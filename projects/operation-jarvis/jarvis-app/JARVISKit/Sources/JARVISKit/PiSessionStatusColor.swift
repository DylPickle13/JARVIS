#if canImport(SwiftUI)
import SwiftUI

public extension PiSessionLifecycle {
    /// Shared by Home cards and the phone/Watch terminal session indicators.
    var statusColor: Color {
        switch self {
        case .offline: return .gray
        case .idle: return .purple
        case .running: return .green
        case .new: return .cyan
        // Exact #FF7A00, shared with Pi Desk; New remains cyan.
        case .compacting: return Color(red: 1, green: 122.0 / 255, blue: 0)
        case .unknown: return Color(red: 0.96, green: 0.58, blue: 0.16)
        }
    }
}
#endif
