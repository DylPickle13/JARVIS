import SwiftUI
import JARVISKit

/// Balanced summaries on the overview; text entry belongs to the pushed editors.
struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var piTerminal: PiTerminalController
    @EnvironmentObject private var notifications: PushNotificationCoordinator

    static func columnCount(for size: DynamicTypeSize) -> Int {
        size.isAccessibilitySize ? 1 : 2
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                SettingsDashboard()
                    .padding(.horizontal, 16)
                    .padding(.bottom, 12)
            }
            .scrollBounceBehavior(.basedOnSize)
            .background(JarvisBackdrop())
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: SettingsDestination.self) { destination in
                SettingsDetailView(destination: destination, sshSettings: piTerminal.settings,
                                   watchProvisioning: app.watchTerminalProvisioning)
            }
            .task { await notifications.refreshHostStatus() }
        }
    }
}

enum SettingsDestination: String, CaseIterable, Hashable {
    case connection, iphoneTerminal, watchTerminal, notifications

    var title: String {
        switch self {
        case .connection: return "Connection"
        case .iphoneTerminal: return "iPhone Terminal"
        case .watchTerminal: return "Watch Terminal"
        case .notifications: return "Notifications"
        }
    }

    var symbol: String {
        switch self {
        case .connection: return "server.rack"
        case .iphoneTerminal: return "terminal.fill"
        case .watchTerminal: return "applewatch"
        case .notifications: return "bell.badge.fill"
        }
    }
}

struct SettingsDashboard: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var piTerminal: PiTerminalController

    var body: some View {
        SettingsDashboardContent(sshSettings: piTerminal.settings,
                                 watchProvisioning: app.watchTerminalProvisioning)
    }
}

struct SettingsDashboardContent: View {
    @ObservedObject var sshSettings: PiTerminalSettings
    @ObservedObject var watchProvisioning: WatchTerminalProvisioningSettings
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var notifications: PushNotificationCoordinator
    @EnvironmentObject private var piTerminal: PiTerminalController
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @StateObject private var maintenance = PiSessionMaintenanceController()
    @State private var confirmRestart = false

    var body: some View {
        VStack(spacing: 12) {
            TabPageHeader(title: "Settings")
            SettingsSummaryGrid(columns: SettingsView.columnCount(for: dynamicTypeSize)) {
                SettingsSummaryCard(destination: .connection) {
                    summary(SettingsPresentation.daemonSummary(app), color: SettingsPresentation.daemonColor(app))
                    summary(SettingsPresentation.usingString(app) ?? "Automatic discovery")
                }
                SettingsSummaryCard(destination: .iphoneTerminal) {
                    summary(sshSettings.hasPassword ? "Configured" : "Setup required",
                            color: sshSettings.hasPassword ? JarvisPalette.accent : JarvisPalette.warning)
                    summary("\(sshSettings.host.isEmpty ? (app.currentEndpoint?.host ?? "Automatic host") : sshSettings.host):\(sshSettings.port)")
                    summary(sshSettings.username)
                }
                SettingsSummaryCard(destination: .watchTerminal) {
                    summary(watchProvisioning.isProvisioned ? "Provisioned" : "Setup required",
                            color: watchProvisioning.isProvisioned ? JarvisPalette.accent : JarvisPalette.warning)
                    summary(Self.bridgeHost(watchProvisioning.endpoint))
                }
                // The toggle is a sibling of the navigation link, never nested inside it.
                SettingsSummaryCard(destination: .notifications, accessory: AnyView(
                    Toggle("Alerts", isOn: Binding(get: { notifications.desiredEnabled }, set: { enabled in
                        Task { await notifications.setEnabled(enabled) }
                    }))
                    .font(.caption).frame(minHeight: 44)
                    .accessibilityLabel("JARVIS alerts")
                )) {
                    summary("iPhone · \(notifications.iphoneState.title)", color: notificationColor(notifications.iphoneState))
                    summary("Watch · \(notifications.watchState.title)", color: notificationColor(notifications.watchState))
                }
            }
            diagnosticsAndMaintenance
            Text("JARVIS \(SettingsPresentation.appVersion)")
                .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                .accessibilityLabel("JARVIS version \(SettingsPresentation.appVersion)")
        }
        .tint(JarvisPalette.accent)
        .alert("Restart all 10 Pi sessions?", isPresented: $confirmRestart) {
            Button("Cancel", role: .cancel) {}
            Button("Restart Sessions", role: .destructive) { runMaintenance(start: true) }
        } message: {
            Text("Active conversations are preserved; quit sessions reopen fresh. Busy sessions wait until idle, for up to 30 minutes; other sessions restart without waiting. Avoid sending new work during the restart. Watch and room-audio sessions are included. The restart continues on the Mac if this phone disconnects.")
        }
    }

    static func bridgeHost(_ endpoint: String) -> String {
        guard !endpoint.isEmpty else { return "Not provisioned" }
        guard let url = URL(string: endpoint), let host = url.host else { return "Bridge configured" }
        return host + (url.port.map { ":\($0)" } ?? "")
    }

    private var diagnosticsAndMaintenance: some View {
        SettingsInlineCard("Diagnostics & Maintenance", symbol: "wrench.and.screwdriver") {
            (dynamicTypeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
                : AnyLayout(HStackLayout(alignment: .top, spacing: 16))) {
                VStack(alignment: .leading, spacing: 6) {
                    metric("jarvisd", app.lastHealth?.version ?? "—")
                    metric("Uptime", app.lastHealth?.uptimeSeconds.map { JarvisFormat.uptime($0) } ?? "—")
                }
                VStack(alignment: .leading, spacing: 6) {
                    metric("LAN", app.lastState?.subsystems?.network?.macLanIp ?? "—")
                    metric("Tailscale", app.lastState?.subsystems?.network?.tailscaleIp ?? "—")
                }
            }
            Divider()
            Button("Restart all 10 Pi sessions", role: .destructive) { confirmRestart = true }
                .settingsAction()
                .disabled(maintenance.isWorking || maintenance.operationID != nil ||
                          sshSettings.configuration(fallbackHost: app.currentEndpoint?.host) == nil)
            if maintenance.isWorking {
                ProgressView("Restarting… \(maintenance.completed)/10").font(.caption)
            }
            if let message = maintenance.message {
                Text(message).font(.caption).foregroundStyle(.secondary)
                    .textSelection(.enabled).accessibilityIdentifier("pi-maintenance-status")
            }
            if maintenance.operationID != nil && !maintenance.isWorking {
                Button(maintenance.canRetrySubmission ? "Retry same request" : "Check restart status") {
                    runMaintenance(start: maintenance.canRetrySubmission)
                }
                .settingsAction()
            }
        }
    }

    private func summary(_ text: String, color: Color = .secondary) -> some View {
        Text(text).font(.caption).foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func notificationColor(_ state: JARVISNotificationLocalState) -> Color {
        switch state {
        case .active: return JarvisPalette.accent
        case .error, .denied: return JarvisPalette.warning
        default: return .secondary
        }
    }

    private func metric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label).foregroundStyle(.secondary)
            Text(value).monospacedDigit().fixedSize(horizontal: false, vertical: true)
        }
        .font(.caption)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func runMaintenance(start: Bool) {
        guard let configuration = sshSettings.configuration(fallbackHost: app.currentEndpoint?.host) else { return }
        maintenance.run(configuration: configuration,
                        trustedHostKey: sshSettings.trustedHostKey(host: configuration.host, port: configuration.port),
                        start: start) {
            piTerminal.reconnectAfterSettingsChange(fallbackHost: app.currentEndpoint?.host)
        }
    }
}

/// Every summary gets the same width AND height, measured from the largest card.
/// Long hosts or accessibility text grow the whole grid rather than clipping a card.
struct SettingsSummaryGrid: Layout {
    var columns: Int
    var spacing: CGFloat = 10

    func cellSize(width: CGFloat, subviews: Subviews) -> CGSize {
        let count = max(1, columns)
        let cellWidth = max(0, (width - CGFloat(count - 1) * spacing) / CGFloat(count))
        let height = subviews.map { $0.sizeThatFits(.init(width: cellWidth, height: nil)).height }.max() ?? 0
        return CGSize(width: cellWidth, height: max(176, height))
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 382
        let cell = cellSize(width: width, subviews: subviews)
        let rows = (subviews.count + max(1, columns) - 1) / max(1, columns)
        return CGSize(width: width, height: CGFloat(rows) * cell.height + CGFloat(max(0, rows - 1)) * spacing)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let cell = cellSize(width: bounds.width, subviews: subviews)
        for (index, view) in subviews.enumerated() {
            view.place(at: CGPoint(x: bounds.minX + CGFloat(index % max(1, columns)) * (cell.width + spacing),
                                   y: bounds.minY + CGFloat(index / max(1, columns)) * (cell.height + spacing)),
                       anchor: .topLeading, proposal: .init(cell))
        }
    }
}

struct SettingsSummaryCard<Content: View>: View {
    let destination: SettingsDestination
    var accessory: AnyView? = nil
    @ViewBuilder var content: Content

    var body: some View {
        MinimalCard(padding: 12) {
            VStack(alignment: .leading, spacing: 8) {
                NavigationLink(value: destination) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Image(systemName: destination.symbol).font(.title3)
                                .foregroundStyle(JarvisPalette.accent)
                            Spacer(minLength: 4)
                            Image(systemName: "chevron.right").font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                        .accessibilityHidden(true)
                        Text(destination.title).font(.subheadline.weight(.semibold))
                            .foregroundStyle(.primary)
                            .fixedSize(horizontal: false, vertical: true)
                        content
                        Spacer(minLength: 0)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Opens \(destination.title) settings")
                if let accessory { accessory }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }
}
