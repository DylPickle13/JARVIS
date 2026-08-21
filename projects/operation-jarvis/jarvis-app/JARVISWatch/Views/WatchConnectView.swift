import SwiftUI
import JARVISKit

struct WatchConnectView: View {
    @StateObject private var model = WatchConnectModel()

    var body: some View {
        WatchDashboardContent(model: model)
            .task {
                await model.refreshIfConfigured()
                await model.runDebugRelaySmokeIfRequested()
            }
    }
}

@MainActor
final class WatchConnectModel: ObservableObject, WatchBridgeDelegate {
    @Published var connectionState: ConnectionState = .idle
    @Published var errorMessage: String?
    @Published var lastState: StateSnapshot?
    @Published var isViaPhone = false
    @Published var cachedAt: Date?
    @Published var busyPlug: String?
    @Published var pendingRelay = false

    private struct RelayResponse {
        let result: CommandResult?
        let error: String?
    }

    private var relayResponses: [String: RelayResponse] = [:]
    private let forceEndpointForTesting: Bool
    private var debugRelaySmokeDidRun = false

    let store = EndpointStore(defaults: JARVISSharedStore.defaults)
    let client = JarvisClient()
    let snapshotStore = SnapshotStore()

    init() {
        #if DEBUG
        let arguments = CommandLine.arguments
        forceEndpointForTesting = arguments.contains("-jarvisForceEndpoint")
        if let index = arguments.firstIndex(of: "-jarvisSeedEndpoint"), index + 1 < arguments.count {
            store.endpointURLString = arguments[index + 1]
        }
        #else
        forceEndpointForTesting = false
        #endif
        if let cached = snapshotStore.load() {
            lastState = cached.state
            cachedAt = cached.savedAt
        }
        WatchBridge.shared.delegate = self
    }

    var isStale: Bool {
        guard let cachedAt else { return lastState?.stale == true }
        return Date().timeIntervalSince(cachedAt) > 900 || lastState?.stale == true
    }

    func isPlugStateStale(_ name: String) -> Bool {
        isStale
            || lastState?.subsystems?.plugs?.stale == true
            || lastState?.subsystems?.plugs?.plugs?[name]?.stale == true
    }

    var dotColor: Color {
        switch connectionState {
        case .connected: return isStale ? .orange : .green
        case .failed: return .red
        case .connecting: return .orange
        case .idle: return .secondary
        }
    }

    var statusText: String {
        switch connectionState {
        case .connected:
            if pendingRelay { return "Waiting for iPhone" }
            return isViaPhone ? "Via iPhone" : (isStale ? "Connected · stale" : "Connected")
        case .failed: return "Offline"
        case .connecting: return "Connecting"
        case .idle: return "Idle"
        }
    }

    func refreshIfConfigured() async { await refresh() }
    func connect() async { await refresh() }

    func runDebugRelaySmokeIfRequested() async {
        #if DEBUG
        guard !debugRelaySmokeDidRun else { return }
        let arguments = CommandLine.arguments
        guard let plugIndex = arguments.firstIndex(of: "-jarvisRelaySmokePlug"), plugIndex + 1 < arguments.count,
              let stateIndex = arguments.firstIndex(of: "-jarvisRelaySmokeState"), stateIndex + 1 < arguments.count else { return }
        let rawState = arguments[stateIndex + 1].lowercased()
        guard rawState == "on" || rawState == "off" else { return }
        debugRelaySmokeDidRun = true
        let plug = arguments[plugIndex + 1]
        let reachabilityDeadline = Date().addingTimeInterval(30)
        while !WatchBridge.shared.isPhoneReachable && Date() < reachabilityDeadline {
            try? await Task.sleep(for: .milliseconds(100))
        }
        NSLog(
            "[JARVIS Watch smoke] begin plug=%@ desired=%@ viaPhone=%@ reachable=%@",
            plug,
            rawState,
            isViaPhone ? "yes" : "no",
            WatchBridge.shared.isPhoneReachable ? "yes" : "no"
        )
        await setPlug(plug, isOn: rawState == "on")
        NSLog("[JARVIS Watch smoke] end error=%@", errorMessage ?? "none")
        #endif
    }

    func refresh() async {
        connectionState = .connecting
        errorMessage = nil
        let candidates: [URL]
        if forceEndpointForTesting, let endpoint = store.endpointURL {
            candidates = [endpoint]
        } else {
            candidates = JarvisEndpoints.candidates(override: store.endpointURL)
        }
        guard let discovered = await client.discover(candidates, timeout: 3) else {
            if WatchBridge.shared.isPhoneReachable {
                isViaPhone = true
                connectionState = .connected
                WatchBridge.shared.requestState()
                if lastState == nil { errorMessage = "Waiting for the iPhone relay." }
            } else if lastState != nil {
                connectionState = .connected
                isViaPhone = true
                errorMessage = "Using cached status; no relay is reachable."
            } else {
                connectionState = .failed
                errorMessage = "JARVIS is unreachable."
            }
            return
        }
        store.endpointURLString = discovered.absoluteString
        do {
            let endpoint = JarvisEndpoint(baseURL: discovered, token: store.token ?? "")
            _ = try await client.health(endpoint)
            let state = try await client.state(endpoint)
            lastState = state
            snapshotStore.save(state)
            cachedAt = Date()
            isViaPhone = false
            connectionState = .connected
        } catch let error as JarvisError {
            connectionState = .failed
            errorMessage = error.errorDescription
        } catch {
            connectionState = .failed
            errorMessage = error.localizedDescription
        }
    }

    func setPlug(_ name: String, isOn: Bool) async {
        guard busyPlug == nil else { return }
        guard !isPlugStateStale(name) else {
            errorMessage = "Plug data is stale; refresh before changing it."
            return
        }
        busyPlug = name
        defer { busyPlug = nil }
        if isViaPhone || store.endpointURL == nil {
            guard WatchBridge.shared.isPhoneReachable else {
                errorMessage = "The iPhone relay is unavailable."
                return
            }
            let requestID = UUID().uuidString
            pendingRelay = true
            defer { pendingRelay = false }
            guard WatchBridge.shared.sendPlugCommand(name: name, isOn: isOn, requestID: requestID) else {
                errorMessage = "Could not send the command to the iPhone."
                return
            }
            guard let response = await waitForRelayResponse(requestID) else {
                errorMessage = "The iPhone relay timed out."
                return
            }
            guard let result = response.result, result.ok else {
                errorMessage = response.error ?? response.result?.error ?? "The relayed plug command failed."
                return
            }
            errorMessage = nil
            return
        }
        guard let endpoint = store.endpoint else {
            errorMessage = "No endpoint available."
            return
        }
        do {
            let result = try await client.command(endpoint, action: isOn ? "plug-on" : "plug-off", params: ["plug": .string(name)])
            guard result.ok else {
                errorMessage = result.error ?? "Plug command failed."
                return
            }
            await refresh()
        } catch let error as JarvisError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func waitForRelayResponse(_ requestID: String) async -> RelayResponse? {
        let deadline = Date().addingTimeInterval(30)
        while Date() < deadline {
            if let response = relayResponses.removeValue(forKey: requestID) { return response }
            if Task.isCancelled { return nil }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return relayResponses.removeValue(forKey: requestID)
    }

    nonisolated func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge) {}

    nonisolated func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String) {
        Task { @MainActor [weak self] in
            guard let self, !self.forceEndpointForTesting,
                  let url = URL(string: endpoint), url.scheme != nil, url.host != nil else { return }
            self.store.endpointURLString = url.absoluteString
        }
    }

    nonisolated func watchBridgeDidReceiveState(_ bridge: WatchBridge, json: Data) {
        Task { @MainActor [weak self] in
            guard let self, let state = try? JSONDecoder().decode(StateSnapshot.self, from: json) else { return }
            self.lastState = state
            self.snapshotStore.save(state)
            self.cachedAt = Date()
            self.isViaPhone = true
            self.connectionState = .connected
            self.errorMessage = nil
        }
    }

    nonisolated func watchBridgeDidReceivePlugCommand(_ bridge: WatchBridge, name: String, isOn: Bool, requestID: String) {}

    nonisolated func watchBridgeDidReceiveCommandResult(_ bridge: WatchBridge, requestID: String, result: CommandResult) {
        Task { @MainActor [weak self] in
            self?.relayResponses[requestID] = RelayResponse(result: result, error: nil)
        }
    }

    nonisolated func watchBridgeDidReceiveCommandError(_ bridge: WatchBridge, requestID: String, error: WatchCommandError) {
        Task { @MainActor [weak self] in
            self?.relayResponses[requestID] = RelayResponse(result: nil, error: error.message)
        }
    }
}

enum WatchFormat {
    static func displayName(_ raw: String) -> String {
        raw.replacingOccurrences(of: "-", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }
}

#Preview {
    WatchConnectView()
}
