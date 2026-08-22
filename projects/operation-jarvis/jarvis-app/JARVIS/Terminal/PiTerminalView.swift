import SwiftUI
import SwiftTerm

struct PiTerminalView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var terminal: PiTerminalController

    @State private var editingLogin = false
    @State private var hostDraft = ""
    @State private var portDraft = "22"
    @State private var usernameDraft = ""
    @State private var passwordDraft = ""

    private var fallbackHost: String? { app.currentEndpoint?.host }
    private var configurationReady: Bool {
        terminal.settings.configuration(fallbackHost: fallbackHost) != nil
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if configurationReady, !editingLogin {
                VStack(spacing: 0) {
                    PiTerminalContainer(controller: terminal)
                        .background(Color.black)
                        .accessibilityLabel("Pi terminal")
                    PiTerminalKeyBar(controller: terminal)
                }
            } else {
                setupView
            }

            if configurationReady, !editingLogin {
                statusOverlay
            }
        }
        .onAppear {
            loadDrafts()
            terminal.setVisible(true, fallbackHost: fallbackHost)
        }
        .onDisappear {
            terminal.setVisible(false, fallbackHost: fallbackHost)
        }
        .onChange(of: fallbackHost) { _, value in
            if configurationReady {
                terminal.reconnectAfterSettingsChange(fallbackHost: value)
            }
        }
        .alert(item: Binding(
            get: { terminal.pendingHostTrust },
            set: { _ in }
        )) { request in
            Alert(
                title: Text("Trust this Mac?"),
                message: Text("\(request.host):\(request.port)\n\n\(request.fingerprint)"),
                primaryButton: .default(Text("Trust")) { terminal.trustPendingHost() },
                secondaryButton: .cancel { terminal.rejectPendingHost() }
            )
        }
    }

    @ViewBuilder
    private var statusOverlay: some View {
        switch terminal.status {
        case .idle:
            VStack {
                Spacer()
                Button("Connect") { terminal.retry() }
                    .buttonStyle(.borderedProminent)
                    .tint(.cyan)
                    .foregroundStyle(.black)
                    .padding(.bottom, 18)
            }
        case .connecting:
            VStack {
                HStack(spacing: 8) {
                    ProgressView().tint(.cyan)
                    Text("Connecting to Pi…")
                        .font(.caption.weight(.semibold))
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .foregroundStyle(.white)
                .background(.black.opacity(0.78), in: Capsule())
                .padding(.top, 8)
                Spacer()
            }
        case .connected:
            EmptyView()
        case .failed(let message):
            VStack(spacing: 14) {
                Image(systemName: "terminal.fill")
                    .font(.title)
                    .foregroundStyle(.cyan)
                Text("Pi disconnected")
                    .font(.headline)
                Text(message)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                HStack {
                    Button("Edit login") {
                        loadDrafts()
                        editingLogin = true
                    }
                    .buttonStyle(.bordered)
                    Button("Reconnect") { terminal.retry() }
                        .buttonStyle(.borderedProminent)
                        .tint(.cyan)
                        .foregroundStyle(.black)
                }
            }
            .padding(22)
            .frame(maxWidth: 330)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .padding()
        }
    }

    private var setupView: some View {
        ScrollView {
            VStack(spacing: 22) {
                Spacer(minLength: 24)
                Image(systemName: "terminal.fill")
                    .font(.system(size: 48, weight: .semibold))
                    .foregroundStyle(.cyan)
                    .accessibilityHidden(true)
                VStack(spacing: 6) {
                    Text("Pi Terminal")
                        .font(.title2.bold())
                    Text("Connect to this Mac and open your persistent Pi session.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                VStack(spacing: 12) {
                    TextField("SSH host (optional)", text: $hostDraft, prompt: Text(fallbackHost ?? "Mac hostname or IP"))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    TextField("Port", text: $portDraft)
                        .keyboardType(.numberPad)
                    TextField("Username", text: $usernameDraft)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Mac login password", text: $passwordDraft)
                        .textContentType(.password)
                }
                .textFieldStyle(.roundedBorder)
                .font(.body.monospaced())

                if let error = terminal.settings.credentialError {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .font(.callout)
                        .foregroundStyle(.red)
                }

                Button {
                    saveAndConnect()
                } label: {
                    Label("Save and connect", systemImage: "link")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.cyan)
                .foregroundStyle(.black)
                .disabled(hostDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && fallbackHost == nil)

                if editingLogin, configurationReady {
                    Button("Cancel") { editingLogin = false }
                        .buttonStyle(.bordered)
                }

                Text("The password stays in this iPhone’s Keychain. Leave SSH host blank to use JARVIS’s current LAN or Tailscale endpoint.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 30)
            .frame(maxWidth: 520)
            .frame(maxWidth: .infinity)
        }
        .background(Color(uiColor: .systemBackground))
    }

    private func loadDrafts() {
        hostDraft = terminal.settings.host
        portDraft = String(terminal.settings.port)
        usernameDraft = terminal.settings.username
        passwordDraft = terminal.settings.passwordForEditing()
    }

    private func saveAndConnect() {
        guard terminal.settings.save(
            host: hostDraft,
            portText: portDraft,
            username: usernameDraft,
            password: passwordDraft
        ) else { return }
        editingLogin = false
        terminal.reconnectAfterSettingsChange(fallbackHost: fallbackHost)
    }
}

private struct PiTerminalKeyBar: View {
    @ObservedObject var controller: PiTerminalController

    var body: some View {
        HStack(spacing: 0) {
            HStack(spacing: 6) {
                key("Esc", label: "Escape", bytes: [0x1b])
                Button {
                    controller.toggleControlLatch()
                } label: {
                    Text("Ctrl")
                        .foregroundStyle(controller.isControlLatched ? .black : .primary)
                        .padding(.horizontal, 10)
                        .frame(minWidth: 44, minHeight: 34)
                        .background(controller.isControlLatched ? Color.cyan : Color.secondary.opacity(0.16), in: RoundedRectangle(cornerRadius: 8))
                }
                .accessibilityLabel("Control modifier")
                key("Tab", label: "Tab", bytes: [0x09])
                key("/", label: "Slash", bytes: PiTerminalKeyDeck.slashBytes)
                key("↑", label: "Up arrow", bytes: [0x1b, 0x5b, 0x41])
                key("↓", label: "Down arrow", bytes: [0x1b, 0x5b, 0x42])
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)

            Divider()
                .frame(height: 30)

            Button {
                controller.toggleTerminalKeyboard()
            } label: {
                Image(systemName: controller.isTerminalFocused ? "keyboard.chevron.compact.down" : "keyboard")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(controller.isTerminalFocused ? Color.cyan : Color.primary)
                    .frame(width: 52, height: 46)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(controller.isTerminalFocused ? "Hide keyboard" : "Show keyboard")
            .accessibilityValue(controller.isTerminalFocused ? "Shown" : "Hidden")
        }
        .frame(height: 46)
        .background(.ultraThinMaterial)
    }

    private func key(_ title: String, label: String, bytes: [UInt8]) -> some View {
        Button {
            controller.sendTerminalBytes(bytes)
        } label: {
            keyLabel(title)
        }
        .accessibilityLabel(label)
    }

    private func keyLabel(_ title: String) -> some View {
        Text(title)
            .font(.callout.monospaced().weight(.semibold))
            .foregroundStyle(.primary)
            .padding(.horizontal, 10)
            .frame(minWidth: 44, minHeight: 34)
            .background(Color.secondary.opacity(0.16), in: RoundedRectangle(cornerRadius: 8))
    }

}

private struct PiTerminalContainer: UIViewRepresentable {
    let controller: PiTerminalController

    func makeCoordinator() -> Coordinator {
        Coordinator(controller: controller)
    }

    func makeUIView(context: Context) -> PiTerminalHostView {
        let view = PiTerminalHostView(frame: .zero)
        context.coordinator.controller.attach(view)
        return view
    }

    func updateUIView(_ uiView: PiTerminalHostView, context: Context) {}

    static func dismantleUIView(_ uiView: PiTerminalHostView, coordinator: Coordinator) {
        coordinator.controller.detach(uiView)
    }

    @MainActor
    final class Coordinator {
        let controller: PiTerminalController
        init(controller: PiTerminalController) { self.controller = controller }
    }
}

#Preview {
    let settings = PiTerminalSettings(defaults: UserDefaults(suiteName: "pi-terminal-preview")!)
    return PiTerminalView()
        .environmentObject(AppState())
        .environmentObject(PiTerminalController(settings: settings))
}
