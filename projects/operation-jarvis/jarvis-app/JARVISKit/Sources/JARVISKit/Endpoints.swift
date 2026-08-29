import Foundation

/// One fail-closed parser for every jarvisd control-plane endpoint entering the
/// app. jarvisd is intentionally available over HTTP on the private LAN and
/// Tailscale networks, so both HTTP and HTTPS remain supported. An endpoint is
/// always the server root; API paths and queries are added only by JarvisClient.
public enum JarvisEndpointURLPolicy {
    private static let allowedSchemes: Set<String> = ["http", "https"]
    private static let recognizedNonHostSchemes: Set<String> = [
        "data", "file", "ftp", "mailto", "ssh", "ws", "wss",
    ]
    private static let forbiddenHostCharacters = CharacterSet.whitespacesAndNewlines
        .union(.controlCharacters)

    public static func parse(_ rawValue: String) -> URL? {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }

        let lowercased = value.lowercased()
        let candidate: String
        if lowercased.hasPrefix("http://") || lowercased.hasPrefix("https://") {
            candidate = value
        } else if hasExplicitNonHTTPURLScheme(value) {
            return nil
        } else {
            candidate = "http://" + value
        }

        guard hasValidAuthorityPortSyntax(candidate),
              var components = URLComponents(string: candidate),
              let rawScheme = components.scheme,
              allowedSchemes.contains(rawScheme.lowercased()),
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil,
              components.percentEncodedPath.isEmpty || components.percentEncodedPath == "/",
              let rawHost = components.host,
              !rawHost.isEmpty,
              rawHost.rangeOfCharacter(from: forbiddenHostCharacters) == nil else {
            return nil
        }
        if let port = components.port, !(1...65_535).contains(port) {
            return nil
        }

        components.scheme = rawScheme.lowercased()
        components.host = rawHost.lowercased()
        components.percentEncodedPath = ""
        guard let normalized = components.url,
              let scheme = normalized.scheme,
              allowedSchemes.contains(scheme),
              normalized.host?.isEmpty == false else {
            return nil
        }
        return normalized
    }

    public static func normalize(_ url: URL) -> URL? {
        parse(url.absoluteString)
    }

    private static func hasValidAuthorityPortSyntax(_ value: String) -> Bool {
        guard let schemeEnd = value.range(of: "://")?.upperBound else { return false }
        let remainder = value[schemeEnd...]
        let authority = remainder.prefix { !"/?#".contains($0) }
        guard !authority.isEmpty else { return false }
        let hostAndPort = authority.split(separator: "@", omittingEmptySubsequences: false).last ?? authority

        if hostAndPort.hasPrefix("[") {
            guard let bracket = hostAndPort.firstIndex(of: "]") else { return false }
            let suffix = hostAndPort[hostAndPort.index(after: bracket)...]
            guard !suffix.isEmpty else { return true }
            guard suffix.first == ":" else { return false }
            let port = suffix.dropFirst()
            return !port.isEmpty && port.allSatisfy(\.isNumber)
        }

        guard let colon = hostAndPort.lastIndex(of: ":") else { return true }
        let port = hostAndPort[hostAndPort.index(after: colon)...]
        return !port.isEmpty && port.allSatisfy(\.isNumber)
    }

    /// Preserve ordinary host:port shorthand (for example `localhost:8790`)
    /// while refusing explicit unsupported URL schemes before adding HTTP.
    private static func hasExplicitNonHTTPURLScheme(_ value: String) -> Bool {
        guard let colon = value.firstIndex(of: ":") else { return false }
        let prefix = value[..<colon]
        guard let first = prefix.unicodeScalars.first,
              CharacterSet.letters.contains(first),
              prefix.unicodeScalars.dropFirst().allSatisfy({
                  CharacterSet.alphanumerics.contains($0) || "+-.".unicodeScalars.contains($0)
              }) else {
            return false
        }

        let suffix = value[value.index(after: colon)...]
        if allowedSchemes.contains(prefix.lowercased()) ||
            recognizedNonHostSchemes.contains(prefix.lowercased()) {
            return true
        }
        if suffix.hasPrefix("//") { return true }
        let possiblePort = suffix.prefix { $0.isNumber }
        return possiblePort.isEmpty || possiblePort.endIndex != suffix.endIndex && suffix[possiblePort.endIndex] != "/"
    }
}

// Default jarvisd candidate endpoints, in priority order. The app probes all
// of these in parallel and uses the first (by priority) that answers /health:
//   1. Home LAN IP       — used when on the home network (verified reachable).
//   2. Tailscale MagicDNS — stable across a Tailscale node address rotation.
//   3. Tailscale IP       — direct fallback if MagicDNS is temporarily absent.
//
// These are environment-specific; override via the in-app endpoint field or by
// editing this list. MagicDNS is preferred off-LAN so reinstalling Tailscale on
// the Mac does not strand an app build on the previous node address.
public enum JarvisEndpoints {
    public static let defaults: [String] = [
        "http://192.168.21.215:8790",                       // home LAN
        "http://dylans-mac-mini-2.tailcba1e5.ts.net:8790", // Tailscale MagicDNS
        "http://100.87.28.34:8790",                         // Tailscale IP fallback
    ]

    /// Candidate URLs, normalized, deduped, and kept in priority order.
    /// `override` is tried first only when it satisfies the shared policy.
    public static func candidates(override: URL?) -> [URL] {
        var seen = Set<URL>()
        var out: [URL] = []
        func add(_ candidate: URL?) {
            guard let candidate,
                  let normalized = JarvisEndpointURLPolicy.normalize(candidate),
                  seen.insert(normalized).inserted else { return }
            out.append(normalized)
        }
        add(override)
        for value in defaults {
            add(JarvisEndpointURLPolicy.parse(value))
        }
        return out
    }
}
