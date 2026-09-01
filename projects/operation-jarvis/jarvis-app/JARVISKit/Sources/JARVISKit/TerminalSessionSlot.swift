import Foundation

/// The six fixed mobile Pi conversations. The raw value is the only value
/// allowed to cross the app/terminald boundary; tmux target names remain a
/// host-side allowlist and are never accepted from a client.
public enum JARVISTerminalSlot: Int, CaseIterable, Codable, Equatable, Hashable, Sendable {
    case one = 1
    case two = 2
    case three = 3
    case four = 4
    case five = 5
    case six = 6

    public static let defaultSlot: JARVISTerminalSlot = .one
    public static let defaultsKey = "jarvis.terminal.active-slot"

    public var displayName: String { String(rawValue) }

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
