import Foundation

/// Nine ordinary mobile conversations plus the reserved Room Audio conversation. The raw value is the only value
/// allowed to cross the app/terminald boundary; tmux target names remain a
/// host-side allowlist and are never accepted from a client.
public enum JARVISTerminalSlot: Int, CaseIterable, Codable, Equatable, Hashable, Sendable {
    case one = 1
    case two = 2
    case three = 3
    case four = 4
    case five = 5
    case six = 6
    case seven = 7
    case eight = 8
    case nine = 9
    case roomAudio = 10

    public static let defaultSlot: JARVISTerminalSlot = .one
    public static let defaultsKey = "jarvis.terminal.active-slot"

    public var displayName: String { String(rawValue) }

    /// Shared phone/Watch indicator grouping: 1–3, 4–6, 7–9, Room Audio (10).
    public var hasLeadingIndicatorGap: Bool {
        self == .four || self == .seven || self == .roomAudio
    }

    /// Resolve by session ID, not array position; stale or missing status is unknown.
    public func lifecycle(in pi: PiSubsystem?) -> PiSessionLifecycle {
        guard let pi, pi.stale != true else { return .unknown }
        return pi.mobileSessions?.first(where: { $0.sessionID == rawValue })?.resolvedLifecycle ?? .unknown
    }

    public var previous: JARVISTerminalSlot? {
        JARVISTerminalSlot(rawValue: rawValue - 1)
    }

    public var next: JARVISTerminalSlot? {
        JARVISTerminalSlot(rawValue: rawValue + 1)
    }

    public static func load(from defaults: UserDefaults = .standard) -> JARVISTerminalSlot {
        JARVISTerminalSlot(rawValue: defaults.integer(forKey: defaultsKey)) ?? defaultSlot
    }

    public func persist(to defaults: UserDefaults = .standard) {
        defaults.set(rawValue, forKey: Self.defaultsKey)
    }
}
