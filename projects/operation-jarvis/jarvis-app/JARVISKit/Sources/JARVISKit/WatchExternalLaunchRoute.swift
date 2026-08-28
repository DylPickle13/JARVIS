import Foundation

/// Closed, argument-free routes used only by the temporary physical link probe.
/// Query items, paths, and caller-supplied destinations are never forwarded.
public enum JARVISWatchExternalLaunchRoute {
    private static let shortcutsURL = URL(string: "shortcuts://")!
    private static let spotifyURL = URL(string: "https://open.spotify.com/")!

    public static func destination(for incomingURL: URL) -> URL? {
        guard incomingURL.scheme?.lowercased() == "jarvis",
              incomingURL.path.isEmpty,
              incomingURL.query == nil,
              incomingURL.fragment == nil else {
            return nil
        }

        switch incomingURL.host?.lowercased() {
        case "launch-shortcuts":
            return shortcutsURL
        case "launch-spotify":
            return spotifyURL
        default:
            return nil
        }
    }
}
