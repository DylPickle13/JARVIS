import Foundation

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
