import Foundation
import Network
import SwiftUI
import WidgetKit
import JARVISKit

public enum AppSection: String, Sendable {
    case home
    case pi
    case jobs
    case settings
}

struct WatchCommandCacheEntry: Sendable {
    let result: CommandResult?
    let error: String?
}

private struct WidgetPlugValue: Equatable {
    let isOn: Bool?
    let stale: Bool?
}

private struct WidgetPurifierValue: Equatable {
    let isOn: Bool?
    let mode: String?
    let fanLevel: Int?
    let fanSetLevel: Int?
    let pm25: Int?
    let filterLife: Int?
    let stale: Bool?
}

private struct WidgetReloadValue: Equatable {
    let overallStale: Bool?
    let plugsStale: Bool?
    let plugs: [String: WidgetPlugValue]
    let purifier: WidgetPurifierValue?
}

/// Main-actor application model. Networking is started by the scene lifecycle,
/// not by init, so cold launch, backgrounding, and network-path changes have a
/// single cancellable owner.
@MainActor
public final class AppState: ObservableObject {
    public let store: EndpointStore
    public let client: any JarvisAPI
    let watchTerminalProvisioning: WatchTerminalProvisioningSettings

    @Published public var connectionState: ConnectionState = .idle
    @Published public var errorMessage: String?
    @Published public var operationErrorMessage: String?
    @Published public var lastState: StateSnapshot?
    @Published public var lastHealth: HealthResponse?
    @Published public var isRefreshing = false
    @Published public var isStateLoading = false
    @Published public var stateErrorMessage: String?

    @Published public var lastServices: [String: ServiceActionResult] = [:]
    @Published public var servicesLoaded = false
    @Published public var servicesLoading = false
    @Published public var servicesErrorMessage: String?

    @Published public var lastScheduledJobs: [ScheduledJob] = []
    @Published public var scheduledJobsSummary: ScheduledJobsSummary?
    @Published public var scheduledJobsLoaded = false
    @Published public var scheduledJobsLoading = false
    @Published public var scheduledJobsErrorMessage: String?

    @Published public var lastScheduledJobResults: [ScheduledJobResult] = []
    @Published public var scheduledJobResultsLoaded = false
    @Published public var scheduledJobResultsLoading = false
    @Published public var scheduledJobResultsErrorMessage: String?
    @Published public private(set) var lastReadScheduledJobResultSequence = 0

    @Published public var signingRenewalStatus: SigningRenewalStatus?
    @Published public var signingRenewalLoading = false
    @Published public var signingRenewalErrorMessage: String?

    @Published public var endpointDraft: String
    @Published public private(set) var busyOperations: Set<String> = []
    @Published public private(set) var activeSection: AppSection = .home

    private var appIsActive = false
    private var networkAvailable = true
    private var retryAllowed = true
    private let activeRefreshInterval: Duration
    private let resultCache: ScheduledJobResultCache
    private let preferences: UserDefaults
    private let resultBaselineKey = "jarvis.jobs.result-baseline-established.v1"
    private let lastReadResultKey = "jarvis.jobs.last-read-sequence.v1"
    private var refreshTask: Task<Void, Never>?
    private var connectionLoopTask: Task<Void, Never>?
    private var stateTask: Task<Void, Never>?
    private var pollingTask: Task<Void, Never>?
    private var pathMonitor: NWPathMonitor?
    var watchCommandResponses: [String: WatchCommandCacheEntry] = [:]
    var watchCommandInFlight: Set<String> = []
    var watchCommandResponseOrder: [String] = []
    let watchCommandCacheLimit = 50

    public init(
        store: EndpointStore? = nil,
        client: any JarvisAPI = JarvisClient(),
        activeRefreshInterval: Duration = JARVISRefreshPolicy.activeInterval,
        preferences: UserDefaults = .standard,
        resultCacheURL: URL? = nil
    ) {
        let resolvedStore = store ?? EndpointStore(defaults: JARVISSharedStore.defaults)
        self.store = resolvedStore
        self.client = client
        self.watchTerminalProvisioning = WatchTerminalProvisioningSettings()
        self.activeRefreshInterval = activeRefreshInterval
        self.preferences = preferences
        self.resultCache = ScheduledJobResultCache(fileURL: resultCacheURL)
        self.endpointDraft = resolvedStore.endpointURLString ?? ""
        self.lastScheduledJobResults = self.resultCache.load()
        self.scheduledJobResultsLoaded = !self.lastScheduledJobResults.isEmpty
        self.lastReadScheduledJobResultSequence = max(0, preferences.integer(forKey: lastReadResultKey))
        seedFromLaunchArgumentsIfPresent()
        self.endpointDraft = resolvedStore.endpointURLString ?? ""
    }

    deinit {
        pathMonitor?.cancel()
        refreshTask?.cancel()
        connectionLoopTask?.cancel()
        stateTask?.cancel()
        pollingTask?.cancel()
    }

    /// Dev/testing affordance: `-jarvisSeedEndpoint <url>` persists an endpoint
    /// before scene activation. It has no effect in normal production launches.
    private func seedFromLaunchArgumentsIfPresent() {
        let args = CommandLine.arguments
        guard let index = args.firstIndex(of: "-jarvisSeedEndpoint"), index + 1 < args.count else { return }
        store.endpointURLString = args[index + 1]
    }

    public var currentEndpoint: URL? { store.endpointURL }

    // MARK: - Scene/network lifecycle

    public func startWatchBridge() {
        WatchBridge.shared.delegate = self
        WatchBridge.shared.start()
        if let snapshot = lastState, let data = try? JSONEncoder().encode(snapshot) {
            // Ordinary publication is latest-value only. Immediate state messages
            // are reserved for an explicit Watch request with its request ID.
            WatchBridge.shared.updateApplicationContext(stateJSON: data, endpoint: currentEndpoint?.absoluteString)
        }
        if let terminalConfiguration = watchTerminalProvisioning.configuration {
            WatchBridge.shared.publishTerminalConfiguration(terminalConfiguration)
        }
    }

    public func sceneDidBecomeActive() {
        guard !appIsActive else { return }
        appIsActive = true
        startPathMonitorIfNeeded()
        if connectionState != .connected {
            startConnectionLoop()
        } else {
            restartPolling(refreshImmediately: true)
        }
    }

    public func sceneWillResignActive() {
        appIsActive = false
        pollingTask?.cancel()
        pollingTask = nil
        refreshTask?.cancel()
        refreshTask = nil
        stateTask?.cancel()
        stateTask = nil
        connectionLoopTask?.cancel()
        connectionLoopTask = nil
    }

    public func setActiveSection(_ section: AppSection) {
        guard activeSection != section else { return }
        activeSection = section
        restartPolling(refreshImmediately: section == .home || section == .jobs)
    }

    private func startPathMonitorIfNeeded() {
        guard pathMonitor == nil else { return }
        let monitor = NWPathMonitor()
        pathMonitor = monitor
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.networkAvailable = path.status == .satisfied
                if self.networkAvailable, self.appIsActive, self.connectionState != .connected {
                    self.startConnectionLoop()
                }
            }
        }
        monitor.start(queue: DispatchQueue(label: "com.operation-jarvis.network-path"))
    }

    private func startConnectionLoop() {
        guard appIsActive, networkAvailable else { return }
        if let existing = connectionLoopTask, !existing.isCancelled {
            return
        }
        connectionLoopTask?.cancel()
        connectionLoopTask = Task { @MainActor [weak self] in
            var delay: Duration = .milliseconds(250)
            while let self, self.appIsActive, !Task.isCancelled {
                await self.refresh()
                if self.connectionState == .connected { return }
                guard self.retryAllowed else { return }
                try? await Task.sleep(for: delay)
                delay = min(delay * 2, .seconds(30))
            }
        }
    }

    // MARK: - Connection

    public func refresh() async {
        refreshTask?.cancel()
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performRefresh()
        }
        refreshTask = task
        await task.value
    }

    private func performRefresh() async {
        connectionState = .connecting
        errorMessage = nil
        retryAllowed = true
        isRefreshing = true
        defer { isRefreshing = false }

        let override: URL?
        if endpointDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            override = nil
        } else if let parsed = endpointURL(from: endpointDraft) {
            override = parsed
        } else {
            connectionState = .failed
            retryAllowed = false
            errorMessage = "The endpoint is not a valid URL."
            return
        }

        let candidates = JarvisEndpoints.candidates(override: override)
        guard let discovered = await client.discover(candidates, timeout: 3.0) else {
            connectionState = .failed
            errorMessage = "Could not reach jarvisd at any known endpoint (tried \(candidates.count))."
            return
        }

        store.endpointURLString = discovered.absoluteString
        let endpoint = JarvisEndpoint(baseURL: discovered, token: store.token ?? "")
        do {
            lastHealth = try await client.health(endpoint)
            connectionState = .connected
            errorMessage = nil
            if activeSection == .home {
                await refreshHomeResources(refreshHealth: false)
            } else {
                await refreshJobs()
            }
            restartPolling(refreshImmediately: false)
        } catch let error as JarvisError {
            connectionState = .failed
            retryAllowed = error.isRetryable
            errorMessage = error.errorDescription ?? "Could not connect to jarvisd."
        } catch is CancellationError {
            return
        } catch {
            connectionState = .failed
            errorMessage = error.localizedDescription
        }
    }

    public func connect() async {
        connectionLoopTask?.cancel()
        await refresh()
        if connectionState != .connected { startConnectionLoop() }
    }

    // MARK: - State

    private var activeEndpoint: JarvisEndpoint? {
        guard let url = store.endpointURL else { return nil }
        return JarvisEndpoint(baseURL: url, token: store.token ?? "")
    }

    public func fetchState() async {
        guard activeEndpoint != nil else { return }
        stateTask?.cancel()
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performFetchState()
        }
        stateTask = task
        await task.value
    }

    private func performFetchState() async {
        guard let endpoint = activeEndpoint else { return }
        isStateLoading = true
        defer { isStateLoading = false }
        do {
            let snapshot = try await client.state(endpoint)
            let previousState = lastState
            let widgetsChanged = widgetReloadValue(previousState) != widgetReloadValue(snapshot)
            lastState = snapshot
            SnapshotStore().save(snapshot)
            if widgetsChanged { WidgetCenter.shared.reloadAllTimelines() }
            if let data = try? JSONEncoder().encode(snapshot) {
                // Application context coalesces routine snapshots and remains
                // available when the Watch was not immediately reachable.
                WatchBridge.shared.updateApplicationContext(stateJSON: data, endpoint: currentEndpoint?.absoluteString)
            }
            stateErrorMessage = nil
            connectionState = .connected
        } catch is CancellationError {
            return
        } catch let error as JarvisError {
            stateErrorMessage = error.errorDescription
            if lastState == nil { errorMessage = error.errorDescription }
            if error.isRetryable {
                connectionState = .failed
                retryAllowed = true
                if appIsActive { startConnectionLoop() }
            } else {
                retryAllowed = false
            }
        } catch {
            stateErrorMessage = error.localizedDescription
            if lastState == nil { errorMessage = error.localizedDescription }
            connectionState = .failed
            retryAllowed = true
            if appIsActive { startConnectionLoop() }
        }
    }

    private func widgetReloadValue(_ state: StateSnapshot?) -> WidgetReloadValue? {
        guard let state else { return nil }
        let plugs = (state.subsystems?.plugs?.plugs ?? [:]).mapValues {
            WidgetPlugValue(isOn: $0.isOn, stale: $0.stale)
        }
        let purifier = state.subsystems?.purifier.map {
            WidgetPurifierValue(
                isOn: $0.isOn,
                mode: $0.mode,
                fanLevel: $0.fanLevel,
                fanSetLevel: $0.fanSetLevel,
                pm25: $0.pm25,
                filterLife: $0.filterLife,
                stale: $0.stale
            )
        }
        return WidgetReloadValue(
            overallStale: state.stale,
            plugsStale: state.subsystems?.plugs?.stale,
            plugs: plugs,
            purifier: purifier
        )
    }

    // MARK: - Commands

    public func isOperationBusy(_ key: String) -> Bool {
        busyOperations.contains(key)
    }

    private func beginOperation(_ key: String) -> Bool {
        guard !busyOperations.contains(key) else { return false }
        var updated = busyOperations
        updated.insert(key)
        busyOperations = updated
        operationErrorMessage = nil
        return true
    }

    private func endOperation(_ key: String) {
        var updated = busyOperations
        updated.remove(key)
        busyOperations = updated
    }

    @discardableResult
    public func send(_ action: String, _ params: [String: JSONValue] = [:]) async -> CommandResult? {
        guard let endpoint = activeEndpoint else {
            operationErrorMessage = "Not connected."
            return nil
        }
        do {
            let result = try await client.command(endpoint, action: action, params: params)
            if !result.ok {
                operationErrorMessage = result.error ?? "\(action) failed."
            }
            return result
        } catch let error as JarvisError {
            operationErrorMessage = error.errorDescription
            return nil
        } catch is CancellationError {
            return nil
        } catch {
            operationErrorMessage = error.localizedDescription
            return nil
        }
    }

    private func runCommand(
        key: String,
        action: String,
        params: [String: JSONValue],
        refreshState: Bool = true
    ) async -> Bool {
        guard beginOperation(key) else { return false }
        defer { endOperation(key) }
        guard let result = await send(action, params), result.ok else { return false }
        if refreshState { await fetchState() }
        return true
    }

    public func setPlug(_ name: String, isOn: Bool) async -> Bool {
        await runCommand(
            key: "plug:\(name)",
            action: isOn ? "plug-on" : "plug-off",
            params: ["plug": .string(name)]
        )
    }

    func executeWatchPlugCommand(_ name: String, isOn: Bool) async -> CommandResult {
        let action = isOn ? "plug-on" : "plug-off"
        guard beginOperation("plug:\(name)") else {
            return CommandResult(ok: false, action: action, error: "A plug operation is already in progress.")
        }
        defer { endOperation("plug:\(name)") }

        // Every relayed write is validated against a fresh phone-side snapshot.
        // A Watch cache may resolve speech, but can never authorize a command.
        await fetchState()
        guard currentEndpoint != nil,
              connectionState == .connected,
              stateErrorMessage == nil else {
            return CommandResult(ok: false, action: action, error: "Fresh plug status is unavailable.")
        }
        let plug: JARVISPlugDescriptor
        do {
            guard let snapshot = lastState else { throw JARVISPlugCatalogError.unavailable }
            plug = try JARVISPlugCatalog.freshPlug(id: name, in: snapshot)
        } catch let error as JARVISPlugCatalogError {
            return CommandResult(ok: false, action: action, error: error.errorDescription)
        } catch {
            return CommandResult(ok: false, action: action, error: "Fresh plug status is unavailable.")
        }
        if plug.isOn == isOn {
            return CommandResult(
                ok: true,
                action: action,
                plug: PlugCommandData(name: name, is_on: isOn),
                summary: "already-in-desired-state"
            )
        }

        guard let result = await send(action, ["plug": .string(name)]), result.ok else {
            return CommandResult(ok: false, action: action, error: operationErrorMessage ?? "The plug command failed.")
        }
        if result.plug?.name == name, result.plug?.is_on == isOn { return result }

        await fetchState()
        guard connectionState == .connected,
              stateErrorMessage == nil,
              let snapshot = lastState,
              let confirmed = try? JARVISPlugCatalog.freshPlug(id: name, in: snapshot),
              confirmed.isOn == isOn else {
            return CommandResult(ok: false, action: action, error: "The plug result could not be confirmed.")
        }
        return CommandResult(
            ok: true,
            action: action,
            plug: PlugCommandData(name: name, is_on: isOn)
        )
    }

    func executeWatchPurifierCommand(_ command: WatchPurifierCommand) async -> CommandResult {
        let action = "purifier-set"
        guard command.isValid else {
            return CommandResult(ok: false, action: action, error: "The air-purifier command was invalid.")
        }
        guard beginOperation("purifier") else {
            return CommandResult(ok: false, action: action, error: "An air-purifier operation is already in progress.")
        }
        defer { endOperation("purifier") }

        // As with plug relays, only a fresh phone-side snapshot may authorize a
        // Watch write. Cached Watch state is presentation data, not authority.
        await fetchState()
        guard currentEndpoint != nil,
              connectionState == .connected,
              stateErrorMessage == nil,
              let snapshot = lastState,
              snapshot.stale != true,
              let purifier = snapshot.subsystems?.purifier,
              purifier.ok == true,
              purifier.stale != true else {
            return CommandResult(ok: false, action: action, error: "Fresh air-purifier status is unavailable.")
        }
        if command.matches(purifier) {
            return CommandResult(ok: true, action: action, summary: "already-in-desired-state")
        }

        guard let result = await send(action, command.parameters), result.ok else {
            return CommandResult(ok: false, action: action, error: operationErrorMessage ?? "The air-purifier command failed.")
        }

        // VeSync can accept a write while returning its previous cloud state.
        // Preserve that distinct pending outcome so both native clients can
        // show confirmation progress instead of a misleading hard failure.
        if result.purifierVerificationPending {
            await fetchState()
            return result
        }

        // Never infer confirmed success from transport delivery alone. Refresh
        // once and report confirmation only when the requested state is visible.
        await fetchState()
        guard connectionState == .connected,
              stateErrorMessage == nil,
              lastState?.stale != true,
              let confirmed = lastState?.subsystems?.purifier,
              confirmed.ok == true,
              confirmed.stale != true,
              command.matches(confirmed) else {
            return CommandResult(ok: false, action: action, error: "The air-purifier result could not be confirmed.")
        }
        return result
    }

    func rememberWatchCommand(_ requestID: String, entry: WatchCommandCacheEntry) {
        guard !requestID.isEmpty else { return }
        watchCommandResponses[requestID] = entry
        watchCommandResponseOrder.removeAll { $0 == requestID }
        watchCommandResponseOrder.append(requestID)
        while watchCommandResponseOrder.count > watchCommandCacheLimit {
            let oldest = watchCommandResponseOrder.removeFirst()
            watchCommandResponses.removeValue(forKey: oldest)
        }
    }

    /// Compatibility helper for older callers. The native UI uses setPlug so
    /// desired-state writes are idempotent.
    public func togglePlug(_ name: String) async {
        guard let state = lastState?.subsystems?.plugs?.plugs?[name]?.isOn else {
            operationErrorMessage = "Plug state is unavailable."
            return
        }
        _ = await setPlug(name, isOn: !state)
    }

    public func setPurifierPower(_ on: Bool) async {
        _ = await runCommand(
            key: "purifier",
            action: "purifier-set",
            params: ["setting": .string("power"), "value": .string(on ? "on" : "off")]
        )
    }

    public func setPurifierMode(_ mode: String) async {
        _ = await runCommand(
            key: "purifier",
            action: "purifier-set",
            params: ["setting": .string("mode"), "value": .string(mode)]
        )
    }

    public func setPurifierFan(_ level: Int) async {
        _ = await runCommand(
            key: "purifier",
            action: "purifier-set",
            params: ["setting": .string("speed"), "level": .number(Double(level))]
        )
    }

    // MARK: - Services

    public func fetchServices() async {
        guard let endpoint = activeEndpoint else { return }
        servicesLoading = true
        defer { servicesLoading = false }
        do {
            let response = try await client.services(endpoint)
            lastServices = response.services
            servicesLoaded = true
            servicesErrorMessage = nil
        } catch let error as JarvisError {
            servicesErrorMessage = error.errorDescription
        } catch is CancellationError {
            return
        } catch {
            servicesErrorMessage = error.localizedDescription
        }
    }

    public func fetchScheduledJobs() async {
        guard let endpoint = activeEndpoint else { return }
        scheduledJobsLoading = true
        defer { scheduledJobsLoading = false }
        do {
            let response = try await client.scheduledJobs(endpoint)
            scheduledJobsLoaded = true
            guard response.ok else {
                scheduledJobsErrorMessage = response.error ?? "Scheduled-job status is unavailable."
                return
            }
            lastScheduledJobs = response.jobs
            scheduledJobsSummary = response.summary
            scheduledJobsErrorMessage = nil
        } catch let error as JarvisError {
            scheduledJobsLoaded = true
            scheduledJobsErrorMessage = error.errorDescription
        } catch is CancellationError {
            return
        } catch {
            scheduledJobsLoaded = true
            scheduledJobsErrorMessage = error.localizedDescription
        }
    }

    public var unreadScheduledJobResultCount: Int {
        lastScheduledJobResults.filter { $0.sequence > lastReadScheduledJobResultSequence }.count
    }

    public func scheduledJobResult(sequence: Int) -> ScheduledJobResult? {
        lastScheduledJobResults.first { $0.sequence == sequence }
    }

    public func markScheduledJobResultsRead() {
        guard let newest = lastScheduledJobResults.map(\.sequence).max(),
              newest > lastReadScheduledJobResultSequence else { return }
        lastReadScheduledJobResultSequence = newest
        preferences.set(newest, forKey: lastReadResultKey)
        preferences.set(true, forKey: resultBaselineKey)
    }

    public func fetchScheduledJobResults(after explicitCursor: Int? = nil) async {
        guard let endpoint = activeEndpoint, !scheduledJobResultsLoading else { return }
        scheduledJobResultsLoading = true
        defer { scheduledJobResultsLoading = false }
        let currentNewest = lastScheduledJobResults.map(\.sequence).max()
        let cursor = explicitCursor ?? currentNewest
        do {
            let response = try await client.scheduledJobResults(
                endpoint,
                after: cursor,
                limit: ScheduledJobResultCache.limit,
                jobId: nil
            )
            scheduledJobResultsLoaded = true
            guard response.ok else {
                scheduledJobResultsErrorMessage = response.error ?? "Scheduled-job results are unavailable."
                return
            }
            lastScheduledJobResults = ScheduledJobResultCache.merging(
                cached: lastScheduledJobResults,
                incoming: response.results
            )
            resultCache.save(lastScheduledJobResults)
            if !preferences.bool(forKey: resultBaselineKey) {
                let baseline = lastScheduledJobResults.map(\.sequence).max() ?? 0
                lastReadScheduledJobResultSequence = baseline
                preferences.set(baseline, forKey: lastReadResultKey)
                preferences.set(true, forKey: resultBaselineKey)
            }
            scheduledJobResultsErrorMessage = nil
        } catch let error as JarvisError {
            scheduledJobResultsLoaded = true
            scheduledJobResultsErrorMessage = error.errorDescription
        } catch is CancellationError {
            return
        } catch {
            scheduledJobResultsLoaded = true
            scheduledJobResultsErrorMessage = error.localizedDescription
        }
    }

    public func fetchScheduledJobResult(sequence: Int) async {
        guard sequence > 0 else { return }
        if scheduledJobResult(sequence: sequence) != nil { return }
        await fetchScheduledJobResults(after: sequence - 1)
    }

    public func fetchHealth() async {
        guard let endpoint = activeEndpoint else { return }
        do {
            lastHealth = try await client.health(endpoint)
        } catch let error as JarvisError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @discardableResult
    public func runServiceAction(_ name: String, _ action: String) async -> Bool {
        let key = "service:\(name)"
        guard beginOperation(key) else { return false }
        defer { endOperation(key) }
        guard let endpoint = activeEndpoint else {
            operationErrorMessage = "Not connected."
            return false
        }
        do {
            let result = try await client.serviceAction(endpoint, name: name, action: action)
            await fetchServices()
            guard result.ok else {
                operationErrorMessage = result.error ?? "\(action.capitalized) failed for \(name)."
                return false
            }
            operationErrorMessage = nil
            return true
        } catch let error as JarvisError {
            operationErrorMessage = error.errorDescription
            return false
        } catch is CancellationError {
            return false
        } catch {
            operationErrorMessage = error.localizedDescription
            return false
        }
    }

    // MARK: - Developer signing

    public func fetchSigningRenewalStatus() async {
        guard let endpoint = activeEndpoint else {
            signingRenewalErrorMessage = "Connect to the JARVIS daemon first."
            return
        }
        signingRenewalLoading = true
        defer { signingRenewalLoading = false }
        do {
            signingRenewalStatus = try await client.signingRenewalStatus(endpoint)
            signingRenewalErrorMessage = nil
        } catch is CancellationError {
            return
        } catch let error as JarvisError {
            signingRenewalErrorMessage = error.errorDescription
        } catch {
            signingRenewalErrorMessage = error.localizedDescription
        }
    }

    @discardableResult
    public func startSigningRenewal() async -> Bool {
        guard !signingRenewalLoading else { return false }
        guard let endpoint = activeEndpoint else {
            signingRenewalErrorMessage = "Connect to the JARVIS daemon first."
            return false
        }
        signingRenewalLoading = true
        defer { signingRenewalLoading = false }
        do {
            let status = try await client.startSigningRenewal(endpoint)
            signingRenewalStatus = status
            signingRenewalErrorMessage = nil
            return status.running
        } catch is CancellationError {
            return false
        } catch let error as JarvisError {
            signingRenewalErrorMessage = error.errorDescription
            return false
        } catch {
            signingRenewalErrorMessage = error.localizedDescription
            return false
        }
    }

    // MARK: - Polling

    public func refreshHome() async {
        await refreshHomeResources(refreshHealth: true)
    }

    public func refreshJobs() async {
        async let jobs: Void = fetchScheduledJobs()
        async let results: Void = fetchScheduledJobResults()
        _ = await (jobs, results)
    }

    private func refreshHomeResources(refreshHealth: Bool) async {
        async let state: Void = fetchState()
        async let services: Void = fetchServices()
        async let jobs: Void = fetchScheduledJobs()
        async let results: Void = fetchScheduledJobResults()
        if refreshHealth {
            async let health: Void = fetchHealth()
            _ = await (state, services, jobs, results, health)
        } else {
            _ = await (state, services, jobs, results)
        }
    }

    private func restartPolling(refreshImmediately: Bool) {
        pollingTask?.cancel()
        pollingTask = nil
        guard appIsActive, connectionState == .connected else { return }
        pollingTask = Task { @MainActor [weak self] in
            guard let self else { return }
            if refreshImmediately {
                if self.activeSection == .home {
                    await self.refreshHome()
                } else {
                    await self.refreshJobs()
                }
            }
            while !Task.isCancelled, self.appIsActive, self.connectionState == .connected {
                do {
                    try await Task.sleep(for: self.activeRefreshInterval)
                } catch {
                    return
                }
                guard !Task.isCancelled, self.appIsActive, self.connectionState == .connected else { return }
                if self.activeSection == .home {
                    await self.refreshHome()
                } else {
                    // Jobs remain current while any app tab is active. Terminal,
                    // Settings, hardware state, and service polling remain idle
                    // outside Home.
                    await self.refreshJobs()
                }
            }
        }
    }

    // MARK: - Reset

    public func clearConnection() {
        refreshTask?.cancel()
        connectionLoopTask?.cancel()
        stateTask?.cancel()
        pollingTask?.cancel()
        store.clear()
        lastState = nil
        lastHealth = nil
        lastServices = [:]
        lastScheduledJobs = []
        scheduledJobsSummary = nil
        servicesLoaded = false
        scheduledJobsLoaded = false
        scheduledJobsErrorMessage = nil
        scheduledJobResultsLoading = false
        scheduledJobResultsErrorMessage = nil
        connectionState = .idle
        errorMessage = nil
        stateErrorMessage = nil
        operationErrorMessage = nil
        endpointDraft = ""
        if appIsActive { startConnectionLoop() }
    }

    private func endpointURL(from string: String) -> URL? {
        JarvisEndpointURLPolicy.parse(string)
    }
}
