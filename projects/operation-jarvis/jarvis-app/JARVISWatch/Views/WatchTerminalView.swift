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
    @Published private(set) var pendingBackspaceCount = 0
    @Published var controlLatched = false

    private let settings = WatchTerminalSettings()
    private var client: WatchTerminalClient?
    private var pollTask: Task<Void, Never>?
    private var wakeRecoveryTask: Task<Void, Never>?
    private var appIsForeground = false
    private var sceneIsActive = false
    private var isVisible = false
    private var connectionGeneration = 0
    private var successfulPollCount = 0
    private var pendingBackspaceIDs = Set<UUID>()

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
        let resumedFromInactive = appIsForeground && !sceneIsActive
        appIsForeground = true
        sceneIsActive = true

        guard isVisible else { return }
        guard pollTask != nil, client != nil else {
            restartIfNeeded()
            return
        }

        if status == .offline {
            // The normal retry loop may be waiting after a route failure. A
            // foreground wake is an explicit opportunity to retry now.
            restartIfNeeded(preserveLiveStatus: false)
        } else if resumedFromInactive {
            // Keep a healthy URLSession/route instead of flashing orange and
            // rebuilding it for every wrist raise or tap. If watchOS suspended
            // the in-flight long poll and it does not resume, recover once
            // after a bounded grace period while keeping the last frame live.
            scheduleWakeRecovery()
        }
    }

    func sceneDidEnterAlwaysOn() {
        sceneIsActive = false
        wakeRecoveryTask?.cancel()
        wakeRecoveryTask = nil
        guard !appIsForeground else { return }
        appIsForeground = true
        restartIfNeeded()
    }

    func sceneDidEnterBackground() {
        sceneIsActive = false
        appIsForeground = false
        stop()
    }

    func setVisible(_ visible: Bool) {
        isVisible = visible
        if visible {
            if pollTask == nil || client == nil { restartIfNeeded() }
        } else {
            stop()
        }
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

    func sendEnter() {
        controlLatched = false
        send(WatchTerminalKeyBytes.carriageReturn, appendReturn: false)
    }

    /// Backspace remains immediate and repeatable. Each tap attempts one exact
    /// DEL POST without entering the normal input loading state. Concurrent
    /// DEL requests are safe because terminald serializes its tmux writes, and
    /// no request is queued, retried, or replayed by the Watch.
    func sendBackspace() {
        controlLatched = false
        guard appIsForeground, isVisible, status == .live, !isSending, let client else {
            if status != .notConfigured { errorMessage = "The terminal is not connected." }
            return
        }

        let trackingID = UUID()
        pendingBackspaceIDs.insert(trackingID)
        pendingBackspaceCount = pendingBackspaceIDs.count
        let generation = connectionGeneration
        let input = WatchTerminalInput(data: WatchTerminalKeyBytes.backspace, appendReturn: false)
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                self.pendingBackspaceIDs.remove(trackingID)
                self.pendingBackspaceCount = self.pendingBackspaceIDs.count
            }
            do {
                try await client.send(input)
                guard self.connectionGeneration == generation else { return }
                self.errorMessage = nil
            } catch is CancellationError {
                return
            } catch {
                guard self.connectionGeneration == generation else { return }
                self.errorMessage = "Backspace was not confirmed: \(error.localizedDescription)"
            }
        }
    }

    private func restartIfNeeded(preserveLiveStatus: Bool = false) {
        let keepsLiveStatus = preserveLiveStatus && frame != nil && status == .live
        stop(markOffline: !keepsLiveStatus)
        guard appIsForeground, isVisible else { return }
        guard let configuration = settings.configuration else {
            status = .notConfigured
            errorMessage = "Open iPhone JARVIS Settings to provision the Watch terminal."
            return
        }
        let client = WatchTerminalClient(configuration: configuration)
        self.client = client
        status = keepsLiveStatus ? .live : .connecting
        errorMessage = nil
        pollTask = Task { @MainActor [weak self] in
            guard let self else { return }
            var sequence = self.frame?.sequence ?? 0
            while !Task.isCancelled, self.appIsForeground, self.isVisible {
                do {
                    let next = try await client.frame(after: sequence)
                    guard !Task.isCancelled else { return }
                    self.frame = next
                    sequence = next.sequence
                    self.successfulPollCount += 1
                    self.wakeRecoveryTask?.cancel()
                    self.wakeRecoveryTask = nil
                    self.status = .live
                    self.errorMessage = nil
                } catch is CancellationError {
                    return
                } catch {
                    guard !Task.isCancelled else { return }
                    self.wakeRecoveryTask?.cancel()
                    self.wakeRecoveryTask = nil
                    self.status = .offline
                    self.errorMessage = error.localizedDescription
                    try? await Task.sleep(for: .seconds(1))
                }
            }
        }
    }

    private func scheduleWakeRecovery() {
        wakeRecoveryTask?.cancel()
        let generation = connectionGeneration
        let observedPollCount = successfulPollCount
        wakeRecoveryTask = Task { @MainActor [weak self] in
            do {
                // A normal terminald long poll completes in at most 1.5 seconds.
                // Seven seconds also covers the pinned session's resource
                // timeout when a request was frozen during Always On.
                try await Task.sleep(for: .seconds(7))
            } catch {
                return
            }
            guard let self,
                  self.connectionGeneration == generation,
                  self.appIsForeground,
                  self.sceneIsActive,
                  self.isVisible,
                  self.status == .live,
                  self.successfulPollCount == observedPollCount else { return }
            self.restartIfNeeded(preserveLiveStatus: true)
        }
    }

    private func stop(markOffline: Bool = true) {
        connectionGeneration += 1
        wakeRecoveryTask?.cancel()
        wakeRecoveryTask = nil
        pollTask?.cancel()
        pollTask = nil
        client?.close()
        client = nil
        isSending = false
        pendingBackspaceIDs.removeAll()
        pendingBackspaceCount = 0
        if markOffline, settings.configuration != nil, status != .notConfigured { status = .offline }
    }

    private func send(_ data: Data, appendReturn: Bool) {
        guard appIsForeground, isVisible, status == .live, !isSending,
              pendingBackspaceCount == 0, let client else {
            if status != .notConfigured { errorMessage = "The terminal is not connected." }
            return
        }
        isSending = true
        let generation = connectionGeneration
        let input = WatchTerminalInput(data: data, appendReturn: appendReturn)
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if self.connectionGeneration == generation { self.isSending = false }
            }
            do {
                try await client.send(input)
                guard self.connectionGeneration == generation else { return }
                self.errorMessage = nil
            } catch is CancellationError {
                return
            } catch {
                guard self.connectionGeneration == generation else { return }
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
    @State private var keyboardDraft = ""
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

    private var normalInputIsEnabled: Bool {
        controller.status == .live
            && !controller.isSending
            && controller.pendingBackspaceCount == 0
    }

    private var backspaceIsEnabled: Bool {
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
            inputDock
        }
        .padding(.horizontal, 8)
        .padding(.top, 6)
        .padding(.bottom, 8)
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
            .gesture(
                DragGesture(minimumDistance: 24).onEnded { value in
                    guard value.translation.height < -60,
                          abs(value.translation.height) > abs(value.translation.width),
                          let onAdvancePage else { return }
                    // Touch remains page navigation only. Terminal history is
                    // controlled exclusively by the focused Digital Crown.
                    onAdvancePage()
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
        let defaultForeground = Color(red: 0.94, green: 0.94, blue: 0.94)
        let defaultBackground = Color.black
        let rawForeground = terminalForegroundColor(span.style.foreground, defaultColor: defaultForeground)
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
            .foregroundStyle(foreground.opacity(span.style.dim ? 0.82 : 1))
            .background(background)
            .fixedSize(horizontal: true, vertical: false)
    }

    private func terminalForegroundColor(_ color: WatchTerminalANSIColor, defaultColor: Color) -> Color {
        guard case .rgb(let value) = color else { return defaultColor }
        let brightened = WatchTerminalLayout.brightenedForeground(value)
        return Color(
            red: Double(brightened.red) / 255,
            green: Double(brightened.green) / 255,
            blue: Double(brightened.blue) / 255
        )
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
        ZStack(alignment: .top) {
            Text("JARVIS")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, alignment: .center)
                .accessibilityAddTraits(.isHeader)

            HStack(spacing: 5) {
                Image(systemName: "terminal.fill")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Color.cyan)
                    .accessibilityHidden(true)
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
                        .padding(.horizontal, 6)
                        .frame(minWidth: 36)
                        .frame(height: 21)
                        .background(Color.black.opacity(0.82), in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Terminal display mode")
                .accessibilityValue(displayMode == .fit ? "Fit mirrored grid" : "Full-size mirrored grid")
                .accessibilityHint("Double tap to switch mirror sizes")
            }
            .padding(.leading, 7)
            .padding(.trailing, 14)
        }
        .padding(.top, 2)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    private var inputDock: some View {
        HStack(spacing: 3) {
            Button {
                showingKeyPalette.toggle()
            } label: {
                dockLabel(symbol: showingKeyPalette ? "xmark" : "command", title: "Keys", emphasized: false)
            }
            .buttonStyle(.plain)
            .disabled(!normalInputIsEnabled)
            .accessibilityLabel(showingKeyPalette ? "Hide terminal keys" : "Show terminal keys")

            TextField("", text: $keyboardDraft, prompt: Text("Input").foregroundStyle(Color.clear))
                .textFieldStyle(.plain)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .submitLabel(.done)
                .onSubmit {
                    stageInput(keyboardDraft)
                    keyboardDraft = ""
                }
                .overlay {
                    dockLabel(symbol: "keyboard", title: "Input", emphasized: false)
                        .allowsHitTesting(false)
                }
                .frame(maxWidth: .infinity, minHeight: 35)
                .background(Color.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .disabled(!normalInputIsEnabled)
                .accessibilityLabel("Input text at the Pi cursor")
                .accessibilityHint("Opens the Apple Watch keyboard first. Text is inserted without submitting.")

            Button {
                controller.sendKey(WatchTerminalKeyBytes.slash)
            } label: {
                Text("/")
                    .font(.system(size: 15, weight: .bold, design: .monospaced))
                    .foregroundStyle(Color.cyan)
                    .frame(width: 28, height: 35)
                    .background(Color.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(!normalInputIsEnabled)
            .accessibilityLabel("Slash")
            .accessibilityHint("Inserts one slash at the Pi cursor.")

            Button {
                controller.sendBackspace()
            } label: {
                Image(systemName: "delete.backward.fill")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color.cyan)
                    .frame(width: 28, height: 35)
                    .background(Color.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(!backspaceIsEnabled)
            .accessibilityLabel("Backspace current Pi input")
            .accessibilityHint("Sends one immediate delete without showing a loading indicator.")

            Button {
                showingKeyPalette = false
                controller.sendEnter()
            } label: {
                Image(systemName: "return")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color.black)
                    .frame(width: 28, height: 35)
                    .background(Color.cyan, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(!normalInputIsEnabled)
            .accessibilityLabel("Enter current Pi input")
            .accessibilityHint("Sends one terminal Return byte to submit at the Pi cursor.")
        }
        .frame(height: 39)
    }

    private func stageInput(_ input: String) {
        let message = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else { return }
        controller.sendText(message, appendReturn: false)
    }

    private func dockLabel(symbol: String, title: String, emphasized: Bool) -> some View {
        HStack(spacing: 2) {
            Image(systemName: symbol)
                .font(.system(size: emphasized ? 12 : 10, weight: .bold))
            Text(title)
                .font(.system(size: emphasized ? 9 : 8, weight: .bold))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
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
        .disabled(
            controller.status != .live
                || controller.isSending
                || controller.pendingBackspaceCount > 0
        )
        .accessibilityLabel(accessibility)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
