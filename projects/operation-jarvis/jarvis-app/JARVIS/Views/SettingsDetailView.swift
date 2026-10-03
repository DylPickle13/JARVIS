import SwiftUI
import JARVISKit
import UIKit

/// Editors are constructed only after navigation; the overview never loads passwords.
struct SettingsDetailView: View {
    let destination: SettingsDestination
    @ObservedObject var sshSettings: PiTerminalSettings
    @ObservedObject var watchProvisioning: WatchTerminalProvisioningSettings
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var notifications: PushNotificationCoordinator
    @EnvironmentObject private var piTerminal: PiTerminalController
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var sshHost = ""
    @State private var sshPort = "22"
    @State private var sshUsername = ""
    @State private var sshPassword = ""
    @State private var sshSaved = false
    @State private var loadedSettings = false
    @State private var setupCode = ""
    @State private var setupCodeSent = false
    @State private var confirmation: SettingsEditorConfirmation?

    private var rowLayout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 10))
            : AnyLayout(HStackLayout(alignment: .center, spacing: 10))
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                switch destination {
                case .connection:
                    connectionCard
                    Text("Leave the endpoint override blank to discover the Mac automatically over LAN or Tailscale.")
                        .font(.callout).foregroundStyle(.secondary)
                case .iphoneTerminal:
                    terminalCard
                    SettingsInlineCard("Security", symbol: "lock.shield") {
                        Button("Forget trusted SSH host", role: .destructive) { confirmation = .forget }
                            .settingsAction()
                        Text("Only forget trust if the Mac SSH host key intentionally changed. The next connection will require explicit trust.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                case .watchTerminal:
                    watchCard
                case .notifications:
                    notificationCard
                }
            }
            .padding(16)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(JarvisBackdrop())
        .navigationTitle(destination.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .onAppear {
            if destination == .iphoneTerminal { loadSettingsOnce() }
        }
        .task {
            if destination == .notifications { await notifications.refreshHostStatus() }
        }
        .alert(item: $confirmation) { action in
            switch action {
            case .reset:
                return Alert(title: Text("Reset JARVIS connection?"),
                    message: Text("Removes saved connection details and returns to automatic discovery. Reconnect before controlling or refreshing services."),
                    primaryButton: .destructive(Text("Reset Connection")) { app.clearConnection() },
                    secondaryButton: .cancel())
            case .forget:
                return Alert(title: Text("Forget trusted SSH host?"),
                    message: Text("Only do this if the Mac SSH host key intentionally changed. Explicit trust will be required at the next terminal connection."),
                    primaryButton: .destructive(Text("Forget Host")) {
                        piTerminal.forgetTrustedHost(fallbackHost: app.currentEndpoint?.host)
                    }, secondaryButton: .cancel())
            }
        }
    }

    private var connectionCard: some View {
        SettingsInlineCard("Connection", symbol: "server.rack",
                           detail: SettingsPresentation.daemonSummary(app),
                           detailColor: SettingsPresentation.daemonColor(app), accessory: AnyView(
            Button("Reset", role: .destructive) { confirmation = .reset }
                .accessibilityLabel("Reset connection").settingsAction()
        )) {
            value("Active", SettingsPresentation.usingString(app) ?? "Automatic discovery")
            rowLayout {
                SettingsInlineField("Endpoint override") {
                    TextField("Automatic · LAN or Tailscale", text: $app.endpointDraft)
                        .keyboardType(.URL)
                        .accessibilityLabel("Endpoint override; blank uses automatic discovery")
                }
                Button(app.connectionState == .connecting ? "Connecting…" : "Connect") {
                    Task { await app.connect() }
                }
                .disabled(app.connectionState == .connecting)
                .settingsAction()
            }
            if app.connectionState == .failed, let error = app.errorMessage { issue(error) }
        }
    }

    private var terminalCard: some View {
        SettingsInlineCard("iPhone Terminal", symbol: "terminal.fill",
                           detail: sshSettings.hasPassword ? "Configured" : "Setup required",
                           detailColor: sshSettings.hasPassword ? JarvisPalette.accent : JarvisPalette.warning,
                           accessory: AnyView(
            Button(sshSaved ? "Saved" : "Save login", action: saveSSH).settingsAction()
        )) {
            rowLayout {
                SettingsInlineField("SSH host · blank follows JARVIS") {
                    TextField(app.currentEndpoint?.host ?? "Automatic", text: $sshHost)
                        .keyboardType(.URL).accessibilityLabel("SSH host; blank follows JARVIS")
                }
                SettingsInlineField("Port") {
                    TextField("22", text: $sshPort)
                        .keyboardType(.numberPad).accessibilityLabel("SSH port")
                }
                .frame(maxWidth: dynamicTypeSize.isAccessibilitySize ? .infinity : 64)
            }
            rowLayout {
                SettingsInlineField("Username") {
                    TextField("Mac username", text: $sshUsername)
                        .textContentType(.username).accessibilityLabel("SSH username")
                }
                SettingsInlineField("Password") {
                    SecureField("Mac login password", text: $sshPassword)
                        .textContentType(.password).accessibilityLabel("Mac login password")
                }
            }
            if let error = sshSettings.credentialError { issue(error) }
        }
        .onChange(of: sshHost) { sshSaved = false }
        .onChange(of: sshPort) { sshSaved = false }
        .onChange(of: sshUsername) { sshSaved = false }
        .onChange(of: sshPassword) { sshSaved = false }
    }

    private var watchCard: some View {
        SettingsInlineCard("Watch Terminal", symbol: "applewatch") {
            status(watchProvisioning.isProvisioned ? "Provisioned" : "Setup required",
                   color: watchProvisioning.isProvisioned ? JarvisPalette.accent : JarvisPalette.warning)
            value("Bridge", watchProvisioning.endpoint.isEmpty ? "Not provisioned" : watchProvisioning.endpoint)
            rowLayout {
                SettingsInlineField("Setup code") {
                    SecureField("Paste code", text: $setupCode)
                        .accessibilityLabel("Watch terminal setup code")
                }
                Button(setupCodeSent ? "Sent" : "Send", action: sendWatchCode)
                    .disabled(setupCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityLabel(setupCodeSent ? "Sent to Apple Watch" : "Save and send to Apple Watch")
                    .settingsAction()
            }
            Text("jarvis-terminal-provisioning.sh\nKeychain → paired Watch")
                .font(.caption2).foregroundStyle(.secondary)
            if let error = watchProvisioning.errorMessage { issue(error) }
        }
        .onChange(of: setupCode) { if !setupCode.isEmpty { setupCodeSent = false } }
    }

    private var notificationCard: some View {
        SettingsInlineCard("Notifications", symbol: "bell.badge.fill",
                           detail: "JARVIS alerts · \(notifications.overallTitle)", accessory: AnyView(
            Toggle("JARVIS alerts", isOn: Binding(get: { notifications.desiredEnabled }, set: { enabled in
                Task { await notifications.setEnabled(enabled) }
            }))
            .labelsHidden().frame(minHeight: 44)
        )) {
            rowLayout {
                value("iPhone", notifications.iphoneState.title)
                value("Watch", notifications.watchState.title)
            }
            if let host = notifications.hostStatus {
                rowLayout {
                    value("APNs", host.providerConfigured ? "Configured" : "Not configured")
                    value("Dispatch", host.dispatchEnabled ? "Enabled" : "Disabled")
                }
                Text("Queue: \(host.pendingCount) pending · \(host.failedCount) failed · \(host.ambiguousCount) uncertain")
                    .font(.caption)
                    .foregroundStyle(host.failedCount == 0 && host.ambiguousCount == 0 ? Color.secondary : JarvisPalette.warning)
                if let error = host.error, !error.isEmpty {
                    issue(error).accessibilityIdentifier("notification-provider-error")
                }
            } else {
                Text("APNs, dispatch and queue: status unavailable")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let error = notifications.errorMessage {
                issue(error).accessibilityIdentifier("notification-error")
            }
            rowLayout {
                Button("Retry secure update") { Task { await notifications.retryPendingRegistrations() } }
                    .disabled(!notifications.canRetrySecureUpdate).settingsAction()
                Spacer(minLength: 0)
                Button("Refresh") { Task { await notifications.refreshHostStatus() } }
                    .disabled(notifications.isWorking)
                    .accessibilityLabel("Refresh notification status").settingsAction()
            }
            if notifications.authorizationStatus == .denied {
                Button("Open iPhone Notification Settings") {
                    guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
                    UIApplication.shared.open(url)
                }
                .settingsAction()
            }
            Text("Best-effort alerts include intentional Pi updates and scheduled-job previews, not automatic session-finish alerts. Tap a Pi alert to open its session. Hide Lock Screen previews in iOS Show Previews; full job results stay in Jobs.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    private func status(_ text: String, color: Color) -> some View {
        Text(text).font(.caption.weight(.medium)).foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func value(_ label: String, _ text: String) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(label).foregroundStyle(.secondary)
                Spacer(minLength: 0)
                Text(text).fixedSize()
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(label).foregroundStyle(.secondary)
                Text(text).fixedSize(horizontal: false, vertical: true)
            }
        }
        .font(.caption.monospacedDigit())
        .accessibilityElement(children: .combine)
    }

    private func issue(_ text: String) -> some View {
        Text(text).font(.caption).foregroundStyle(JarvisPalette.warning)
            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
    }

    private func loadSettingsOnce() {
        guard !loadedSettings else { return }
        sshHost = sshSettings.host
        sshPort = String(sshSettings.port)
        sshUsername = sshSettings.username
        sshPassword = sshSettings.passwordForEditing()
        loadedSettings = true
    }

    private func saveSSH() {
        sshSaved = sshSettings.save(host: sshHost, portText: sshPort,
                                            username: sshUsername, password: sshPassword)
        if sshSaved {
            piTerminal.reconnectAfterSettingsChange(fallbackHost: app.currentEndpoint?.host)
        }
    }

    private func sendWatchCode() {
        guard watchProvisioning.save(provisioningCode: setupCode),
              let configuration = watchProvisioning.configuration else {
            setupCodeSent = false
            return
        }
        WatchBridge.shared.publishTerminalConfiguration(configuration)
        setupCode = ""
        setupCodeSent = true
    }

}

private enum SettingsEditorConfirmation: String, Identifiable {
    case reset, forget
    var id: String { rawValue }
}

struct SettingsInlineCard<Content: View>: View {
    let title: String
    let symbol: String
    let detail: String?
    let detailColor: Color
    let accessory: AnyView?
    @ViewBuilder var content: Content
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(_ title: String, symbol: String, detail: String? = nil, detailColor: Color = .secondary,
         accessory: AnyView? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.symbol = symbol
        self.detail = detail
        self.detailColor = detailColor
        self.accessory = accessory
        self.content = content()
    }

    var body: some View {
        MinimalCard(padding: 14) {
            VStack(alignment: .leading, spacing: 10) {
                (dynamicTypeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: 0))
                    : AnyLayout(HStackLayout(spacing: 4))) {
                    VStack(alignment: .leading, spacing: 1) {
                        Label(title, systemImage: symbol)
                            .font(.subheadline.weight(.semibold))
                            .fixedSize(horizontal: false, vertical: true)
                            .foregroundStyle(JarvisPalette.accent)
                            .accessibilityAddTraits(.isHeader)
                        if let detail {
                            Text(detail).font(.caption).foregroundStyle(detailColor)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    if let accessory {
                        Spacer(minLength: 0)
                        accessory
                    }
                }
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct SettingsInlineField<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    @FocusState private var isFocused: Bool

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            content.font(.subheadline.monospaced())
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .focused($isFocused)
        }
        .padding(.horizontal, 6)
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .background(.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 7))
        .contentShape(Rectangle())
        .onTapGesture { isFocused = true }
    }
}

private struct SettingsActionStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.semibold))
            .foregroundStyle(configuration.role == .destructive ? Color.red : JarvisPalette.accent)
            .padding(.horizontal, 4)
            .frame(minWidth: 44, minHeight: 44)
            .contentShape(Rectangle())
            .opacity(isEnabled ? (configuration.isPressed ? 0.6 : 1) : 0.4)
    }
}

extension View {
    func settingsAction() -> some View {
        buttonStyle(SettingsActionStyle())
    }
}
