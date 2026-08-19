import SwiftUI
import JARVISKit

// Shared UI building blocks for the iOS app (M1+): the connection badge, an
// inset-grouped card container, and small formatting helpers. Kept separate so
// Home / Events / System / Settings can all reuse them.

// MARK: - Connection badge

/// Small capsule status indicator (dot + detail text).
struct ConnectionBadge: View {
    let state: ConnectionState
    let detail: String

    private var color: Color {
        switch state {
        case .connected: return .green
        case .failed: return .red
        case .connecting: return .orange
        case .idle: return .secondary
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 9, height: 9)
            Text(detail)
                .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Connection \(detail)")
    }
}

// MARK: - Card container

/// An inset-grouped card (secondary grouped background, 12pt continuous
/// corners) matching the HIG grouped-list card style.
struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                Color(.secondarySystemGroupedBackground),
                in: RoundedRectangle(cornerRadius: 12, style: .continuous)
            )
    }
}

// MARK: - Formatting helpers

enum JarvisFormat {
    static func uptime(_ seconds: Double) -> String {
        let s = Int(seconds)
        let h = s / 3600
        let m = (s % 3600) / 60
        let sec = s % 60
        if h > 0 { return "\(h)h \(m)m" }
        if m > 0 { return "\(m)m \(sec)s" }
        return "\(sec)s"
    }

    /// "family-room-light" -> "Family Room Light"
    static func displayName(_ raw: String) -> String {
        raw
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }

    /// Map an Open-Meteo WMO weather code to an SF Symbol name.
    static func weatherSymbol(_ code: Int?) -> String {
        switch code {
        case nil: return "cloud"
        case 0: return "sun.max.fill"
        case 1, 2: return "cloud.sun.fill"
        case 3: return "cloud.fill"
        case 45, 48: return "cloud.fog.fill"
        case 51, 53, 55, 56, 57: return "cloud.drizzle.fill"
        case 61, 63, 65, 66, 67: return "cloud.rain.fill"
        case 71, 73, 75, 77: return "cloud.snow.fill"
        case 80, 81, 82: return "cloud.heavyrain.fill"
        case 85, 86: return "cloud.snow.fill"
        case 95: return "cloud.bolt.fill"
        case 96, 99: return "cloud.bolt.rain.fill"
        default: return "cloud"
        }
    }

    /// Tint colour for a weather symbol.
    static func weatherTint(_ code: Int?) -> Color {
        guard let code else { return .gray }
        switch code {
        case 0, 1, 2: return .yellow
        case 3, 45, 48: return .gray
        case 51...67, 80...82: return .blue
        case 71...77, 85, 86: return .cyan
        case 95, 96, 99: return .orange
        default: return .gray
        }
    }

    // MARK: - Time

    /// Compact relative time for event rows: "now", "42s", "7m", "3h", "2d".
    static func relativeTime(_ iso: String?) -> String {
        guard let iso, let date = parseISO8601(iso) else { return "" }
        let secs = Int(Date().timeIntervalSince(date))
        if secs < 5 { return "now" }
        if secs < 60 { return "\(secs)s" }
        if secs < 3600 { return "\(secs / 60)m" }
        if secs < 86400 { return "\(secs / 3600)h" }
        return "\(secs / 86400)d"
    }

    /// Parse an ISO-8601 timestamp (with or without fractional seconds).
    static func parseISO8601(_ s: String) -> Date? {
        let withFrac = ISO8601DateFormatter()
        withFrac.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFrac.date(from: s) { return d }
        let plain = ISO8601DateFormatter()
        return plain.date(from: s)
    }
}
