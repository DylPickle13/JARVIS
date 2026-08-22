import SwiftUI
import JARVISKit

struct WatchConnectView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model = WatchConnectModel()

    var body: some View {
        rootContent
            .task {
                if scenePhase == .active { model.sceneDidBecomeActive() }
                await model.runDebugRelaySmokeIfRequested()
            }
            .onChange(of: scenePhase) { _, phase in
                switch phase {
                case .active:
                    model.sceneDidBecomeActive()
                case .inactive, .background:
                    model.sceneWillResignActive()
                @unknown default:
                    break
                }
            }
    }

    @ViewBuilder
    private var rootContent: some View {
        #if DEBUG && targetEnvironment(simulator)
        if CommandLine.arguments.contains("-jarvisOpenWatchTerminal") {
            NavigationStack { WatchTerminalView(controller: model.terminal) }
        } else {
            NavigationStack { WatchDashboardContent(model: model) }
        }
        #else
        NavigationStack { WatchDashboardContent(model: model) }
        #endif
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
    @Published private(set) var isRefreshing = false

    private struct RelayResponse {
        let result: CommandResult?
        let error: String?
    }

    private var relayResponses: [String: RelayResponse] = [:]
    private let forceEndpointForTesting: Bool
    private let activeRefreshInterval: Duration
    private var debugRelaySmokeDidRun = false
    private var appIsActive = false
    private var refreshGeneration = 0
    private var refreshLoopTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?

    let store = EndpointStore(defaults: JARVISSharedStore.defaults)
    let client = JarvisClient()
    let snapshotStore = SnapshotStore()
    let terminal = WatchTerminalController()

    init(activeRefreshInterval: Duration = JARVISRefreshPolicy.activeInterval) {
        self.activeRefreshInterval = activeRefreshInterval
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
        connectionState != .connected
            || isStale
            || lastState?.subsystems?.plugs?.stale == true
            || lastState?.subsystems?.plugs?.plugs?[name]?.stale == true
    }

    var shouldShowRetry: Bool {
        connectionState == .failed || (isStale && errorMessage != nil)
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

    func sceneDidBecomeActive() {
        guard !appIsActive else { return }
        appIsActive = true
        terminal.sceneDidBecomeActive()
        startRefreshLoop()
    }

    func sceneWillResignActive() {
        appIsActive = false
        refreshLoopTask?.cancel()
        refreshLoopTask = nil
        refreshGeneration += 1
        refreshTask?.cancel()
        refreshTask = nil
        isRefreshing = false
        terminal.sceneWillResignActive()
    }

    func connect() async { await refresh() }

    private func startRefreshLoop() {
        refreshLoopTask?.cancel()
        refreshLoopTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.refresh()
            while !Task.isCancelled, self.appIsActive {
                do {
                    try await Task.sleep(for: self.activeRefreshInterval)
                } catch {
                    return
                }
                guard !Task.isCancelled, self.appIsActive else { return }
                await self.refresh()
            }
        }
    }

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
        if let refreshTask {
            await refreshTask.value
            return
        }
        let generation = refreshGeneration
        isRefreshing = true
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performRefresh()
        }
        refreshTask = task
        await task.value
        if generation == refreshGeneration {
            refreshTask = nil
            isRefreshing = false
        }
    }

    private func performRefresh() async {
        if connectionState != .connected { connectionState = .connecting }
        errorMessage = nil

        let candidates: [URL]
        if forceEndpointForTesting, let endpoint = store.endpointURL {
            candidates = [endpoint]
        } else {
            candidates = JarvisEndpoints.candidates(override: store.endpointURL)
        }
        guard let discovered = await client.discover(candidates, timeout: 3) else {
            guard !Task.isCancelled else { return }
            useRelayOrCache()
            return
        }
        guard !Task.isCancelled else { return }
        store.endpointURLString = discovered.absoluteString
        do {
            let endpoint = JarvisEndpoint(baseURL: discovered, token: store.token ?? "")
            _ = try await client.health(endpoint)
            let state = try await client.state(endpoint)
            guard !Task.isCancelled else { return }
            let previousState = lastState
            lastState = state
            updateJARVISSiriParametersIfNeeded(previous: previousState, current: state)
            snapshotStore.save(state)
            cachedAt = Date()
            isViaPhone = false
            connectionState = .connected
            errorMessage = nil
        } catch is CancellationError {
            return
        } catch let error as JarvisError {
            guard !Task.isCancelled else { return }
            useRelayOrCache(directError: error.errorDescription)
        } catch {
            guard !Task.isCancelled else { return }
            useRelayOrCache(directError: error.localizedDescription)
        }
    }

    private func useRelayOrCache(directError: String? = nil) {
        if WatchBridge.shared.isPhoneReachable {
            isViaPhone = true
            connectionState = lastState == nil ? .connecting : .connected
            WatchBridge.shared.requestState()
            errorMessage = lastState == nil || isStale ? "Waiting for a fresh iPhone relay." : nil
        } else if lastState != nil {
            isViaPhone = false
            connectionState = .failed
            errorMessage = directError ?? "Using cached status; JARVIS is unreachable."
        } else {
            isViaPhone = false
            connectionState = .failed
            errorMessage = directError ?? "JARVIS is unreachable."
        }
    }

    func setPlug(_ name: String, isOn: Bool) async {
        guard busyPlug == nil else { return }
        guard !isPlugStateStale(name) else {
            errorMessage = "Plug data is stale; waiting for an automatic refresh."
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
            WatchBridge.shared.requestState()
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

    nonisolated func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge, requestID: String) {}

    nonisolated func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String) {
        Task { @MainActor [weak self] in
            guard let self, !self.forceEndpointForTesting,
                  let url = URL(string: endpoint), url.scheme != nil, url.host != nil else { return }
            self.store.endpointURLString = url.absoluteString
        }
    }

    nonisolated func watchBridgeDidReceiveTerminalConfiguration(
        _ bridge: WatchBridge,
        configuration: WatchTerminalConfiguration
    ) {
        Task { @MainActor [weak self] in
            self?.terminal.apply(configuration: configuration)
        }
    }

    nonisolated func watchBridgeDidReceiveState(_ bridge: WatchBridge, json: Data) {
        Task { @MainActor [weak self] in
            guard let self, let state = try? JSONDecoder().decode(StateSnapshot.self, from: json) else { return }
            let previousState = self.lastState
            self.lastState = state
            updateJARVISSiriParametersIfNeeded(previous: previousState, current: state)
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
