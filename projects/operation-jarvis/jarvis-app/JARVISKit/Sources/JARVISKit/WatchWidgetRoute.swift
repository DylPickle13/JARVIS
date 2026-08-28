import Foundation

public enum JARVISWatchWidgetDestination: String, Equatable, Hashable, Identifiable, Sendable {
    case quickActions
    case nowPlaying

    public var id: String { rawValue }
}

/// Closed routes for the two side controls in the composite Watch widget.
/// Paths, queries, fragments, and caller-selected destinations are rejected.
public enum JARVISWatchWidgetRoute {
    public static let quickActionsURL = URL(string: "jarvis://quick-actions")!
    public static let nowPlayingURL = URL(string: "jarvis://now-playing")!

    public static func destination(for incomingURL: URL) -> JARVISWatchWidgetDestination? {
        guard incomingURL.scheme?.lowercased() == "jarvis",
              incomingURL.path.isEmpty,
              incomingURL.query == nil,
              incomingURL.fragment == nil else {
            return nil
        }

        switch incomingURL.host?.lowercased() {
        case "quick-actions":
            return .quickActions
        case "now-playing":
            return .nowPlaying
        default:
            return nil
        }
    }
}
