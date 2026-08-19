import Foundation

// Default jarvisd candidate endpoints, in priority order. The app probes all
// of these in parallel and uses the first (by priority) that answers /health:
//   1. Home LAN IP  — used when on the home network (verified reachable).
//   2. Tailscale IP — used when away (and at home once Tailscale is healthy).
//
// These are environment-specific; override via the in-app endpoint field or by
// editing this list. A future refinement is mDNS/Bonjour discovery
// (e.g. http://jarvis.local:8790) so the LAN IP needn't be hardcoded.
public enum JarvisEndpoints {
    public static let defaults: [String] = [
        "http://192.168.21.215:8790", // home LAN
        "http://100.96.55.86:8790",   // Tailscale (home + away)
    ]

    /// Candidate URLs, deduped, in priority order. `override` (if a valid URL)
    /// is tried first so a manually-entered endpoint wins over the defaults.
    public static func candidates(override: URL?) -> [URL] {
        var seen = Set<URL>()
        var out: [URL] = []
        func add(_ u: URL?) {
            guard let u, seen.insert(u).inserted else { return }
            out.append(u)
        }
        add(override)
        for s in defaults {
            add(URL(string: s))
        }
        return out
    }
}
