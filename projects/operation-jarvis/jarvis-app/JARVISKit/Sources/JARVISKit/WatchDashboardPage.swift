import Foundation

/// Direction policy for the Watch's non-wrapping custom pager.
/// Up advances; down returns. Terminal owns its editor gestures.
public enum WatchDashboardPage: Hashable, CaseIterable {
    case terminal
    case plugs
    case system
    case jobs

    public func destination(
        verticalTranslation: Double,
        horizontalTranslation: Double
    ) -> Self? {
        guard verticalTranslation.isFinite, horizontalTranslation.isFinite,
              abs(verticalTranslation) >= 52,
              abs(verticalTranslation) > abs(horizontalTranslation) else { return nil }
        let upward = verticalTranslation < 0
        switch self {
        case .terminal: return nil // Terminal owns its editor gestures.
        case .plugs: return upward ? .system : .terminal
        case .system: return upward ? .jobs : .plugs
        case .jobs: return upward ? nil : .system
        }
    }
}
