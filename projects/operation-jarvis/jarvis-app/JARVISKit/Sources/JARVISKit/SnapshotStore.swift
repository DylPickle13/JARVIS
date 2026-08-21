import Foundation

/// Best-effort telemetry cache. Paid profiles may provide an App Group
/// container; Personal Team builds fall back to each target's local defaults.
/// Credentials remain in Keychain and are never stored here.
public enum JARVISSharedStore {
    public static let appGroupIdentifier = "group.com.operation-jarvis.jarvis"

    public static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroupIdentifier) ?? .standard
    }
}

public struct CachedState: Codable, Equatable, Sendable {
    public let state: StateSnapshot
    public let savedAt: Date

    public init(state: StateSnapshot, savedAt: Date = Date()) {
        self.state = state
        self.savedAt = savedAt
    }
}

public final class SnapshotStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key = "jarvis.cached.state.v1"
    private let lock = NSLock()

    public init(suiteName: String = JARVISSharedStore.appGroupIdentifier) {
        self.defaults = UserDefaults(suiteName: suiteName) ?? .standard
    }

    public func save(_ state: StateSnapshot, at date: Date = Date()) {
        guard let data = try? JSONEncoder().encode(CachedState(state: state, savedAt: date)) else { return }
        lock.lock()
        defaults.set(data, forKey: key)
        lock.unlock()
    }

    public func load() -> CachedState? {
        lock.lock()
        let data = defaults.data(forKey: key)
        lock.unlock()
        guard let data else { return nil }
        return try? JSONDecoder().decode(CachedState.self, from: data)
    }

    @discardableResult
    public func applyConfirmedPlugState(name: String, isOn: Bool, at date: Date = Date()) -> CachedState? {
        guard let cached = load() else { return nil }
        let updated = cached.state.applyingConfirmedPlugState(name: name, isOn: isOn, at: date)
        save(updated, at: date)
        return CachedState(state: updated, savedAt: date)
    }

    public func clear() {
        lock.lock()
        defaults.removeObject(forKey: key)
        lock.unlock()
    }
}
