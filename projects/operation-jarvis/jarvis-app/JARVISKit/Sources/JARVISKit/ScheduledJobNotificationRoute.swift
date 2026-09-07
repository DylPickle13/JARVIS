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
