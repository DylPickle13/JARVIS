import JARVISKit
import SwiftUI
import SwiftTerm

enum PiTerminalFeatureGate {
#if JARVIS_NATIVE_ATTACHMENTS
    static let nativeAttachmentsEnabled = true
#else
    // The first signed candidate remains keyboard-only. Enable this condition
    // only on the later attachment candidate after keyboard acceptance.
    static let nativeAttachmentsEnabled = false
#endif
}

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
                GeometryReader { geometry in
                    PiTerminalContainer(controller: terminal)
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .background(Color.black)
                        .accessibilityLabel("Pi terminal")
                }
            } else {
                setupView
            }

            if configurationReady, !editingLogin {
                statusOverlay
                sessionIndicator
            }
        }
        .tint(JarvisPalette.accent)
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
        .alert("Review paste", isPresented: Binding(
            get: { terminal.pasteReview != nil },
            set: { if !$0 { terminal.pasteReview = nil } }
        ), presenting: terminal.pasteReview) { review in
            if review.supportsMultiline {
                Button("Paste text") { terminal.confirmPaste(id: review.id, singleLine: false) }
            }
            Button("Paste as one line") { terminal.confirmPaste(id: review.id, singleLine: true) }
            Button("Cancel", role: .cancel) { terminal.cancelPaste() }
        } message: { review in
            Text((review.supportsMultiline ? "Enter will not be appended.\n\n" : "Safe multiline paste is unavailable; choose one line.\n\n") + review.preview)
        }
        .alert("Cannot paste", isPresented: Binding(
            get: { terminal.pasteError != nil }, set: { if !$0 { terminal.pasteError = nil } }
        )) {
            Button("OK", role: .cancel) { terminal.pasteError = nil }
        } message: { Text(terminal.pasteError ?? "") }
        .sheet(isPresented: Binding(
            get: { terminal.isAttachmentSheetPresented },
            set: { presented in
                if !presented { terminal.dismissAttachmentSheet() }
            }
        )) {
            PiAttachmentPickerView(controller: terminal)
        }
    }

    private var sessionIndicator: some View {
        VStack {
            HStack(spacing: 5) {
                ForEach(JARVISTerminalSlot.allCases, id: \.self) { slot in
                    if slot.hasLeadingIndicatorGap {
                        Spacer().frame(width: 3)
                    }
                    Capsule()
                        .fill(slot == terminal.selectedSlot ? JarvisPalette.accent : Color.white.opacity(0.38))
                        .frame(width: slot == terminal.selectedSlot ? 15 : 7, height: 4)
                }
                Text(terminal.selectedSlot.displayName)
                    .font(.caption2.bold().monospacedDigit())
                    .foregroundStyle(.white)
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 7)
            .jarvisGlassSurface(Color.black.opacity(0.72), in: Capsule(), glass: true)
            .environment(\.colorScheme, .dark)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.top, 8)
            .padding(.trailing, 9)
            Spacer()
        }
        .allowsHitTesting(false)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Pi terminal session \(terminal.selectedSlot.displayName) of \(JARVISTerminalSlot.allCases.count)")
        .accessibilityHint("Swipe left or right across the terminal to change session")
    }

    @ViewBuilder
    private var statusOverlay: some View {
        switch terminal.status {
        case .idle:
            VStack {
                Spacer()
                Button("Connect") { terminal.retry() }
                    .buttonStyle(.borderedProminent)
                    .tint(JarvisPalette.accent)
                    .foregroundStyle(JarvisPalette.onAccent)
                    .padding(.bottom, 18)
            }
        case .connecting:
            VStack {
                HStack(spacing: 8) {
                    ProgressView().tint(JarvisPalette.accent)
                    Text("Connecting to Pi…")
                        .font(.caption.weight(.semibold))
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .foregroundStyle(.white)
                .jarvisGlassSurface(Color.black.opacity(0.78), in: Capsule(), glass: true)
                .environment(\.colorScheme, .dark)
                .padding(.top, 8)
                Spacer()
            }
        case .connected:
            EmptyView()
        case .failed(let message):
            VStack(spacing: 14) {
                Image(systemName: "terminal.fill")
                    .font(.title)
                    .foregroundStyle(JarvisPalette.accent)
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
                        .tint(JarvisPalette.accent)
                        .foregroundStyle(JarvisPalette.onAccent)
                }
            }
            .padding(22)
            .frame(maxWidth: 330)
            .jarvisGlassSurface(Color.black.opacity(0.78), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .padding()
        }
    }

    private var setupView: some View {
        ScrollView {
            VStack(spacing: 22) {
                Spacer(minLength: 24)
                Image(systemName: "terminal.fill")
                    .font(.system(size: 48, weight: .semibold))
                    .foregroundStyle(JarvisPalette.accent)
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
                .tint(JarvisPalette.accent)
                .foregroundStyle(JarvisPalette.onAccent)
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

/// A width budget shared by the real toolbar and narrow-screen regression tests.
/// Text keys get more room than arrows; no control has a fixed width or scrolls.
enum PiTerminalToolbarAction: CaseIterable {
    case escape, control, tab, slash, up, down, paste, attach, keyboard

    var weight: CGFloat {
        switch self {
        case .escape, .control, .tab: 1.15
        case .slash, .up, .down: 0.8
        default: 1
        }
    }
}

struct PiTerminalToolbarMetrics {
    static let height: CGFloat = 46
    static let inset: CGFloat = 4
    static let spacing: CGFloat = 2
    let availableWidth: CGFloat
    let showsAttachments: Bool

    var actions: [PiTerminalToolbarAction] {
        PiTerminalToolbarAction.allCases.filter { showsAttachments || $0 != .attach }
    }

    func width(for action: PiTerminalToolbarAction) -> CGFloat {
        let usable = max(0, availableWidth - Self.inset * 2 - CGFloat(actions.count - 1) * Self.spacing)
        return usable * action.weight / actions.reduce(0) { $0 + $1.weight }
    }
}

struct PiTerminalToolbarButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(isEnabled ? (configuration.isPressed ? 0.65 : 1) : 0.4)
    }
}

struct PiTerminalKeyBar: View {
    static let height = PiTerminalToolbarMetrics.height
    @ObservedObject var controller: PiTerminalController

    var body: some View {
        PiTerminalToolbarContent(
            showsAttachments: PiTerminalFeatureGate.nativeAttachmentsEnabled,
            canSend: controller.canSendTerminalInput,
            canAttach: controller.canOpenAttachments,
            controlLatched: controller.isControlLatched,
            keyboardShown: controller.isTerminalFocused
        ) { action in
            switch action {
            case .escape: controller.sendTerminalBytes([0x1b])
            case .control: controller.toggleControlLatch()
            case .tab: controller.sendTerminalBytes([0x09])
            case .slash: controller.sendTerminalBytes(PiTerminalKeyDeck.slashBytes)
            case .up: controller.sendTerminalBytes([0x1b, 0x5b, 0x41])
            case .down: controller.sendTerminalBytes([0x1b, 0x5b, 0x42])
            case .paste: controller.pasteIntoTerminal()
            case .attach: controller.presentAttachmentSheet()
            case .keyboard: controller.toggleTerminalKeyboard()
            }
        }
    }
}

/// Stateless presentation also lets render fixtures exercise every state without
/// connecting to, reading the clipboard for, or submitting to a live Pi session.
struct PiTerminalToolbarContent: View {
    let showsAttachments: Bool
    let canSend: Bool
    let canAttach: Bool
    let controlLatched: Bool
    let keyboardShown: Bool
    let perform: (PiTerminalToolbarAction) -> Void

    var body: some View {
        GeometryReader { geometry in
            let metrics = PiTerminalToolbarMetrics(availableWidth: geometry.size.width, showsAttachments: showsAttachments)
            HStack(spacing: PiTerminalToolbarMetrics.spacing) {
                key("Esc", label: "Escape", action: .escape, metrics: metrics)
                key("Ctrl", label: "Control modifier", action: .control, metrics: metrics)
                    .accessibilityValue(controlLatched ? "Latched" : "Off")
                key("Tab", label: "Tab", action: .tab, metrics: metrics)
                key("/", label: "Slash", action: .slash, metrics: metrics)
                key("↑", label: "Up arrow", action: .up, metrics: metrics)
                key("↓", label: "Down arrow", action: .down, metrics: metrics)
                PiTerminalPasteControl(width: metrics.width(for: .paste)) { perform(.paste) }
                    .disabled(!canSend)
                if showsAttachments {
                    icon("paperclip", label: "Attach files", action: .attach, metrics: metrics)
                        .disabled(!canAttach)
                        .accessibilityHint("Choose Photos or Files for the next Pi message")
                }
                icon(keyboardShown ? "keyboard.chevron.compact.down" : "keyboard",
                     label: keyboardShown ? "Hide keyboard" : "Show keyboard", action: .keyboard, metrics: metrics)
                    .disabled(!keyboardShown && !canSend)
                    .accessibilityValue(keyboardShown ? "Shown" : "Hidden")
            }
            .padding(.horizontal, PiTerminalToolbarMetrics.inset)
        }
        .frame(height: PiTerminalToolbarMetrics.height)
        .tint(JarvisPalette.accent)
        .buttonStyle(PiTerminalToolbarButtonStyle())
        .background(Color(uiColor: .secondarySystemBackground))
    }

    private func key(_ title: String, label: String, action: PiTerminalToolbarAction, metrics: PiTerminalToolbarMetrics) -> some View {
        let latched = action == .control && controlLatched
        return Button { perform(action) } label: {
            Text(title)
                .font(.system(size: 14, weight: .semibold, design: .monospaced))
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .foregroundStyle(latched ? JarvisPalette.onAccent : JarvisPalette.accent)
                .padding(.horizontal, 2)
                .frame(width: metrics.width(for: action), height: 34)
                .background(latched ? JarvisPalette.accent : JarvisPalette.accent.opacity(0.10),
                            in: RoundedRectangle(cornerRadius: 8))
                .frame(height: PiTerminalToolbarMetrics.height)
                .contentShape(Rectangle())
        }
        .disabled(!canSend)
        .accessibilityLabel(label)
    }

    private func icon(_ symbol: String, label: String, action: PiTerminalToolbarAction, metrics: PiTerminalToolbarMetrics) -> some View {
        Button { perform(action) } label: {
            Image(systemName: symbol)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(JarvisPalette.accent)
                .frame(width: metrics.width(for: action), height: PiTerminalToolbarMetrics.height)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(label)
    }
}

// Explicitly fill the parent's proposal. The terminal is not an intrinsic-height
// control: its toolbar must never determine the height of the whole viewport.
struct PiTerminalContainer: UIViewControllerRepresentable {
    let controller: PiTerminalController

    func makeUIViewController(context: Context) -> PiTerminalViewportController {
        PiTerminalViewportController(controller: controller)
    }

    func updateUIViewController(_ uiViewController: PiTerminalViewportController, context: Context) {}

    func sizeThatFits(_ proposal: ProposedViewSize, uiViewController: PiTerminalViewportController, context: Context) -> CGSize? {
        guard let width = proposal.width, let height = proposal.height,
              width.isFinite, height.isFinite else { return nil }
        return CGSize(width: max(0, width), height: max(0, height))
    }

    static func dismantleUIViewController(_ uiViewController: PiTerminalViewportController, coordinator: ()) {
        uiViewController.disconnectView()
    }
}

final class PiTerminalViewportController: UIViewController {
    let terminalView = PiTerminalHostView(frame: .zero)
    let toolbar: UIHostingController<PiTerminalKeyBar>
    private let controller: PiTerminalController
    private var keyboardFrameInScreen: CGRect?

    init(controller: PiTerminalController) {
        self.controller = controller
        toolbar = UIHostingController(rootView: PiTerminalKeyBar(controller: controller))
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        view.clipsToBounds = true
        view.addSubview(terminalView)
        addChild(toolbar)
        // This fixed-height child must not independently avoid the keyboard.
        toolbar.safeAreaRegions = []
        toolbar.view.backgroundColor = .clear
        view.addSubview(toolbar.view)
        toolbar.didMove(toParent: self)
        NotificationCenter.default.addObserver(self, selector: #selector(keyboardChanged(_:)),
            name: UIResponder.keyboardWillChangeFrameNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(keyboardChanged(_:)),
            name: UIResponder.keyboardWillHideNotification, object: nil)
        // Attach exactly once; a keyboard layout change only resizes the existing
        // SwiftTerm view (and its existing SSH PTY), never replaces a session.
        controller.attach(terminalView)
    }

    // Intersect the actual keyboard with this viewport, not a cached keyboard
    // height. If SwiftUI already reduced the viewport this adds no second inset.
    static func contentBottom(bounds: CGRect, safeAreaBottom: CGFloat, keyboard: CGRect?) -> CGFloat {
        let safeBottom = max(0, bounds.height - safeAreaBottom)
        guard let keyboard, !keyboard.isNull, !keyboard.isEmpty,
              keyboard.minY > bounds.minY,
              keyboard.maxY >= bounds.maxY - 1,
              keyboard.intersection(bounds).width >= bounds.width - 1 else { return safeBottom }
        return min(safeBottom, max(0, keyboard.minY - bounds.minY))
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        let keyboard: CGRect? = keyboardFrameInScreen.flatMap { frame in
            guard let window = view.window, let screen = window.windowScene?.screen else { return nil }
            return view.convert(window.convert(frame, from: screen.coordinateSpace), from: window)
        }
        let bottom = Self.contentBottom(bounds: view.bounds,
            safeAreaBottom: view.safeAreaInsets.bottom, keyboard: keyboard)
        let height = min(PiTerminalToolbarMetrics.height, bottom)
        terminalView.frame = CGRect(x: 0, y: 0, width: view.bounds.width, height: max(0, bottom - height))
        toolbar.view.frame = CGRect(x: 0, y: bottom - height, width: view.bounds.width, height: height)
    }

    @objc private func keyboardChanged(_ notification: Notification) {
        keyboardFrameInScreen = notification.name == UIResponder.keyboardWillHideNotification
            ? nil : (notification.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? NSValue)?.cgRectValue
        let duration = (notification.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? NSNumber)?.doubleValue ?? 0
        let curve = (notification.userInfo?[UIResponder.keyboardAnimationCurveUserInfoKey] as? NSNumber)?.uintValue ?? 0
        view.setNeedsLayout()
        UIView.animate(withDuration: duration, delay: 0,
            options: [UIView.AnimationOptions(rawValue: curve << 16), .beginFromCurrentState]) {
            self.view.layoutIfNeeded()
        }
    }

    deinit { NotificationCenter.default.removeObserver(self) }

    func disconnectView() { controller.detach(terminalView) }
}

#Preview {
    let settings = PiTerminalSettings(defaults: UserDefaults(suiteName: "pi-terminal-preview")!)
    return PiTerminalView()
        .environmentObject(AppState())
        .environmentObject(PiTerminalController(settings: settings))
}
