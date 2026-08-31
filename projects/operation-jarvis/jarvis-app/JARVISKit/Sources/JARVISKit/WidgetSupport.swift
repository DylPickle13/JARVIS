import Foundation
import OSLog

/// Shared, target-local widget state loading. Personal Team builds cannot use
/// an App Group, so each widget process keeps its own cache and discovers
/// jarvisd directly when no endpoint is stored in that target's sandbox.
public enum JARVISWidgetStateLoader {
    public static let timelineRefreshInterval: TimeInterval = 15 * 60
    public static let staleAfter: TimeInterval = 15 * 60
    public static let timelineRefreshDeadline: TimeInterval = 8
    private static let refreshCoordinator = JARVISWidgetRefreshCoordinator()
    private static let logger = Logger(
        subsystem: "com.operation-jarvis.jarvis.widgets",
        category: "state-refresh"
    )

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
            let token = endpointStore.token ?? ""
            let resolved = try await JARVISWidgetRefreshDeadline.run(
                seconds: timelineRefreshDeadline
            ) {
                try await client.resolveState(
                    preferredEndpoint: preferredEndpoint,
                    candidates: candidates,
                    token: token,
                    discoveryTimeout: 3
                )
            }
            endpointStore.endpointURLString = resolved.endpointURL.absoluteString
            logger.info("Widget state refresh source=network")
            return CachedState(state: resolved.state)
        } catch JARVISWidgetRefreshDeadlineError.exceeded {
            logger.info(
                "Widget state refresh source=cache outcome=deadline age=\(cacheAgeBucket(cached), privacy: .public)"
            )
            return cached
        } catch {
            logger.info(
                "Widget state refresh source=cache outcome=failure age=\(cacheAgeBucket(cached), privacy: .public)"
            )
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

    private static func cacheAgeBucket(_ cached: CachedState?, now: Date = Date()) -> String {
        guard let cached else { return "missing" }
        let age = max(0, now.timeIntervalSince(cached.savedAt))
        if age <= staleAfter { return "fresh" }
        if age <= 60 * 60 { return "stale-under-hour" }
        return "stale-over-hour"
    }
}

/// Applies a cancellation-aware outer boundary around endpoint recovery so a
/// widget provider can always fall back to its existing target-local cache.
enum JARVISWidgetRefreshDeadlineError: Error, Equatable, Sendable {
    case exceeded
}

enum JARVISWidgetRefreshDeadline {
    static func run<T: Sendable>(
        seconds: TimeInterval,
        operation: @escaping @Sendable () async throws -> T
    ) async throws -> T {
        let boundedSeconds = min(max(seconds, 0.05), 60)
        let nanoseconds = UInt64(boundedSeconds * 1_000_000_000)

        return try await withThrowingTaskGroup(of: T.self, returning: T.self) { group in
            group.addTask {
                try await operation()
            }
            group.addTask {
                try await Task.sleep(nanoseconds: nanoseconds)
                try Task.checkCancellation()
                throw JARVISWidgetRefreshDeadlineError.exceeded
            }
            defer { group.cancelAll() }
            guard let result = try await group.next() else {
                throw JARVISWidgetRefreshDeadlineError.exceeded
            }
            return result
        }
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
