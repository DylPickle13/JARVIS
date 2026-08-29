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
        let candidates = JarvisEndpoints.candidates(override: endpointStore.endpointURL)
        guard let endpointURL = await client.discover(candidates, timeout: 3) else { return cached }
        endpointStore.endpointURLString = endpointURL.absoluteString
        do {
            let state = try await client.state(
                JarvisEndpoint(baseURL: endpointURL, token: endpointStore.token ?? "")
            )
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
}

/// Coalesces only requests that are concurrently in flight. Completed results
/// are deliberately not retained, so every WidgetCenter reload may fetch current
/// state rather than replaying an older process-local attempt.
private actor JARVISWidgetRefreshCoordinator {
    private struct InFlight {
        let id: UUID
        let task: Task<CachedState?, Never>
    }

    private var inFlight: InFlight?

    func refreshedState() async -> CachedState? {
        if let existing = inFlight {
            return await existing.task.value
        }

        let id = UUID()
        let task = Task { await JARVISWidgetStateLoader.fetchState() }
        inFlight = InFlight(id: id, task: task)
        let result = await task.value

        if inFlight?.id == id { inFlight = nil }
        if let result {
            SnapshotStore().save(result.state, at: result.savedAt)
        }
        return result
    }
}
