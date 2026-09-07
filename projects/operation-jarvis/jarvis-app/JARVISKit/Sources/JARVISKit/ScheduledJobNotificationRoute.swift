import CoreFoundation
import Foundation

/// Pure, side-effect-free validation for fixed JARVIS Jobs APNs routing metadata.
public struct ScheduledJobNavigationRequest: Equatable, Identifiable, Sendable {
    public let id: UUID
    public let resultSequence: Int

    public init?(id: UUID = UUID(), resultSequence: Int) {
        guard resultSequence > 0 else { return nil }
        self.id = id
        self.resultSequence = resultSequence
    }
}

public struct ScheduledJobNotificationRoute: Equatable, Sendable {
    public static let name = "scheduled-job-result"
    public static let version = 1

    public let resultSequence: Int

    public init?(route: String?, version: Any?, resultSequence: Any?) {
        guard route == Self.name,
              Self.integer(from: version) == Self.version,
              let sequence = Self.integer(from: resultSequence),
              sequence > 0 else { return nil }
        self.resultSequence = sequence
    }

    public init?(payload: [String: JSONValue]) {
        guard case let .string(route)? = payload["route"] else { return nil }
        let version: Any?
        switch payload["routeVersion"] {
        case let .number(raw): version = NSNumber(value: raw)
        case let .string(raw): version = raw
        default: version = nil
        }
        let sequence: Any?
        switch payload["resultSequence"] {
        case let .string(raw): sequence = raw
        case let .number(raw): sequence = NSNumber(value: raw)
        default: sequence = nil
        }
        self.init(route: route, version: version, resultSequence: sequence)
    }

    private static func integer(from value: Any?) -> Int? {
        switch value {
        case let raw as String:
            return Int(raw)
        case let raw as NSNumber where CFGetTypeID(raw) != CFBooleanGetTypeID():
            // NSNumber.stringValue preserves integral 64-bit payloads without
            // routing them through Double (and rejects fractional spellings).
            return Int(raw.stringValue)
        default:
            return nil
        }
    }
}

/// Content-free completion alerts are informational, not Jobs-result routes.
public struct PiSessionCompletionNotificationRoute: Equatable, Sendable {
    public let sessionID: Int

    public init?(route: String?, version: Any?, sessionID: Any?) {
        guard route == "pi-session-completed",
              let validated = ScheduledJobNotificationRoute(
                route: ScheduledJobNotificationRoute.name, version: version,
                resultSequence: sessionID),
              (1...9).contains(validated.resultSequence) else { return nil }
        self.sessionID = validated.resultSequence
    }
}

/// A bounded, process-local tap inbox: no foreground navigation or persisted payload.
public struct PiTerminalNotificationRequest: Hashable, Sendable {
    public let notificationID: String
    public let sessionID: Int
    public init(notificationID: String, sessionID: Int) {
        self.notificationID = notificationID
        self.sessionID = sessionID
    }
}
public struct PiTerminalNotificationInbox: Sendable {
    private var seen: [String] = []
    public init() {}
    public mutating func receive(notificationID: String, sessionID: Int) -> PiTerminalNotificationRequest? {
        guard (1...9).contains(sessionID), !notificationID.isEmpty,
              !seen.contains(notificationID) else { return nil }
        seen.append(notificationID)
        if seen.count > 64 { seen.removeFirst(seen.count - 64) }
        return PiTerminalNotificationRequest(notificationID: notificationID, sessionID: sessionID)
    }
}
