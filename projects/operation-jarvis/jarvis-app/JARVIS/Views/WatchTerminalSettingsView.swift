import SwiftUI
import JARVISKit

struct WatchTerminalSettingsView: View {
    @EnvironmentObject private var app: AppState
    @State private var setupCode = ""
    @State private var setupCodeSent = false
    @State private var showTechnicalDetails = false

    var body: some View {
        Form {
            Section("Status") {
                SettingsStatusHeader(
                    title: "Watch Terminal",
                    detail: app.watchTerminalProvisioning.isProvisioned ? "Provisioned" : "Setup required",
                    systemImage: "applewatch",
                    color: app.watchTerminalProvisioning.isProvisioned ? JarvisPalette.cyan : JarvisPalette.warning
                )
            }

            Section {
                SecureField("Watch terminal setup code", text: $setupCode)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.body.monospaced())

                Button {
                    guard app.watchTerminalProvisioning.save(provisioningCode: setupCode),
                          let configuration = app.watchTerminalProvisioning.configuration else {
                        setupCodeSent = false
                        return
                    }
                    WatchBridge.shared.publishTerminalConfiguration(configuration)
                    setupCode = ""
                    setupCodeSent = true
                } label: {
                    Label(
                        setupCodeSent ? "Sent to Apple Watch" : "Save and Send to Apple Watch",
                        systemImage: setupCodeSent ? "checkmark.circle.fill" : "applewatch.radiowaves.left.and.right"
                    )
                    .frame(maxWidth: .infinity)
                }
                .disabled(setupCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                if let error = app.watchTerminalProvisioning.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            } header: {
                Text(app.watchTerminalProvisioning.isProvisioned ? "Replace Provisioning" : "Provisioning")
            } footer: {
                Text("Paste the private code printed by scripts/jarvis-terminal-provisioning.sh. The token stays in Keychain and transfers only to your paired Watch.")
            }

            if app.watchTerminalProvisioning.isProvisioned {
                Section {
                    DisclosureGroup("Technical Details", isExpanded: $showTechnicalDetails) {
                        LabeledContent("Bridge", value: app.watchTerminalProvisioning.endpoint)
                            .font(.caption)
                    }
                }
            }
        }
        .compactSettingsForm(title: "Watch Terminal")
        .onAppear { setupCodeSent = false }
    }
}
