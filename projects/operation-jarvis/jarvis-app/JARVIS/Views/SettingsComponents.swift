import SwiftUI

struct SettingsGroup<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title.uppercased())
                .font(.caption2.weight(.semibold))
                .tracking(0.7)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 3)
            MinimalCard {
                VStack(spacing: 0) { content() }
            }
        }
    }
}

struct SettingsNavigationRow: View {
    let title: String
    let systemImage: String
    let value: String
    let color: Color

    var body: some View {
        HStack(spacing: 11) {
            Image(systemName: systemImage)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(JarvisPalette.cyan)
                .frame(width: 24)
            Text(title)
                .font(.body)
                .foregroundStyle(.primary)
            Spacer(minLength: 8)
            Text(value)
                .font(.caption.weight(.medium))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            Image(systemName: "chevron.right")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

struct SettingsStatusHeader: View {
    let title: String
    let detail: String
    let systemImage: String
    let color: Color

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle().fill(color.opacity(0.14))
                Image(systemName: systemImage)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(color)
            }
            .frame(width: 42, height: 42)

            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(color)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
    }
}

@MainActor
enum SettingsPresentation {
    static func daemonSummary(_ app: AppState) -> String {
        switch app.connectionState {
        case .connected: return "Connected · \(networkLabel(app))"
        case .connecting: return "Connecting"
        case .failed: return "Offline"
        case .idle: return "Not connected"
        }
    }

    static func daemonColor(_ app: AppState) -> Color {
        switch app.connectionState {
        case .connected: return JarvisPalette.cyan
        case .connecting: return JarvisPalette.warning
        case .failed: return .red
        case .idle: return .secondary
        }
    }

    static func networkLabel(_ app: AppState) -> String {
        guard let host = app.currentEndpoint?.host else { return "—" }
        if host.hasPrefix("100.") || host.hasSuffix(".ts.net") { return "Tailscale" }
        if host.hasPrefix("192.168") || host.hasPrefix("10.") || host.hasPrefix("172.") { return "LAN" }
        return host
    }

    static func usingString(_ app: AppState) -> String? {
        guard let endpoint = app.currentEndpoint, let host = endpoint.host else { return nil }
        let port = endpoint.port.map(String.init) ?? "8790"
        return host + ":" + port
    }

    static var appVersion: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(version) (\(build))"
    }

    static func signingCountdown(to expiration: Date, at date: Date) -> String {
        let seconds = Int(expiration.timeIntervalSince(date))
        guard seconds > 0 else { return "Expired" }
        let days = seconds / 86_400
        let hours = (seconds % 86_400) / 3_600
        if days > 0 { return "\(days)d \(hours)h remaining" }
        let minutes = max(1, (seconds % 3_600) / 60)
        return "\(hours)h \(minutes)m remaining"
    }

    static func signingColor(expiration: Date?, at date: Date) -> Color {
        guard let expiration else { return JarvisPalette.warning }
        let remaining = expiration.timeIntervalSince(date)
        if remaining <= 0 { return .red }
        if remaining <= 2 * 86_400 { return JarvisPalette.warning }
        return JarvisPalette.cyan
    }
}

extension View {
    func compactSettingsForm(title: String) -> some View {
        scrollContentBackground(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
    }
}
