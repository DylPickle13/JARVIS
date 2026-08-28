import SwiftUI

struct ConnectionSettingsView: View {
    @EnvironmentObject private var app: AppState
    @State private var showTechnicalDetails = false
    @State private var showResetConfirmation = false

    var body: some View {
        Form {
            if app.connectionState == .failed, let error = app.errorMessage {
                Section("Needs attention") {
                    Label {
                        Text(error)
                            .font(.callout)
                            .foregroundStyle(.red)
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                    }
                }
            }

            Section {
                SettingsStatusHeader(
                    title: "JARVIS daemon",
                    detail: SettingsPresentation.daemonSummary(app),
                    systemImage: app.connectionState == .connected ? "checkmark.circle.fill" : "server.rack",
                    color: SettingsPresentation.daemonColor(app)
                )

                if let activeEndpoint = SettingsPresentation.usingString(app) {
                    LabeledContent("Active endpoint", value: activeEndpoint)
                        .font(.callout)
                }

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
                Text("Connection")
            } footer: {
                Text("Leave the override blank to discover the Mac automatically over the home LAN or Tailscale.")
            }

            Section {
                DisclosureGroup("Technical Details", isExpanded: $showTechnicalDetails) {
                    LabeledContent("jarvisd", value: app.lastHealth?.version ?? "—")
                    if let uptime = app.lastHealth?.uptimeSeconds {
                        LabeledContent("Uptime", value: JarvisFormat.uptime(uptime))
                    }
                    if let network = app.lastState?.subsystems?.network {
                        LabeledContent("LAN IP", value: network.macLanIp ?? "—")
                        LabeledContent("Tailscale IP", value: network.tailscaleIp ?? "—")
                    } else {
                        LabeledContent("Network telemetry", value: "Unavailable")
                    }
                }
            }

            Section {
                Button(role: .destructive) {
                    showResetConfirmation = true
                } label: {
                    Label("Reset Connection", systemImage: "arrow.counterclockwise")
                        .frame(maxWidth: .infinity)
                }
            } footer: {
                Text("Reset removes the saved connection details and returns JARVIS to automatic discovery.")
            }
        }
        .compactSettingsForm(title: "Connection")
        .alert("Reset JARVIS connection?", isPresented: $showResetConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Reset Connection", role: .destructive) {
                app.clearConnection()
            }
        } message: {
            Text("You will need to reconnect before JARVIS can control or refresh services.")
        }
    }
}
