import Foundation

public enum HomeAutomationControl: String, Codable, CaseIterable, Sendable {
    case automaticVoice = "automatic-voice"
    case barnDoor = "barn-door"

    public var title: String { self == .automaticVoice ? "Voice" : "Barn Door Protocol" }
    public var symbol: String { self == .automaticVoice ? "speaker.wave.2.fill" : "door.left.hand.closed" }

    /// Visual shorthand only; button accessibility retains the full state/warning.
    public static func compactStatus(_ label: String, warning: Bool = false) -> String {
        if warning { return "!" }
        switch label {
        case "On": return "ON"
        case "Off": return "OFF"
        case "Unavailable": return "—"
        case "Changing…", "Refreshing…": return "…"
        default: return "?"
        }
    }
}

public struct HomeAutomationCommand: Codable, Equatable, Sendable {
    public let control: HomeAutomationControl
    public let enabled: Bool
    public let revision: String
    public let confirmed: Bool
    public let requestID: String

    public init(control: HomeAutomationControl, enabled: Bool, revision: String, confirmed: Bool = false,
                requestID: String = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()) {
        self.control = control; self.enabled = enabled; self.revision = revision
        self.confirmed = confirmed; self.requestID = requestID
    }

    public var isValid: Bool {
        Self.hex(requestID, count: 32) && Self.hex(revision, count: control == .automaticVoice ? 32 : 64)
            && (control != .barnDoor || !enabled || confirmed)
    }

    private static func hex(_ value: String, count: Int) -> Bool {
        value.count == count && value.allSatisfy { "0123456789abcdef".contains($0) }
    }
}

public struct HomeAutomationReceipt: Codable, Equatable, Sendable {
    public let requestID: String
    public let control: HomeAutomationControl
    public let enabled: Bool
    public let status: String

    public func matches(_ command: HomeAutomationCommand) -> Bool {
        requestID == command.requestID && control == command.control && enabled == command.enabled
            && ["pending", "verified", "unknown", "rejected"].contains(status)
    }
}

public struct HomeAutomationState: Codable, Equatable, Sendable {
    public let available: Bool?
    public let enabled: Bool?
    public let revision: String?
    public let observedAt: String?
    public let validUntil: String?
    public let refreshing: Bool?
    public let blocked: Bool?
    public let error: String?
    public let operation: HomeAutomationReceipt?

    public init(available: Bool? = nil, enabled: Bool? = nil, revision: String? = nil,
                observedAt: String? = nil, validUntil: String? = nil, refreshing: Bool? = nil,
                blocked: Bool? = nil, error: String? = nil, operation: HomeAutomationReceipt? = nil) {
        self.available = available; self.enabled = enabled; self.revision = revision
        self.observedAt = observedAt; self.validUntil = validUntil; self.refreshing = refreshing
        self.blocked = blocked; self.error = error; self.operation = operation
    }

    public func isFresh(now: Date = Date()) -> Bool {
        guard available == true, enabled != nil, revision != nil,
              let observed = Self.date(observedAt), let expires = Self.date(validUntil) else { return false }
        return observed.timeIntervalSince(now) <= 5 && expires > now && expires > observed
            && expires.timeIntervalSince(observed) <= 90
    }

    public func canChange(_ control: HomeAutomationControl, connected: Bool, now: Date = Date()) -> Bool {
        guard connected, isFresh(now: now), refreshing != true, blocked != true, error == nil,
              operation?.status != "pending", let revision else { return false }
        return HomeAutomationCommand(control: control, enabled: false, revision: revision).isValid
    }

    public func label(connected: Bool, now: Date = Date()) -> String {
        if operation?.status == "pending" { return connected ? "Changing…" : "Unconfirmed" }
        guard connected, isFresh(now: now) else { return refreshing == true && connected ? "Refreshing…" : "Unavailable" }
        return enabled == true ? "On" : "Off"
    }

    public var outcomeWarning: String? {
        if operation?.status == "unknown" { return "Outcome unknown. Refresh configuration; do not resend automatically." }
        if operation?.status == "rejected" { return "Change rejected. Refresh before acting." }
        return error
    }

    private static func date(_ value: String?) -> Date? {
        guard let value else { return nil }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return parser.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }
}

public struct HomeAutomationsSnapshot: Codable, Equatable, Sendable {
    public let automaticVoice: HomeAutomationState?
    public let barnDoor: HomeAutomationState?

    public init(automaticVoice: HomeAutomationState? = nil, barnDoor: HomeAutomationState? = nil) {
        self.automaticVoice = automaticVoice; self.barnDoor = barnDoor
    }

    private enum CodingKeys: String, CodingKey { case automaticVoice, barnDoor }
    public init(from decoder: Decoder) throws {
        guard let values = try? decoder.container(keyedBy: CodingKeys.self) else {
            automaticVoice = nil; barnDoor = nil
            return
        }
        automaticVoice = try? values.decode(HomeAutomationState.self, forKey: .automaticVoice)
        barnDoor = try? values.decode(HomeAutomationState.self, forKey: .barnDoor)
    }

    public subscript(_ control: HomeAutomationControl) -> HomeAutomationState? {
        control == .automaticVoice ? automaticVoice : barnDoor
    }
}
