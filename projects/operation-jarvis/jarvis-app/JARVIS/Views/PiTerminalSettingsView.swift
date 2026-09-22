import SwiftUI

struct PiTerminalSettingsView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var piTerminal: PiTerminalController
    @State private var sshHost = ""
    @State private var sshPort = "22"
    @State private var sshUsername = ""
    @State private var sshPassword = ""
    @State private var sshSaved = false
    @State private var showSecurityDetails = false
    @State private var showForgetHostConfirmation = false
    @State private var showRestartConfirmation = false
    @StateObject private var maintenance = PiSessionMaintenanceController()

    var body: some View {
        Form {
            Section("Status") {
                SettingsStatusHeader(
                    title: "Pi Terminal",
                    detail: piTerminal.settings.hasPassword ? "Configured" : "Setup required",
                    systemImage: "terminal.fill",
                    color: piTerminal.settings.hasPassword ? JarvisPalette.accent : JarvisPalette.warning
                )
            }

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
                Text("SSH Login")
            } footer: {
                Text("A blank host follows JARVIS between LAN and Tailscale. The JARVIS tab remembers one of nine persistent Pi conversations; swipe horizontally in the terminal to change it.")
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
                        sshSaved ? "SSH Login Saved" : "Save SSH Login",
                        systemImage: sshSaved ? "checkmark.circle.fill" : "key.fill"
                    )
                    .frame(maxWidth: .infinity)
                }

                if let error = piTerminal.settings.credentialError {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            Section {
                Button {
                    showRestartConfirmation = true
                } label: {
                    Label("Restart All 10 Pi Sessions", systemImage: "arrow.clockwise")
                }
                .disabled(maintenance.isWorking || maintenance.operationID != nil ||
                          piTerminal.settings.configuration(fallbackHost: app.currentEndpoint?.host) == nil)

                if maintenance.isWorking {
                    ProgressView("Restarting sessions… \(maintenance.completed)/10")
                }
                if let message = maintenance.message {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .accessibilityIdentifier("pi-maintenance-status")
                }
                if maintenance.operationID != nil && !maintenance.isWorking {
                    Button(maintenance.canRetrySubmission ? "Retry Same Request" : "Check Restart Status") {
                        runMaintenance(start: maintenance.canRetrySubmission)
                    }
                }
            } header: {
                Text("Session Maintenance")
            } footer: {
                Text("Restarts all 10 Pi sessions on the Mac, including sessions used by Watch and room audio. Active conversations are preserved; quit sessions reopen fresh. Busy sessions block the restart.")
            }

            Section {
                DisclosureGroup("Security", isExpanded: $showSecurityDetails) {
                    Button(role: .destructive) {
                        showForgetHostConfirmation = true
                    } label: {
                        Label(
                            "Forget Trusted SSH Host",
                            systemImage: "exclamationmark.arrow.triangle.2.circlepath"
                        )
                        .frame(maxWidth: .infinity)
                    }
                }
            } footer: {
                Text("Forget the trusted host only if the Mac SSH host key has intentionally changed.")
            }
        }
        .compactSettingsForm(title: "Pi Terminal")
        .onAppear { loadSettings() }
        .alert("Restart all 10 Pi sessions?", isPresented: $showRestartConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Restart Sessions", role: .destructive) { runMaintenance(start: true) }
        } message: {
            Text("Active conversations will be preserved; quit sessions will reopen fresh. Busy sessions will block the restart. Watch and room-audio sessions are also affected. The restart continues on the Mac if this phone disconnects.")
        }
        .alert("Forget trusted SSH host?", isPresented: $showForgetHostConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Forget Host", role: .destructive) {
                piTerminal.forgetTrustedHost(fallbackHost: app.currentEndpoint?.host)
            }
        } message: {
            Text("JARVIS will require explicit trust before the next terminal connection.")
        }
    }

    private func runMaintenance(start: Bool) {
        guard let configuration = piTerminal.settings.configuration(fallbackHost: app.currentEndpoint?.host) else { return }
        maintenance.run(
            configuration: configuration,
            trustedHostKey: piTerminal.settings.trustedHostKey(host: configuration.host, port: configuration.port),
            start: start
        ) {
            piTerminal.reconnectAfterSettingsChange(fallbackHost: app.currentEndpoint?.host)
        }
    }

    private func loadSettings() {
        sshHost = piTerminal.settings.host
        sshPort = String(piTerminal.settings.port)
        sshUsername = piTerminal.settings.username
        sshPassword = piTerminal.settings.passwordForEditing()
        sshSaved = false
    }
}
