import Foundation

/// Non-wrapping Watch pager with the owner's dedicated health and plug pages.
/// Up advances; down returns. Terminal owns horizontal session gestures.
public enum WatchDashboardPage: Hashable, CaseIterable {
    case home
    case terminal
    case plugs
    case jarvis
    case jobs

    public func destination(
        verticalTranslation: Double,
        horizontalTranslation: Double
    ) -> Self? {
        guard verticalTranslation.isFinite, horizontalTranslation.isFinite,
              abs(verticalTranslation) >= 52,
              abs(verticalTranslation) > abs(horizontalTranslation),
              let index = Self.allCases.firstIndex(of: self) else { return nil }
        let next = index + (verticalTranslation < 0 ? 1 : -1)
        return Self.allCases.indices.contains(next) ? Self.allCases[next] : nil
    }
}
