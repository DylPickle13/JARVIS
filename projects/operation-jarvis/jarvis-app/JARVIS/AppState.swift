import Foundation
import SwiftUI
import JARVISKit

// App-wide connection + state model. The app auto-discovers the jarvisd
// endpoint (home LAN IP or Tailscale IP) and connects with no token. Later
// milestones add Home/Events/System tabs on top of this same AppState.

@MainActor
public final class AppState: ObservableObject {
    public let store: EndpointStore
    public let client: JarvisClient

    @Published public var connectionState: ConnectionState = .idle
    @Published public var errorMessage: String?
    @Published public var lastState: StateSnapshot?
    @Published public var lastHealth: HealthResponse?
    @Published public var isRefreshing = false
    // M2: events feed + service control.
    @Published public var lastEvents: [EventItem] = []
    @Published public var lastServices: [String: ServiceActionResult] = [:]

    // Optional manual endpoint override (advanced). Empty = auto-discover.
    @Published public var endpointDraft: String

    public init(store: EndpointStore = EndpointStore(), client: JarvisClient = JarvisClient()) {
        self.store = store
        self.client = client
        self.endpointDraft = store.endpointURLString ?? ""
        seedFromLaunchArgumentsIfPresent()
        self.endpointDraft = store.endpointURLString ?? ""
        // Always try to connect on launch (auto-discovery, no token needed).
        Task { await refresh() }
    }

    /// Dev/testing affordance: if launched with `-jarvisSeedEndpoint <url>`
    /// (e.g. via `xcrun simctl launch`), persist it so the app prefers it.
    /// Harmless in production (no one passes these).
    private func seedFromLaunchArgumentsIfPresent() {
        let args = CommandLine.arguments
        func value(for key: String) -> String? {
            guard let i = args.firstIndex(of: key), i + 1 < args.count else { return nil }
            return args[i + 1]
        }
        if let ep = value(for: "-jarvisSeedEndpoint") {
            store.endpointURLString = ep
        }
    }

    /// The endpoint currently in use (last discovered), if any.
    public var currentEndpoint: URL? { store.endpointURL }

    /// Re-discover the endpoint and refresh state. This is what "Connect" and
    /// the launch-time auto-connect both do.
    public func refresh() async {
        connectionState = .connecting
        errorMessage = nil
        isRefreshing = true
        defer { isRefreshing = false }

        // Candidate list: manual override first (if any), then the defaults.
        let override = endpointDraft.isEmpty ? nil : endpointURL(from: endpointDraft)
        let candidates = JarvisEndpoints.candidates(override: override)

        guard let discovered = await client.discover(candidates) else {
            lastState = nil
            lastHealth = nil
            connectionState = .failed
            errorMessage = "Could not reach jarvisd at any known endpoint (tried \(candidates.count))."
            return
        }

        // Remember the working endpoint for next time.
        store.endpointURLString = discovered.absoluteString
        let endpoint = JarvisEndpoint(baseURL: discovered, token: store.token ?? "")

        // Consider connected as soon as /health answers (fast). The state
        // snapshot is fetched separately — it can be slow (plugs/purifier/
        // weather) and shouldn't gate the connection.
        do {
            lastHealth = try await client.health(endpoint)
            connectionState = .connected
            errorMessage = nil
        } catch let error as JarvisError {
            connectionState = .failed
            errorMessage = error.errorDescription ?? "Unknown error"
            return
        } catch {
            connectionState = .failed
            errorMessage = error.localizedDescription
            return
        }

        // Fetch the initial state snapshot in the background (the Home tab
        // also polls it every 10 s).
        Task { await fetchState() }
    }

    /// "Connect" button: re-discover + refresh.
    public func connect() async {
        await refresh()
    }

    // MARK: - Commands (M1)

    /// The endpoint currently in use, wrapped with the stored token.
    private var activeEndpoint: JarvisEndpoint? {
        guard let url = store.endpointURL else { return nil }
        return JarvisEndpoint(baseURL: url, token: store.token ?? "")
    }

    /// Send an allowlisted command to jarvisd. Returns the result, or nil on
    /// failure (errorMessage is set).
    @discardableResult
    public func send(_ action: String, _ params: [String: JSONValue]) async -> CommandResult? {
        guard let endpoint = activeEndpoint else {
            errorMessage = "Not connected."
            return nil
        }
        do {
            return try await client.command(endpoint, action: action, params: params)
        } catch let error as JarvisError {
            errorMessage = error.errorDescription
            return nil
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    /// Re-fetch state from the current endpoint without re-discovering. Used
    /// after commands and for periodic polling on the Home screen.
    public func fetchState() async {
        guard let endpoint = activeEndpoint else { return }
        do {
            let state = try await client.state(endpoint)
            lastState = state
            lastHealth = try? await client.health(endpoint)
            connectionState = .connected
            errorMessage = nil
        } catch {
            // Keep the last good snapshot; don't drop the UI on a blip.
        }
    }

    /// Toggle a smart plug, then refresh the snapshot.
    public func togglePlug(_ name: String) async {
        _ = await send("plug-toggle", ["plug": .string(name)])
        await fetchState()
    }

    /// Set air purifier power (on/off), then refresh.
    public func setPurifierPower(_ on: Bool) async {
        _ = await send("purifier-set", ["setting": .string("power"), "value": .string(on ? "on" : "off")])
        await fetchState()
    }

    /// Set air purifier mode (auto/manual/sleep/pet), then refresh.
    public func setPurifierMode(_ mode: String) async {
        _ = await send("purifier-set", ["setting": .string("mode"), "value": .string(mode)])
        await fetchState()
    }

    /// Set air purifier fan level (1–4), then refresh.
    public func setPurifierFan(_ level: Int) async {
        _ = await send("purifier-set", ["setting": .string("speed"), "level": .number(Double(level))])
        await fetchState()
    }

    // MARK: - Events + services (M2)

    /// Fetch the recent event feed (newest last). Used by the Events tab.
    public func fetchEvents(limit: Int = 100) async {
        guard let endpoint = activeEndpoint else { return }
        do {
            let resp = try await client.events(endpoint, limit: limit)
            lastEvents = resp.events
        } catch {
            // Keep the last good feed on a blip.
        }
    }

    /// Fetch the registered services + their running state. Used by the System tab.
    public func fetchServices() async {
        guard let endpoint = activeEndpoint else { return }
        do {
            let resp = try await client.services(endpoint)
            lastServices = resp.services
        } catch {
            // Keep the last good snapshot.
        }
    }

    /// Lightweight daemon health fetch (version + uptime) for the System tab.
    public func fetchHealth() async {
        guard let endpoint = activeEndpoint else { return }
        lastHealth = try? await client.health(endpoint)
    }

    /// Run a service action (start/stop/restart/status) and refresh the list.
    /// Returns true if the action reported ok.
    @discardableResult
    public func runServiceAction(_ name: String, _ action: String) async -> Bool {
        guard let endpoint = activeEndpoint else {
            errorMessage = "Not connected."
            return false
        }
        do {
            let result = try await client.serviceAction(endpoint, name: name, action: action)
            await fetchServices()
            if !result.ok {
                errorMessage = result.error ?? "\(action) failed for \(name)"
            }
            return result.ok
        } catch let error as JarvisError {
            errorMessage = error.errorDescription
            return false
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    /// Reset: clear the remembered endpoint and re-discover from defaults.
    public func clearConnection() {
        store.clear()
        lastState = nil
        lastHealth = nil
        connectionState = .idle
        errorMessage = nil
        endpointDraft = ""
        Task { await refresh() }
    }

    private func endpointURL(from string: String) -> URL? {
        var s = string.trimmingCharacters(in: .whitespaces)
        if !s.hasPrefix("http://") && !s.hasPrefix("https://") { s = "http://" + s }
        return URL(string: s)
    }
}
