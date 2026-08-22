import CryptoKit
import Foundation
import JARVISKit
import Security
import SwiftUI

private enum WatchTerminalError: LocalizedError {
    case notConfigured
    case invalidResponse
    case rejected(String)
    case certificateRejected

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "Set up the Watch terminal from iPhone Settings."
        case .invalidResponse: return "The terminal bridge returned an invalid response."
        case .rejected(let message): return message
        case .certificateRejected: return "The Mac terminal certificate did not match."
        }
    }
}

private final class WatchTerminalPinnedSessionDelegate: NSObject, URLSessionDelegate, @unchecked Sendable {
    private let expectedFingerprint: String

    init(expectedFingerprint: String) {
        self.expectedFingerprint = WatchTerminalConfiguration.normalizeFingerprint(expectedFingerprint)
    }

    func urlSession(
        _ session: URLSession,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let leaf = chain.first else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        let digest = SHA256.hash(data: SecCertificateCopyData(leaf) as Data)
        let actual = digest.map { String(format: "%02x", $0) }.joined()
        guard actual == expectedFingerprint else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
}

private final class WatchTerminalHTTPClient: @unchecked Sendable {
    private let configuration: WatchTerminalConfiguration
    private let delegate: WatchTerminalPinnedSessionDelegate
    private let session: URLSession
    private let candidateBaseURLs: [URL]
    private let endpointLock = NSLock()
    private var activeBaseURL: URL?

    init(configuration: WatchTerminalConfiguration) {
        self.configuration = configuration
        self.candidateBaseURLs = configuration.candidateBaseURLs
        self.delegate = WatchTerminalPinnedSessionDelegate(expectedFingerprint: configuration.certificateSHA256)
        let sessionConfiguration = URLSessionConfiguration.ephemeral
        sessionConfiguration.timeoutIntervalForRequest = 4
        sessionConfiguration.timeoutIntervalForResource = 6
        sessionConfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.session = URLSession(configuration: sessionConfiguration, delegate: delegate, delegateQueue: nil)
    }

    func close() {
        session.invalidateAndCancel()
    }

    func frame(after sequence: Int) async throws -> WatchTerminalFrame {
        var lastError: Error = WatchTerminalError.notConfigured
        for baseURL in orderedBaseURLs() {
            if Task.isCancelled { throw CancellationError() }
            do {
                var components = try endpointComponents(baseURL: baseURL, path: "v1/terminal/frame")
                components.queryItems = [URLQueryItem(name: "after", value: String(sequence))]
                guard let url = components.url else { throw WatchTerminalError.notConfigured }
                var request = URLRequest(url: url)
                request.httpMethod = "GET"
                authorize(&request)
                let (data, response) = try await session.data(for: request)
                try validate(response: response, data: data)
                guard let frame = try? JSONDecoder().decode(WatchTerminalFrame.self, from: data) else {
                    throw WatchTerminalError.invalidResponse
                }
                rememberActive(baseURL)
                return frame
            } catch let error as URLError where error.code == .cancelled {
                throw CancellationError()
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                lastError = error
            }
        }
        throw lastError
    }

    func send(_ input: WatchTerminalInput) async throws {
        // Input is immediate-only and is never replayed across endpoints. A
        // successful frame chooses the active route before controls are enabled.
        guard let baseURL = preferredBaseURL() else { throw WatchTerminalError.notConfigured }
        let components = try endpointComponents(baseURL: baseURL, path: "v1/terminal/input")
        guard let url = components.url else { throw WatchTerminalError.notConfigured }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        authorize(&request)
        request.httpBody = try JSONEncoder().encode(input)
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
    }

    private func preferredBaseURL() -> URL? {
        endpointLock.lock()
        defer { endpointLock.unlock() }
        return activeBaseURL ?? candidateBaseURLs.first
    }

    private func orderedBaseURLs() -> [URL] {
        endpointLock.lock()
        let active = activeBaseURL
        endpointLock.unlock()
        guard let active else { return candidateBaseURLs }
        return [active] + candidateBaseURLs.filter { $0 != active }
    }

    private func rememberActive(_ baseURL: URL) {
        endpointLock.lock()
        activeBaseURL = baseURL
        endpointLock.unlock()
    }

    private func endpointComponents(baseURL: URL, path: String) throws -> URLComponents {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: true) else {
            throw WatchTerminalError.notConfigured
        }
        return components
    }

    private func authorize(_ request: inout URLRequest) {
        request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw WatchTerminalError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            let message = object?["error"] as? String ?? "Terminal bridge rejected the request."
            throw WatchTerminalError.rejected(message)
        }
    }
}

@MainActor
private final class WatchTerminalSettings {
    private let defaults = UserDefaults.standard
    private let endpointKey = "jarvis.watch-terminal.endpoint"
    private let fingerprintKey = "jarvis.watch-terminal.certificate-sha256"
    private let keychainService = "com.operation-jarvis.jarvis.watchkitapp.watch-terminal"
    private let tokenAccount = "bridge.token"
    #if DEBUG && targetEnvironment(simulator)
    private var simulatorConfiguration: WatchTerminalConfiguration?
    #endif

    var configuration: WatchTerminalConfiguration? {
        #if DEBUG && targetEnvironment(simulator)
        if let simulatorConfiguration { return simulatorConfiguration }
        #endif
        guard let token = readToken() else { return nil }
        let configuration = WatchTerminalConfiguration(
            endpoint: defaults.string(forKey: endpointKey) ?? "",
            token: token,
            certificateSHA256: defaults.string(forKey: fingerprintKey) ?? ""
        )
        return configuration.isValid ? configuration : nil
    }

    @discardableResult
    func save(_ configuration: WatchTerminalConfiguration) -> Bool {
        guard configuration.isValid else { return false }
        #if DEBUG && targetEnvironment(simulator)
        simulatorConfiguration = configuration
        #else
        guard writeToken(configuration.token) else { return false }
        #endif
        defaults.set(configuration.endpoint, forKey: endpointKey)
        defaults.set(configuration.certificateSHA256, forKey: fingerprintKey)
        return true
    }

    private func writeToken(_ token: String) -> Bool {
        guard let data = token.data(using: .utf8) else { return false }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: tokenAccount,
        ]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }

    private func readToken() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: tokenAccount,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
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
    private var client: WatchTerminalHTTPClient?
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

    func sendWheel(scrollingUp: Bool) {
        let column = (frame?.cursorColumn ?? 0) + 1
        let row = (frame?.cursorRow ?? 0) + 1
        send(WatchTerminalKeyBytes.wheel(scrollingUp: scrollingUp, column: column, row: row), appendReturn: false)
    }

    private func restartIfNeeded() {
        stop()
        guard appIsActive, isVisible else { return }
        guard let configuration = settings.configuration else {
            status = .notConfigured
            errorMessage = "Open iPhone JARVIS Settings to provision the Watch terminal."
            return
        }
        let client = WatchTerminalHTTPClient(configuration: configuration)
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

struct WatchTerminalView: View {
    @ObservedObject var controller: WatchTerminalController
    let isActive: Bool
    let onAdvancePage: (() -> Void)?
    @State private var showingComposer = false
    @State private var draft = ""
    @State private var crownPosition = 0.0

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
        VStack(spacing: 4) {
            header
            terminal
            keyDeck
        }
        .padding(.horizontal, 4)
        .padding(.bottom, 3)
        .background(Color.black.ignoresSafeArea())
        .focusable()
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
            controller.sendWheel(scrollingUp: newValue < oldValue)
        }
        .onAppear { controller.setVisible(isActive) }
        .onChange(of: isActive) { _, active in controller.setVisible(active) }
        .onDisappear { controller.setVisible(false) }
        .sheet(isPresented: $showingComposer) { composer }
    }

    private var header: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(controller.status.color)
                .frame(width: 6, height: 6)
            Text(controller.status.label)
                .font(.system(size: 8, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
            Spacer(minLength: 2)
            Button {
                showingComposer = true
            } label: {
                Image(systemName: "text.cursor")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(Color.cyan)
                    .frame(width: 26, height: 26)
                    .background(Color.cyan.opacity(0.14), in: Circle())
            }
            .buttonStyle(.plain)
            .disabled(controller.status != .live)
            .accessibilityLabel("Type a JARVIS command")
        }
        .frame(height: 24)
    }

    private var terminal: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color(red: 0.015, green: 0.035, blue: 0.045))
                if let frame = controller.frame {
                    let contentWidth = max(1, geometry.size.width - 10)
                    let fontSize = CGFloat(WatchTerminalLayout.fontSize(
                        columns: frame.columns,
                        availableWidth: Double(contentWidth)
                    ))
                    let lineHeight = CGFloat(WatchTerminalLayout.lineHeight(fontSize: Double(fontSize)))
                    let maximumLines = max(1, Int(max(0, geometry.size.height - 10) / lineHeight))
                    let visibleLines = frame.visibleLines(maximumLines: maximumLines)

                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(visibleLines.enumerated()), id: \.offset) { _, line in
                            Text(verbatim: line)
                                .font(.system(size: fontSize, weight: .regular, design: .monospaced))
                                .foregroundStyle(Color(red: 0.72, green: 0.95, blue: 1.0))
                                .lineLimit(1)
                                .truncationMode(.tail)
                                .frame(maxWidth: .infinity, minHeight: lineHeight, maxHeight: lineHeight, alignment: .leading)
                                .clipped()
                        }
                    }
                    .padding(5)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                } else {
                    VStack(spacing: 5) {
                        if controller.status == .connecting { ProgressView().controlSize(.small) }
                        Text(controller.errorMessage ?? "Waiting for the Mac terminal")
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .padding(8)
                }
            }
            .clipped()
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 12).onEnded { value in
                    guard abs(value.translation.height) > abs(value.translation.width) else { return }
                    if value.translation.height < -60, let onAdvancePage {
                        onAdvancePage()
                    } else {
                        controller.sendWheel(scrollingUp: value.translation.height > 0)
                    }
                }
            )
        }
    }

    private var keyDeck: some View {
        HStack(spacing: 2) {
            terminalKey("Esc", accessibility: "Escape") { controller.sendKey(WatchTerminalKeyBytes.escape) }
            terminalKey("Ctrl", accessibility: "Control modifier", selected: controller.controlLatched) {
                controller.controlLatched.toggle()
            }
            terminalKey("Tab", accessibility: "Tab") { controller.sendKey(WatchTerminalKeyBytes.tab) }
            terminalKey("/", accessibility: "Slash") { controller.sendKey(WatchTerminalKeyBytes.slash) }
            terminalKey("↑", accessibility: "Up arrow") { controller.sendKey(WatchTerminalKeyBytes.up) }
            terminalKey("↓", accessibility: "Down arrow") { controller.sendKey(WatchTerminalKeyBytes.down) }
        }
        .frame(height: 25)
    }

    private func terminalKey(
        _ title: String,
        accessibility: String,
        selected: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: title.count > 2 ? 7 : 10, weight: .bold, design: .monospaced))
                .frame(maxWidth: .infinity, minHeight: 21)
                .background(selected ? Color.cyan.opacity(0.35) : Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 5))
        }
        .buttonStyle(.plain)
        .disabled(controller.status != .live || controller.isSending)
        .accessibilityLabel(accessibility)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var composer: some View {
        NavigationStack {
            VStack(spacing: 10) {
                TextField("Message JARVIS", text: $draft)
                Button {
                    let message = draft
                    draft = ""
                    showingComposer = false
                    controller.sendText(message)
                } label: {
                    Label(controller.controlLatched ? "Send Ctrl key" : "Send", systemImage: "paperplane.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(draft.isEmpty)
            }
            .padding()
            .navigationTitle("JARVIS Input")
        }
    }
}
