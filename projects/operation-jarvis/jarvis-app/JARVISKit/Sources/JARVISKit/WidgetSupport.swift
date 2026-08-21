import Foundation

/// Shared, target-local widget state loading. Personal Team builds cannot use
/// an App Group, so each widget process keeps its own cache and discovers
/// jarvisd directly when no endpoint is stored in that target's sandbox.
public enum JARVISWidgetStateLoader {
    public static let timelineRefreshInterval: TimeInterval = 15 * 60
    public static let staleAfter: TimeInterval = 15 * 60
    private static let refreshCoordinator = JARVISWidgetRefreshCoordinator()

    public static func cachedState() -> CachedState? {
        SnapshotStore().load()
    }

    public static func refreshedState() async -> CachedState? {
        await refreshCoordinator.refreshedState()
    }

    fileprivate static func fetchState() async -> CachedState? {
        let store = SnapshotStore()
        let cached = store.load()
        let endpointStore = EndpointStore(defaults: JARVISSharedStore.defaults)
        let client = JarvisClient()
        let endpointURL: URL?
        if let saved = endpointStore.endpointURL {
            endpointURL = saved
        } else {
            endpointURL = await client.discover(JarvisEndpoints.candidates(override: nil), timeout: 3)
        }
        guard let endpointURL else { return cached }
        do {
            let state = try await client.state(
                JarvisEndpoint(baseURL: endpointURL, token: endpointStore.token ?? "")
            )
            store.save(state)
            return CachedState(state: state)
        } catch {
            return cached
        }
    }

    public static func isStale(
        _ cached: CachedState?,
        subsystemStale: Bool = false,
        itemStale: Bool = false,
        now: Date = Date()
    ) -> Bool {
        guard let cached else { return true }
        return cached.state.stale == true
            || subsystemStale
            || itemStale
            || now.timeIntervalSince(cached.savedAt) > staleAfter
    }

    public static func plugNames(from cached: CachedState?) -> [String] {
        guard cached?.state.subsystems?.plugs?.ok == true else { return [] }
        return (cached?.state.subsystems?.plugs?.plugs ?? [:]).keys.sorted()
    }
}

private actor JARVISWidgetRefreshCoordinator {
    private var inFlight: Task<CachedState?, Never>?
    private var lastAttempt: Date?
    private var lastResult: CachedState?

    func refreshedState() async -> CachedState? {
        if let lastAttempt, Date().timeIntervalSince(lastAttempt) < 30 {
            return lastResult
        }
        if let inFlight { return await inFlight.value }
        let task = Task { await JARVISWidgetStateLoader.fetchState() }
        inFlight = task
        let result = await task.value
        lastAttempt = Date()
        lastResult = result
        inFlight = nil
        return result
    }
}
