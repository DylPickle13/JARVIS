import Foundation

/// Pure, side-effect-free routing for the future generic Watch APNs payload.
///
/// This type does not request notification authorization, register with APNs,
/// collect a device token, or schedule local notifications. It only validates
/// the opaque retained-result sequence after notification support is enabled.
public struct ScheduledJobNotificationRoute: Equatable, Sendable {
    public let resultSequence: Int

    public init?(payload: [String: JSONValue]) {
        let sequence: Int?
        switch payload["resultSequence"] {
        case let .string(raw):
            sequence = Int(raw)
        case let .number(raw) where raw.rounded(.towardZero) == raw:
            sequence = Int(exactly: raw)
        default:
            sequence = nil
        }
        guard let sequence, sequence > 0 else { return nil }
        self.resultSequence = sequence
    }
}
