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
        let preferredEndpoint = endpointStore.endpointURL
        let candidates = JarvisEndpoints.candidates(override: preferredEndpoint)
        do {
            // A successful authenticated state read is stronger than a separate
            // health probe. Reuse the saved route first, and retain the existing
            // bounded discovery path only as recovery when that route fails.
            let resolved = try await client.resolveState(
                preferredEndpoint: preferredEndpoint,
                candidates: candidates,
                token: endpointStore.token ?? "",
                discoveryTimeout: 3
            )
            endpointStore.endpointURLString = resolved.endpointURL.absoluteString
            return CachedState(state: resolved.state)
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
