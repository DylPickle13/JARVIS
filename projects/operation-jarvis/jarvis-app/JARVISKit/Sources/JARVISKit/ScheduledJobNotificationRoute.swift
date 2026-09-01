import CoreFoundation
import Foundation

/// Pure, side-effect-free routing for the generic JARVIS Jobs APNs payload.
public struct ScheduledJobNotificationRoute: Equatable, Sendable {
    public static let name = "scheduled-job-result"
    public static let version = 1

    public let resultSequence: Int

    public init?(route: String?, version: Int?, resultSequence: Any?) {
        guard route == Self.name, version == Self.version else { return nil }
        let sequence: Int?
        switch resultSequence {
        case let raw as String:
            sequence = Int(raw)
        case let raw as Int:
            sequence = raw
        case let raw as NSNumber where CFGetTypeID(raw) != CFBooleanGetTypeID():
            let double = raw.doubleValue
            sequence = double.rounded(.towardZero) == double ? Int(exactly: double) : nil
        default:
            sequence = nil
        }
        guard let sequence, sequence > 0 else { return nil }
        self.resultSequence = sequence
    }

    public init?(payload: [String: JSONValue]) {
        guard case let .string(route)? = payload["route"] else { return nil }
        let version: Int?
        switch payload["routeVersion"] {
        case let .number(raw) where raw.rounded(.towardZero) == raw:
            version = Int(exactly: raw)
        case let .string(raw):
            version = Int(raw)
        default:
            version = nil
        }
        let sequence: Any?
        switch payload["resultSequence"] {
        case let .string(raw): sequence = raw
        case let .number(raw): sequence = NSNumber(value: raw)
        default: sequence = nil
        }
        self.init(route: route, version: version, resultSequence: sequence)
    }
}
