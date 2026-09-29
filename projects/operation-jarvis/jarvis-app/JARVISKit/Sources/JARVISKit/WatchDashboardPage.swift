import Foundation

/// Non-wrapping Watch pager, ordered top to bottom. Up advances; down returns.
/// Terminal applies this policy locally so horizontal session gestures remain its own.
public enum WatchDashboardPage: Hashable, CaseIterable {
    case system
    case terminal
    case plugs
    case overview
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
        case .system: return upward ? .terminal : nil
        case .terminal: return upward ? .plugs : .system
        case .plugs: return upward ? .overview : .terminal
        case .overview: return upward ? .jobs : .plugs
        case .jobs: return upward ? nil : .overview
        }
    }
}
