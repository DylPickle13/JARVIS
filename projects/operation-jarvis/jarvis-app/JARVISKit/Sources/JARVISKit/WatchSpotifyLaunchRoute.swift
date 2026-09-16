import Foundation

/// No caller-supplied destinations, playback commands, or companion routing.
public enum JARVISWatchSpotifyRoute {
    public static let widgetURL = URL(string: "jarvis://spotify")!
    /// Spotify's published AASA explicitly includes /home for its Watch extension.
    public static let destination = URL(string: "https://open.spotify.com/home")!

    public static func accepts(_ url: URL) -> Bool {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return false }
        return parts.scheme?.lowercased() == "jarvis" && parts.host?.lowercased() == "spotify" &&
            parts.user == nil && parts.password == nil && parts.port == nil &&
            parts.path.isEmpty && parts.query == nil && parts.fragment == nil
    }
}
