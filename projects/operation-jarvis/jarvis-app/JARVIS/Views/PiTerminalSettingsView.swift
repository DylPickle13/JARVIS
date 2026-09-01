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
                Text("A blank host follows JARVIS between LAN and Tailscale. The JARVIS tab remembers one of six persistent Pi conversations; swipe horizontally in the terminal to change it.")
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
        .alert("Forget trusted SSH host?", isPresented: $showForgetHostConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Forget Host", role: .destructive) {
                piTerminal.forgetTrustedHost(fallbackHost: app.currentEndpoint?.host)
            }
        } message: {
            Text("JARVIS will require explicit trust before the next terminal connection.")
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
