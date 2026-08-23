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
        case .connected: return JarvisPalette.cyan
        case .failed: return .red
        case .connecting: return JarvisPalette.warning
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
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                JarvisPalette.surface,
                in: RoundedRectangle(cornerRadius: 18, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Color.primary.opacity(0.065), lineWidth: 0.75)
            }
            .shadow(color: Color.black.opacity(0.055), radius: 12, y: 5)
    }
}

// MARK: - JARVIS visual system

enum JarvisPalette {
    static let cyan = Color(red: 0.20, green: 0.72, blue: 0.96)
    static let electricBlue = Color(red: 0.28, green: 0.49, blue: 1.0)
    static let critical = Color(red: 1.0, green: 0.22, blue: 0.28)
    static let warning = Color(red: 0.96, green: 0.58, blue: 0.16)
    static let surface = Color(.secondarySystemGroupedBackground).opacity(0.94)

    static var backdrop: LinearGradient {
        LinearGradient(
            colors: [
                Color(.systemGroupedBackground),
                cyan.opacity(0.055),
                Color(.systemGroupedBackground),
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

struct JarvisBackdrop: View {
    var body: some View {
        JarvisPalette.backdrop
            .ignoresSafeArea()
    }
}

struct JARVISMark: View {
    let size: CGFloat

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    RadialGradient(
                        colors: [JarvisPalette.cyan.opacity(0.34), JarvisPalette.cyan.opacity(0.04)],
                        center: .center,
                        startRadius: 2,
                        endRadius: size / 2
                    )
                )
                .blur(radius: 3)
            Image("JARVISMark")
                .resizable()
                .scaledToFit()
                .padding(4)
                .clipShape(Circle())
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

struct StatusPill: View {
    let text: String
    let color: Color
    var symbol: String? = nil

    var body: some View {
        HStack(spacing: 5) {
            if let symbol {
                Image(systemName: symbol)
                    .font(.caption2.weight(.bold))
            } else {
                Circle().fill(color).frame(width: 7, height: 7)
            }
            Text(text)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(color.opacity(0.11), in: Capsule())
        .overlay { Capsule().stroke(color.opacity(0.22), lineWidth: 0.75) }
        .accessibilityElement(children: .combine)
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

    static func plugSymbol(_ name: String) -> String {
        switch name {
        case "family-room-light": return "lightbulb.fill"
        case "lamp": return "lamp.table.fill"
        case "pedalboard": return "music.note"
        case "tv": return "tv.fill"
        default: return "powerplug.fill"
        }
    }

    static func freshness(ageSeconds: Double?) -> String {
        guard let ageSeconds else { return "Waiting for status" }
        let seconds = max(0, Int(ageSeconds))
        if seconds < 5 { return "Updated now" }
        if seconds < 60 { return "Updated \(seconds)s ago" }
        if seconds < 3_600 { return "Updated \(seconds / 60)m ago" }
        return "Updated \(seconds / 3_600)h ago"
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

    static func localDateTime(_ iso: String?) -> String? {
        guard let iso, let date = parseISO8601(iso) else { return nil }
        return date.formatted(
            .dateTime
                .weekday(.abbreviated)
                .month(.abbreviated)
                .day()
                .hour()
                .minute()
        )
    }

    static func scheduleDescription(kind: String, schedule: String) -> String {
        if kind == "interval", schedule.count >= 2,
           let amount = Int(schedule.dropLast()), let unit = schedule.last {
            let word: String
            switch unit {
            case "s": word = amount == 1 ? "second" : "seconds"
            case "m": word = amount == 1 ? "minute" : "minutes"
            case "h": word = amount == 1 ? "hour" : "hours"
            case "d": word = amount == 1 ? "day" : "days"
            default: return "Interval · \(schedule)"
            }
            return "Every \(amount) \(word) · \(schedule)"
        }
        if kind == "once" { return "Once · \(schedule)" }
        if kind == "cron" { return "Cron · \(schedule)" }
        return "\(displayName(kind)) · \(schedule)"
    }

    /// Parse an ISO-8601 timestamp (with or without fractional seconds).
    static func parseISO8601(_ s: String) -> Date? {
        if let date = isoWithFractionalSeconds.date(from: s) { return date }
        return isoPlain.date(from: s)
    }
}
