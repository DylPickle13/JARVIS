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

    /// Invalidates an older in-flight timeline read, then writes the confirmed
    /// command result into this widget target's cache. The daemon remains the
    /// authority; the next timeline request still performs a direct refresh.
    @discardableResult
    public static func applyConfirmedPlugState(name: String, isOn: Bool, at date: Date = Date()) async -> CachedState? {
        await refreshCoordinator.invalidate()
        return SnapshotStore().applyConfirmedPlugState(name: name, isOn: isOn, at: date)
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

    public static func plugNames(from cached: CachedState?) -> [String] {
        guard cached?.state.subsystems?.plugs?.ok == true else { return [] }
        return (cached?.state.subsystems?.plugs?.plugs ?? [:]).keys.sorted()
    }
}

/// Coalesces only requests that are concurrently in flight. Completed results
/// are deliberately not retained: a WidgetCenter reload after a command must
/// fetch current state instead of replaying a pre-command snapshot.
private actor JARVISWidgetRefreshCoordinator {
    private struct InFlight {
        let id: UUID
        let generation: Int
        let task: Task<CachedState?, Never>
    }

    private var inFlight: InFlight?
    private var generation = 0

    func refreshedState() async -> CachedState? {
        if let existing = inFlight {
            let result = await existing.task.value
            return generation == existing.generation ? result : SnapshotStore().load()
        }

        let id = UUID()
        let requestGeneration = generation
        let task = Task { await JARVISWidgetStateLoader.fetchState() }
        inFlight = InFlight(id: id, generation: requestGeneration, task: task)
        let result = await task.value

        if inFlight?.id == id { inFlight = nil }
        guard generation == requestGeneration else { return SnapshotStore().load() }
        if let result {
            SnapshotStore().save(result.state, at: result.savedAt)
        }
        return result
    }

    func invalidate() {
        generation += 1
        inFlight?.task.cancel()
        inFlight = nil
    }
}

public enum JARVISWidgetCommandDisposition: Equatable, Sendable {
    case execute
    case alreadyPending
    case recentlyCompleted
}

public struct JARVISPendingPlugCommand: Equatable, Sendable {
    public let isOn: Bool
    public let startedAt: Date
}

/// Target-local interaction state used to render immediate feedback and reject
/// duplicate taps while WidgetKit is executing the first desired-state intent.
public final class JARVISWidgetControlStore: @unchecked Sendable {
    public static let shared = JARVISWidgetControlStore()
    public static let pendingTimeout: TimeInterval = 30
    public static let duplicateWindow: TimeInterval = 10

    private struct Record: Codable {
        let isOn: Bool
        let at: Date
    }

    private let defaults: UserDefaults
    private let lock = NSLock()
    private let pendingKey = "jarvis.widget.pending-plug-commands.v1"
    private let completedKey = "jarvis.widget.completed-plug-commands.v1"

    public init(suiteName: String = JARVISSharedStore.appGroupIdentifier) {
        defaults = UserDefaults(suiteName: suiteName) ?? .standard
    }

    public func begin(name: String, isOn: Bool, now: Date = Date()) -> JARVISWidgetCommandDisposition {
        lock.lock()
        defer { lock.unlock() }

        var pending = records(forKey: pendingKey)
        var completed = records(forKey: completedKey)
        purge(&pending, olderThan: Self.pendingTimeout, now: now)
        purge(&completed, olderThan: Self.duplicateWindow, now: now)

        if pending[name] != nil {
            save(pending, forKey: pendingKey)
            save(completed, forKey: completedKey)
            return .alreadyPending
        }
        if let recent = completed[name], recent.isOn == isOn {
            save(pending, forKey: pendingKey)
            save(completed, forKey: completedKey)
            return .recentlyCompleted
        }

        pending[name] = Record(isOn: isOn, at: now)
        save(pending, forKey: pendingKey)
        save(completed, forKey: completedKey)
        return .execute
    }

    public func complete(name: String, isOn: Bool, succeeded: Bool, now: Date = Date()) {
        lock.lock()
        defer { lock.unlock() }

        var pending = records(forKey: pendingKey)
        var completed = records(forKey: completedKey)
        pending.removeValue(forKey: name)
        if succeeded { completed[name] = Record(isOn: isOn, at: now) }
        purge(&completed, olderThan: Self.duplicateWindow, now: now)
        save(pending, forKey: pendingKey)
        save(completed, forKey: completedKey)
    }

    public func pendingCommand(for name: String, now: Date = Date()) -> JARVISPendingPlugCommand? {
        lock.lock()
        defer { lock.unlock() }

        var pending = records(forKey: pendingKey)
        purge(&pending, olderThan: Self.pendingTimeout, now: now)
        save(pending, forKey: pendingKey)
        guard let record = pending[name] else { return nil }
        return JARVISPendingPlugCommand(isOn: record.isOn, startedAt: record.at)
    }

    public func clear() {
        lock.lock()
        defaults.removeObject(forKey: pendingKey)
        defaults.removeObject(forKey: completedKey)
        lock.unlock()
    }

    private func records(forKey key: String) -> [String: Record] {
        guard let data = defaults.data(forKey: key),
              let records = try? JSONDecoder().decode([String: Record].self, from: data) else { return [:] }
        return records
    }

    private func save(_ records: [String: Record], forKey key: String) {
        guard !records.isEmpty else {
            defaults.removeObject(forKey: key)
            return
        }
        if let data = try? JSONEncoder().encode(records) {
            defaults.set(data, forKey: key)
        }
    }

    private func purge(_ records: inout [String: Record], olderThan interval: TimeInterval, now: Date) {
        records = records.filter { now.timeIntervalSince($0.value.at) >= 0 && now.timeIntervalSince($0.value.at) < interval }
    }
}
