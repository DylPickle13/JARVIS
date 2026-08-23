import SwiftUI
import JARVISKit

/// Compact settings index. Infrequent configuration and diagnostics remain
/// fully available one level deeper instead of occupying the primary viewport.
struct SettingsView: View {
    @EnvironmentObject var app: AppState
    @EnvironmentObject var piTerminal: PiTerminalController
    @State private var sshHost = ""
    @State private var sshPort = "22"
    @State private var sshUsername = ""
    @State private var sshPassword = ""
    @State private var sshSaved = false
    @State private var watchTerminalSetupCode = ""
    @State private var watchTerminalSent = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 15) {
                    settingsGroup(title: "Connections") {
                        NavigationLink {
                            connectionDetail
                        } label: {
                            settingsRow(
                                title: "JARVIS daemon",
                                systemImage: "server.rack",
                                value: daemonSummary,
                                color: daemonColor
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            piTerminalDetail
                        } label: {
                            settingsRow(
                                title: "Pi terminal",
                                systemImage: "terminal.fill",
                                value: piTerminalSummary,
                                color: piTerminal.settings.hasPassword ? JarvisPalette.cyan : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            watchTerminalDetail
                        } label: {
                            settingsRow(
                                title: "Apple Watch",
                                systemImage: "applewatch",
                                value: app.watchTerminalProvisioning.isProvisioned ? "Provisioned" : "Setup required",
                                color: app.watchTerminalProvisioning.isProvisioned ? JarvisPalette.cyan : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)
                    }

                    settingsGroup(title: "Support") {
                        NavigationLink {
                            diagnosticsDetail
                        } label: {
                            settingsRow(
                                title: "Diagnostics",
                                systemImage: "stethoscope",
                                value: diagnosticsSummary,
                                color: app.connectionState == .failed ? .red : .secondary
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            aboutDetail
                        } label: {
                            settingsRow(
                                title: "About JARVIS",
                                systemImage: "info.circle",
                                value: appVersion,
                                color: .secondary
                            )
                        }
                        .buttonStyle(.plain)
                    }

                    if app.connectionState == .failed, let error = app.errorMessage {
                        Label {
                            Text(error)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        } icon: {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(.red)
                        }
                        .padding(.horizontal, 4)
                        .accessibilityElement(children: .combine)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
            .scrollIndicators(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle("Settings")
            .onAppear { loadPiTerminalSettings() }
        }
    }

    // MARK: - Compact index

    private func settingsGroup<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
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

    private func settingsRow(
        title: String,
        systemImage: String,
        value: String,
        color: Color
    ) -> some View {
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
    }

    private var settingsDivider: some View {
        Divider().padding(.leading, 35)
    }

    private var daemonSummary: String {
        switch app.connectionState {
        case .connected: return "Connected · \(networkLabel)"
        case .connecting: return "Connecting"
        case .failed: return "Offline"
        case .idle: return "Not connected"
        }
    }

    private var daemonColor: Color {
        switch app.connectionState {
        case .connected: return JarvisPalette.cyan
        case .connecting: return JarvisPalette.warning
        case .failed: return .red
        case .idle: return .secondary
        }
    }

    private var piTerminalSummary: String {
        piTerminal.settings.hasPassword ? "Configured" : "Setup required"
    }

    private var diagnosticsSummary: String {
        app.connectionState == .failed ? "Needs attention" : "Status and network"
    }

    private var networkLabel: String {
        guard let host = app.currentEndpoint?.host else { return "—" }
        if host.hasPrefix("100.") || host.hasSuffix(".ts.net") { return "Tailscale" }
        if host.hasPrefix("192.168") || host.hasPrefix("10.") || host.hasPrefix("172.") { return "LAN" }
        return host
    }

    // MARK: - JARVIS connection

    private var connectionDetail: some View {
        Form {
            Section("Status") {
                LabeledContent("JARVIS daemon") {
                    ConnectionBadge(state: app.connectionState, detail: daemonSummary)
                }
                if let uptime = app.lastHealth?.uptimeSeconds {
                    LabeledContent("Uptime", value: JarvisFormat.uptime(uptime))
                }
                if let using = usingString {
                    LabeledContent("Using", value: using)
                        .font(.callout)
                }
            }

            Section {
                TextField(
                    "Endpoint override",
                    text: $app.endpointDraft,
                    prompt: Text("Automatic · LAN or Tailscale")
                )
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .font(.body.monospaced())

                Button {
                    Task { await app.connect() }
                } label: {
                    HStack {
                        Spacer()
                        if app.connectionState == .connecting {
                            ProgressView().frame(width: 20)
                            Text("Connecting…")
                        } else {
                            Label("Connect", systemImage: "link")
                        }
                        Spacer()
                    }
                }
                .disabled(app.connectionState == .connecting)
            } header: {
                Text("Endpoint")
            } footer: {
                Text("Leave blank to discover the Mac automatically over the home LAN or Tailscale.")
            }

            Section {
                Button(role: .destructive) {
                    app.clearConnection()
                } label: {
                    Label("Reset connection", systemImage: "arrow.counterclockwise")
                        .frame(maxWidth: .infinity)
                }
            }

            if app.connectionState == .failed, let error = app.errorMessage {
                Section("Error") {
                    Label {
                        Text(error).font(.callout).foregroundStyle(.red)
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                    }
                }
            }
        }
        .compactSettingsForm(title: "JARVIS connection")
    }

    // MARK: - Pi terminal

    private var piTerminalDetail: some View {
        Form {
            Section {
                TextField(
                    "SSH host",
                    text: $sshHost,
                    prompt: Text(app.currentEndpoint?.host ?? "Automatic from JARVIS")
                )
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .font(.body.monospaced())

                TextField("SSH port", text: $sshPort)
                    .keyboardType(.numberPad)
                    .font(.body.monospaced())

                TextField("SSH username", text: $sshUsername)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.body.monospaced())

                SecureField("Mac login password", text: $sshPassword)
                    .textContentType(.password)
                    .font(.body.monospaced())
            } header: {
                Text("SSH login")
            } footer: {
                Text("A blank host follows JARVIS between LAN and Tailscale. Opening the JARVIS tab attaches to the persistent jarvis-ios tmux session.")
            }

            Section {
                Button {
                    sshSaved = piTerminal.settings.save(
                        host: sshHost,
                        portText: sshPort,
                        username: sshUsername,
                        password: sshPassword
                    )
                    if sshSaved {
                        piTerminal.reconnectAfterSettingsChange(fallbackHost: app.currentEndpoint?.host)
                    }
                } label: {
                    Label(
                        sshSaved ? "SSH login saved" : "Save SSH login",
                        systemImage: sshSaved ? "checkmark.circle.fill" : "key.fill"
                    )
                    .frame(maxWidth: .infinity)
                }

                Button(role: .destructive) {
                    piTerminal.forgetTrustedHost(fallbackHost: app.currentEndpoint?.host)
                } label: {
                    Label("Forget trusted SSH host", systemImage: "exclamationmark.arrow.triangle.2.circlepath")
                        .frame(maxWidth: .infinity)
                }

                if let error = piTerminal.settings.credentialError {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
        }
        .compactSettingsForm(title: "Pi terminal")
        .onAppear { loadPiTerminalSettings() }
    }

    private func loadPiTerminalSettings() {
        sshHost = piTerminal.settings.host
        sshPort = String(piTerminal.settings.port)
        sshUsername = piTerminal.settings.username
        sshPassword = piTerminal.settings.passwordForEditing()
        sshSaved = false
        watchTerminalSent = false
    }

    // MARK: - Watch terminal

    private var watchTerminalDetail: some View {
        Form {
            Section {
                LabeledContent(
                    "Status",
                    value: app.watchTerminalProvisioning.isProvisioned ? "Provisioned" : "Not provisioned"
                )
                if app.watchTerminalProvisioning.isProvisioned {
                    LabeledContent("Bridge", value: app.watchTerminalProvisioning.endpoint)
                        .font(.caption)
                }
            }

            Section {
                SecureField("Watch terminal setup code", text: $watchTerminalSetupCode)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.body.monospaced())

                Button {
                    guard app.watchTerminalProvisioning.save(provisioningCode: watchTerminalSetupCode),
                          let configuration = app.watchTerminalProvisioning.configuration else {
                        watchTerminalSent = false
                        return
                    }
                    WatchBridge.shared.publishTerminalConfiguration(configuration)
                    watchTerminalSetupCode = ""
                    watchTerminalSent = true
                } label: {
                    Label(
                        watchTerminalSent ? "Sent to Apple Watch" : "Save and send to Apple Watch",
                        systemImage: watchTerminalSent ? "checkmark.circle.fill" : "applewatch.radiowaves.left.and.right"
                    )
                    .frame(maxWidth: .infinity)
                }
                .disabled(watchTerminalSetupCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                if let error = app.watchTerminalProvisioning.errorMessage {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            } header: {
                Text("Provisioning")
            } footer: {
                Text("Paste the private code printed by scripts/jarvis-terminal-provisioning.sh. The token stays in Keychain and is transferred only to your paired Watch.")
            }
        }
        .compactSettingsForm(title: "Apple Watch")
    }

    // MARK: - Diagnostics and About

    private var diagnosticsDetail: some View {
        Form {
            Section("Connection") {
                LabeledContent("Status") {
                    ConnectionBadge(state: app.connectionState, detail: daemonSummary)
                }
                LabeledContent("Endpoint", value: usingString ?? "—")
                LabeledContent("Daemon", value: "jarvisd \(app.lastHealth?.version ?? "—")")
                if let uptime = app.lastHealth?.uptimeSeconds {
                    LabeledContent("Uptime", value: JarvisFormat.uptime(uptime))
                }
            }

            Section("Network") {
                if let network = app.lastState?.subsystems?.network {
                    LabeledContent("LAN IP", value: network.macLanIp ?? "—")
                    LabeledContent("Tailscale IP", value: network.tailscaleIp ?? "—")
                } else {
                    LabeledContent("Network telemetry", value: "Unavailable")
                }
            }

            if let error = app.errorMessage {
                Section("Last error") {
                    Text(error).foregroundStyle(.red)
                }
            }
        }
        .compactSettingsForm(title: "Diagnostics")
    }

    private var aboutDetail: some View {
        Form {
            Section {
                LabeledContent("App", value: "JARVIS")
                LabeledContent("Version", value: appVersion)
                LabeledContent("Daemon", value: "jarvisd \(app.lastHealth?.version ?? "—")")
            }
        }
        .compactSettingsForm(title: "About JARVIS")
    }

    private var usingString: String? {
        guard let endpoint = app.currentEndpoint, let host = endpoint.host else { return nil }
        let port = endpoint.port.map(String.init) ?? "8790"
        return host + ":" + port
    }

    private var appVersion: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(version) (\(build))"
    }
}

private extension View {
    func compactSettingsForm(title: String) -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
    }
}

#Preview {
    let settings = PiTerminalSettings(defaults: UserDefaults(suiteName: "pi-settings-preview")!)
    return SettingsView()
        .environmentObject(AppState())
        .environmentObject(PiTerminalController(settings: settings))
}
