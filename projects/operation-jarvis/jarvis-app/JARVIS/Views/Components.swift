import SwiftUI
import JARVISKit

// Shared UI building blocks for the iOS app (M1+): the connection badge, an
// inset-grouped card container, and small formatting helpers. Kept separate so
// Home / Events / Settings can all reuse them.

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
        HStack(alignment: .top, spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 9, height: 9)
                .padding(.top, 6)
            Text(detail)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Connection \(detail)")
    }
}

// MARK: - Operation errors

struct OperationErrorCard: View {
    let message: String

    var body: some View {
        Label {
            Text(message)
                .font(.callout)
                .foregroundStyle(.red)
                .fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
        }
        .padding(.horizontal, 4)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Operation failed: \(message)")
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
    private static let isoWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    private static let isoPlain = ISO8601DateFormatter()

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

    // MARK: - Time

    /// Compact relative time for event rows: "now", "42s", "7m", "3h", "2d".
    static func relativeTime(_ iso: String?) -> String {
        guard let iso, let date = parseISO8601(iso) else { return "" }
        let secs = max(0, Int(Date().timeIntervalSince(date)))
        if secs < 5 { return "now" }
        if secs < 60 { return "\(secs)s" }
        if secs < 3600 { return "\(secs / 60)m" }
        if secs < 86400 { return "\(secs / 3600)h" }
        return "\(secs / 86400)d"
    }

    /// Parse an ISO-8601 timestamp (with or without fractional seconds).
    static func parseISO8601(_ s: String) -> Date? {
        if let date = isoWithFractionalSeconds.date(from: s) { return date }
        return isoPlain.date(from: s)
    }
}
