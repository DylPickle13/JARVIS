import Foundation
import JARVISKit
import SwiftUI

@MainActor
private final class WatchTerminalSettings {
    #if DEBUG && targetEnvironment(simulator)
    private var simulatorConfiguration: WatchTerminalConfiguration?
    #endif

    var configuration: WatchTerminalConfiguration? {
        #if DEBUG && targetEnvironment(simulator)
        if let simulatorConfiguration { return simulatorConfiguration }
        #endif
        guard case .configured(let configuration) = JARVISTerminalConfigurationStore.load() else {
            return nil
        }
        return configuration
    }

    @discardableResult
    func save(_ configuration: WatchTerminalConfiguration) -> Bool {
        guard configuration.isValid else { return false }
        #if DEBUG && targetEnvironment(simulator)
        simulatorConfiguration = configuration
        return true
        #else
        return JARVISTerminalConfigurationStore.save(configuration)
        #endif
    }
}

@MainActor
final class WatchTerminalController: ObservableObject {
    enum Status: Equatable {
        case notConfigured
        case connecting
        case live
        case offline

        var label: String {
            switch self {
            case .notConfigured: return "SET UP ON IPHONE"
            case .connecting: return "CONNECTING"
            case .live: return "LIVE"
            case .offline: return "OFFLINE"
            }
        }

        var color: Color {
            switch self {
            case .notConfigured: return .orange
            case .connecting: return .orange
            case .live: return .green
            case .offline: return .red
            }
        }
    }

    @Published private(set) var frame: WatchTerminalFrame?
    @Published private(set) var status: Status
    @Published private(set) var errorMessage: String?
    @Published private(set) var isSending = false
    @Published var controlLatched = false

    private let settings = WatchTerminalSettings()
    private var client: WatchTerminalClient?
    private var pollTask: Task<Void, Never>?
    private var appIsActive = false
    private var isVisible = false

    init() {
        #if DEBUG && targetEnvironment(simulator)
        let arguments = CommandLine.arguments
        if let index = arguments.firstIndex(of: "-jarvisSeedWatchTerminal"), index + 1 < arguments.count,
           let configuration = WatchTerminalConfiguration.fromProvisioningCode(arguments[index + 1]) {
            settings.save(configuration)
        }
        #endif
        status = settings.configuration == nil ? .notConfigured : .offline
    }

    func apply(configuration: WatchTerminalConfiguration) {
        guard settings.save(configuration) else {
            errorMessage = "Could not save the Watch terminal setup."
            return
        }
        restartIfNeeded()
    }

    func sceneDidBecomeActive() {
        appIsActive = true
        restartIfNeeded()
    }

    func sceneWillResignActive() {
        appIsActive = false
        stop()
    }

    func setVisible(_ visible: Bool) {
        isVisible = visible
        if visible { restartIfNeeded() } else { stop() }
    }

    func sendText(_ text: String, appendReturn: Bool = true) {
        let bytes = Data(text.utf8)
        guard !bytes.isEmpty else { return }
        if controlLatched {
            guard bytes.count == 1, let byte = bytes.first,
                  let control = WatchTerminalKeyBytes.control(byte) else {
                errorMessage = "Ctrl requires one ASCII character."
                return
            }
            controlLatched = false
            send(control, appendReturn: false)
        } else {
            send(bytes, appendReturn: appendReturn)
        }
    }

    func sendKey(_ bytes: Data) {
        if controlLatched, bytes.count == 1, let byte = bytes.first,
           let control = WatchTerminalKeyBytes.control(byte) {
            controlLatched = false
            send(control, appendReturn: false)
            return
        }
        controlLatched = false
        send(bytes, appendReturn: false)
    }

    private func restartIfNeeded() {
        stop()
        guard appIsActive, isVisible else { return }
        guard let configuration = settings.configuration else {
            status = .notConfigured
            errorMessage = "Open iPhone JARVIS Settings to provision the Watch terminal."
            return
        }
        let client = WatchTerminalClient(configuration: configuration)
        self.client = client
        status = .connecting
        errorMessage = nil
        pollTask = Task { @MainActor [weak self] in
            guard let self else { return }
            var sequence = self.frame?.sequence ?? 0
            while !Task.isCancelled, self.appIsActive, self.isVisible {
                do {
                    let next = try await client.frame(after: sequence)
                    guard !Task.isCancelled else { return }
                    self.frame = next
                    sequence = next.sequence
                    self.status = .live
                    self.errorMessage = nil
                } catch is CancellationError {
                    return
                } catch {
                    guard !Task.isCancelled else { return }
                    self.status = .offline
                    self.errorMessage = error.localizedDescription
                    try? await Task.sleep(for: .seconds(1))
                }
            }
        }
    }

    private func stop() {
        pollTask?.cancel()
        pollTask = nil
        client?.close()
        client = nil
        isSending = false
        if settings.configuration != nil, status != .notConfigured { status = .offline }
    }

    private func send(_ data: Data, appendReturn: Bool) {
        guard appIsActive, isVisible, status == .live, !isSending, let client else {
            if status != .notConfigured { errorMessage = "The terminal is not connected." }
            return
        }
        isSending = true
        let input = WatchTerminalInput(data: data, appendReturn: appendReturn)
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.isSending = false }
            do {
                try await client.send(input)
                self.errorMessage = nil
            } catch {
                self.errorMessage = "Input was not confirmed: \(error.localizedDescription)"
            }
        }
    }
}

private enum WatchTerminalDisplayMode: String {
    case fit
    case grid
}

struct WatchTerminalView: View {
    @ObservedObject var controller: WatchTerminalController
    let isActive: Bool
    let onAdvancePage: (() -> Void)?
    @AppStorage("jarvis.watch-terminal.display-mode") private var displayModeRaw = WatchTerminalDisplayMode.fit.rawValue
    @State private var showingKeyPalette = false
    @State private var crownPosition = 0.0
    @State private var scrollOffset = 0
    @FocusState private var crownIsFocused: Bool

    private var displayMode: WatchTerminalDisplayMode {
        get {
            if displayModeRaw == "raw" { return .grid }
            if displayModeRaw == "readable" { return .fit }
            return WatchTerminalDisplayMode(rawValue: displayModeRaw) ?? .fit
        }
        nonmutating set { displayModeRaw = newValue.rawValue }
    }

    private var inputIsEnabled: Bool {
        controller.status == .live && !controller.isSending
    }

    init(
        controller: WatchTerminalController,
        isActive: Bool = true,
        onAdvancePage: (() -> Void)? = nil
    ) {
        self.controller = controller
        self.isActive = isActive
        self.onAdvancePage = onAdvancePage
    }

    var body: some View {
        VStack(spacing: 2) {
            terminal
            promptRail
            inputDock
        }
        .padding(.horizontal, 2)
        .padding(.bottom, 2)
        .background(Color.black.ignoresSafeArea())
        .overlay(alignment: .bottom) {
            if showingKeyPalette {
                keyPalette
                    .padding(.horizontal, 3)
                    .padding(.bottom, 42)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.16), value: showingKeyPalette)
        .focusable(isActive)
        .focused($crownIsFocused)
        .digitalCrownRotation(
            $crownPosition,
            from: -100_000,
            through: 100_000,
            by: 1,
            sensitivity: .medium,
            isContinuous: true,
            isHapticFeedbackEnabled: true
        )
        .onChange(of: crownPosition) { oldValue, newValue in
            guard newValue != oldValue else { return }
            let steps = max(1, min(8, Int(abs(newValue - oldValue).rounded())))
            adjustScroll(towardHistory: newValue < oldValue, steps: steps)
        }
        .onAppear {
            controller.setVisible(isActive)
            crownIsFocused = isActive
        }
        .onChange(of: isActive) { _, active in
            controller.setVisible(active)
            crownIsFocused = active
        }
        .onDisappear {
            crownIsFocused = false
            controller.setVisible(false)
        }
    }

    private var terminal: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                Color(red: 0.008, green: 0.022, blue: 0.028)

                if let frame = controller.frame {
                    mirroredTerminal(frame: frame, geometry: geometry, fitToWidth: displayMode == .fit)
                } else {
                    waitingTerminal
                }

                terminalStatusOverlay
            }
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
            .contentShape(Rectangle())
            .simultaneousGesture(
                DragGesture(minimumDistance: 12).onEnded { value in
                    guard abs(value.translation.height) > abs(value.translation.width) else { return }
                    if value.translation.height < -60, scrollOffset == 0, let onAdvancePage {
                        onAdvancePage()
                    } else {
                        let steps = max(1, min(12, Int(abs(value.translation.height) / 12)))
                        adjustScroll(towardHistory: value.translation.height > 0, steps: steps)
                    }
                }
            )
        }
    }

    private func mirroredTerminal(
        frame: WatchTerminalFrame,
        geometry: GeometryProxy,
        fitToWidth: Bool
    ) -> some View {
        let contentWidth = max(1, geometry.size.width - 10)
        let fontSize = CGFloat(
            fitToWidth
                ? WatchTerminalLayout.mirrorFontSize(
                    availableWidth: Double(contentWidth),
                    terminalColumns: frame.columns
                )
                : WatchTerminalLayout.rawFontSize
        )
        let lineHeight = CGFloat(WatchTerminalLayout.lineHeight(fontSize: Double(fontSize)))
        let maximumLines = max(1, Int(max(0, geometry.size.height - 29) / lineHeight))
        let safeOffset = min(scrollOffset, frame.maximumScrollOffset(maximumLines: maximumLines))
        let visibleRange = frame.viewportRange(maximumLines: maximumLines, scrollOffset: safeOffset)
        let mirroredStyles = WatchTerminalANSIParser.parse(lines: frame.ansiLines)
        let styledLines = Array(mirroredStyles[visibleRange])
        let terminalWidth = max(
            contentWidth,
            CGFloat(frame.columns) * fontSize * CGFloat(WatchTerminalLayout.monospacedCharacterWidthRatio)
        )

        return ScrollView(.horizontal, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(styledLines.enumerated()), id: \.offset) { _, spans in
                    HStack(spacing: 0) {
                        ForEach(Array(spans.enumerated()), id: \.offset) { _, span in
                            terminalSpan(span, fontSize: fontSize)
                        }
                    }
                    .frame(width: terminalWidth, height: lineHeight, alignment: .leading)
                    .clipped()
                }
            }
            .padding(.horizontal, 5)
        }
        .contentMargins(.top, 25, for: .scrollContent)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityLabel("Mirrored Pi terminal")
        .accessibilityValue(safeOffset == 0 ? "Live" : "Scrolled back \(safeOffset) rows")
        .task(id: safeOffset) {
            if scrollOffset != safeOffset { scrollOffset = safeOffset }
        }
    }

    private func terminalSpan(_ span: WatchTerminalANSISpan, fontSize: CGFloat) -> some View {
        let defaultForeground = Color(red: 0.83, green: 0.83, blue: 0.83)
        let defaultBackground = Color.black
        let rawForeground = terminalColor(span.style.foreground, defaultColor: defaultForeground)
        let rawBackground = terminalColor(span.style.background, defaultColor: defaultBackground)
        let foreground = span.style.inverse ? rawBackground : rawForeground
        let background = span.style.inverse ? rawForeground : rawBackground
        let visibleText = span.style.hidden
            ? String(repeating: " ", count: span.text.count)
            : span.text
        var text = Text(verbatim: visibleText)
            .font(.system(
                size: fontSize,
                weight: span.style.bold ? .bold : .regular,
                design: .monospaced
            ))
        if span.style.italic { text = text.italic() }
        if span.style.underline { text = text.underline() }
        if span.style.strikethrough { text = text.strikethrough() }
        return text
            .foregroundStyle(foreground.opacity(span.style.dim ? 0.62 : 1))
            .background(background)
            .fixedSize(horizontal: true, vertical: false)
    }

    private func terminalColor(_ color: WatchTerminalANSIColor, defaultColor: Color) -> Color {
        guard case .rgb(let value) = color else { return defaultColor }
        return Color(
            red: Double(value.red) / 255,
            green: Double(value.green) / 255,
            blue: Double(value.blue) / 255
        )
    }

    private func adjustScroll(towardHistory: Bool, steps: Int) {
        guard let frame = controller.frame else { return }
        if towardHistory {
            scrollOffset = min(frame.lines.count, scrollOffset + max(1, steps))
        } else {
            scrollOffset = max(0, scrollOffset - max(1, steps))
        }
        crownIsFocused = true
    }

    private var waitingTerminal: some View {
        VStack(spacing: 7) {
            if controller.status == .connecting { ProgressView().controlSize(.small) }
            Text(controller.errorMessage ?? "Waiting for the Mac terminal")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 12)
        .padding(.top, 20)
    }

    private var terminalStatusOverlay: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(controller.status.color)
                .frame(width: 7, height: 7)
                .accessibilityLabel("Terminal status")
                .accessibilityValue(controller.status.label)
            if scrollOffset > 0 {
                Text("↑\(scrollOffset)")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundStyle(Color.cyan)
                    .accessibilityLabel("Scrolled back \(scrollOffset) terminal rows")
            }
            Spacer(minLength: 0)
            Button {
                displayMode = displayMode == .fit ? .grid : .fit
                crownIsFocused = true
            } label: {
                Text(displayMode == .fit ? "FIT" : "GRID")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundStyle(displayMode == .fit ? Color.cyan : Color.secondary)
                    .padding(.horizontal, 7)
                    .frame(height: 21)
                    .background(Color.black.opacity(0.82), in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Terminal display mode")
            .accessibilityValue(displayMode == .fit ? "Fit mirrored grid" : "Full-size mirrored grid")
            .accessibilityHint("Double tap to switch mirror sizes")
        }
        .padding(.horizontal, 6)
        .padding(.top, 2)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    private var promptRail: some View {
        GeometryReader { geometry in
            let contentWidth = max(1, geometry.size.width - 34)
            let columns = WatchTerminalLayout.displayColumns(
                availableWidth: Double(contentWidth),
                fontSize: WatchTerminalLayout.promptFontSize
            )
            let prompt = controller.frame?.promptViewport(displayColumns: columns) ?? "Waiting for Pi input"

            HStack(spacing: 5) {
                Image(systemName: "chevron.right")
                    .font(.system(size: 8, weight: .black))
                    .foregroundStyle(Color.cyan)
                Text(verbatim: prompt)
                    .font(.system(size: CGFloat(WatchTerminalLayout.promptFontSize), weight: .semibold, design: .monospaced))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .clipped()
                if controller.isSending {
                    ProgressView().controlSize(.mini)
                }
            }
            .padding(.horizontal, 7)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.cyan.opacity(0.10), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Current Pi input")
            .accessibilityValue(prompt)
        }
        .frame(height: 27)
    }

    private var inputDock: some View {
        HStack(spacing: 3) {
            Button {
                showingKeyPalette.toggle()
            } label: {
                dockLabel(symbol: showingKeyPalette ? "xmark" : "command", title: "Keys", emphasized: false)
            }
            .buttonStyle(.plain)
            .disabled(!inputIsEnabled)
            .accessibilityLabel(showingKeyPalette ? "Hide terminal keys" : "Show terminal keys")

            TextFieldLink(prompt: Text("Message JARVIS")) {
                dockLabel(symbol: "keyboard", title: "Input", emphasized: false)
            } onSubmit: { input in
                stageInput(input)
            }
            .buttonStyle(.plain)
            .disabled(!inputIsEnabled)
            .accessibilityLabel("Input text at the Pi cursor")
            .accessibilityHint("Opens Apple Watch keyboard with microphone input. Text is inserted without submitting.")

            Button {
                showingKeyPalette = false
                controller.sendKey(WatchTerminalKeyBytes.carriageReturn)
            } label: {
                dockLabel(symbol: "paperplane.fill", title: "Send", emphasized: true)
            }
            .buttonStyle(.plain)
            .disabled(!inputIsEnabled)
            .accessibilityLabel("Send current Pi input")
            .accessibilityHint("Sends Return to submit the text at the Pi cursor.")
        }
        .frame(height: 39)
    }

    private func stageInput(_ input: String) {
        let message = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else { return }
        Task { @MainActor in
            controller.sendText(message, appendReturn: false)
        }
    }

    private func dockLabel(symbol: String, title: String, emphasized: Bool) -> some View {
        HStack(spacing: 4) {
            Image(systemName: symbol)
                .font(.system(size: emphasized ? 13 : 11, weight: .bold))
            Text(title)
                .font(.system(size: emphasized ? 10 : 9, weight: .bold))
        }
        .foregroundStyle(emphasized ? Color.black : Color.primary)
        .frame(maxWidth: .infinity, minHeight: 35)
        .background(
            emphasized ? Color.cyan : Color.white.opacity(0.09),
            in: RoundedRectangle(cornerRadius: 8, style: .continuous)
        )
    }

    private var keyPalette: some View {
        VStack(spacing: 3) {
            HStack(spacing: 3) {
                terminalKey("Esc", accessibility: "Escape") { controller.sendKey(WatchTerminalKeyBytes.escape) }
                terminalKey("Ctrl", accessibility: "Control modifier", selected: controller.controlLatched) {
                    controller.controlLatched.toggle()
                }
                terminalKey("Tab", accessibility: "Tab") { controller.sendKey(WatchTerminalKeyBytes.tab) }
            }
            HStack(spacing: 3) {
                terminalKey("/", accessibility: "Slash") { controller.sendKey(WatchTerminalKeyBytes.slash) }
                terminalKey("↑", accessibility: "Up arrow") { controller.sendKey(WatchTerminalKeyBytes.up) }
                terminalKey("↓", accessibility: "Down arrow") { controller.sendKey(WatchTerminalKeyBytes.down) }
            }
        }
        .padding(5)
        .background(Color.black.opacity(0.96), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.cyan.opacity(0.24), lineWidth: 1)
        }
    }

    private func terminalKey(
        _ title: String,
        accessibility: String,
        selected: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: title.count > 2 ? 9 : 12, weight: .bold, design: .monospaced))
                .frame(maxWidth: .infinity, minHeight: 28)
                .background(selected ? Color.cyan.opacity(0.35) : Color.white.opacity(0.10), in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .disabled(controller.status != .live || controller.isSending)
        .accessibilityLabel(accessibility)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
