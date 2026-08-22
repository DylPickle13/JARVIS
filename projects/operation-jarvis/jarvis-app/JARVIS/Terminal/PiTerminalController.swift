import Combine
import Foundation
import Network

@MainActor
enum PiTerminalConnectionStatus: Equatable {
    case idle
    case connecting
    case connected
    case failed(String)
}

@MainActor
final class PiTerminalController: ObservableObject {
    @Published private(set) var status: PiTerminalConnectionStatus = .idle
    @Published private(set) var pendingHostTrust: PiPendingHostTrust?
    @Published private(set) var isControlLatched = false

    let settings: PiTerminalSettings

    private weak var terminalView: PiTerminalHostView?
    private var isVisible = false
    private var appIsActive = false
    private var fallbackHost: String?
    private var pathMonitor: NWPathMonitor?
    private var networkAvailable = true

    init(settings: PiTerminalSettings) {
        self.settings = settings
        startPathMonitor()
    }

    deinit {
        pathMonitor?.cancel()
    }

    func attach(_ view: PiTerminalHostView) {
        terminalView = view
        view.stateChanged = { [weak self] newStatus in
            Task { @MainActor [weak self] in
                self?.status = newStatus
            }
        }
        view.controlLatchChanged = { [weak self] latched in
            Task { @MainActor [weak self] in self?.isControlLatched = latched }
        }
        view.hostTrustRequested = { [weak self] request in
            Task { @MainActor [weak self] in
                guard let self else {
                    request.reject()
                    return
                }
#if DEBUG && targetEnvironment(simulator)
                if CommandLine.arguments.contains("-jarvisAutoTrustSSHHost") {
                    self.settings.trustHostKey(request.publicKey, host: request.host, port: request.port)
                    request.accept()
                    return
                }
#endif
                self.pendingHostTrust = request
            }
        }
        maybeConnect()
    }

    func detach(_ view: PiTerminalHostView) {
        guard terminalView === view else { return }
        view.disconnectSSH()
        terminalView = nil
        pendingHostTrust?.reject()
        pendingHostTrust = nil
        status = .idle
        isControlLatched = false
    }

    func sendTerminalBytes(_ bytes: [UInt8]) {
        terminalView?.sendAccessoryBytes(bytes)
    }

    func toggleControlLatch() {
        terminalView?.toggleControlLatch()
    }

    func pasteIntoTerminal() {
        terminalView?.paste(nil)
    }

    func hideTerminalKeyboard() {
        _ = terminalView?.resignFirstResponder()
    }

    func focusTerminal() {
        _ = terminalView?.becomeFirstResponder()
    }

    func setVisible(_ visible: Bool, fallbackHost: String?) {
        isVisible = visible
        self.fallbackHost = fallbackHost
        if visible {
            maybeConnect()
        } else {
            pendingHostTrust?.reject()
            pendingHostTrust = nil
            terminalView?.disconnectSSH()
            status = .idle
        }
    }

    func sceneDidBecomeActive() {
        appIsActive = true
        maybeConnect(force: status.isFailure)
    }

    func sceneWillResignActive() {
        appIsActive = false
        pendingHostTrust?.reject()
        pendingHostTrust = nil
        terminalView?.disconnectSSH()
        status = .idle
    }

    func retry() {
        maybeConnect(force: true)
    }

    func reconnectAfterSettingsChange(fallbackHost: String?) {
        self.fallbackHost = fallbackHost
        pendingHostTrust?.reject()
        pendingHostTrust = nil
        terminalView?.disconnectSSH()
        status = .idle
        maybeConnect(force: true)
    }

    func trustPendingHost() {
        guard let request = pendingHostTrust else { return }
        settings.trustHostKey(request.publicKey, host: request.host, port: request.port)
        pendingHostTrust = nil
        request.accept()
    }

    func rejectPendingHost() {
        guard let request = pendingHostTrust else { return }
        pendingHostTrust = nil
        request.reject()
        status = .failed("The Mac’s SSH host key was not trusted.")
    }

    func forgetTrustedHost(fallbackHost: String?) {
        settings.forgetCurrentTrustedHost(fallbackHost: fallbackHost)
        reconnectAfterSettingsChange(fallbackHost: fallbackHost)
    }

    private func maybeConnect(force: Bool = false) {
        guard isVisible, appIsActive, networkAvailable, let terminalView else { return }
        guard let configuration = settings.configuration(fallbackHost: fallbackHost) else {
            status = .idle
            return
        }
        if !force, status == .connecting || status == .connected { return }
        let trustedKey = settings.trustedHostKey(host: configuration.host, port: configuration.port)
        status = .connecting
        terminalView.connect(configuration: configuration, trustedHostKey: trustedKey)
    }

    private func startPathMonitor() {
        let monitor = NWPathMonitor()
        pathMonitor = monitor
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self else { return }
                let wasAvailable = self.networkAvailable
                self.networkAvailable = path.status == .satisfied
                if self.networkAvailable, !wasAvailable {
                    self.maybeConnect(force: true)
                } else if !self.networkAvailable {
                    self.terminalView?.disconnectSSH()
                    self.status = .failed("The network is unavailable.")
                }
            }
        }
        monitor.start(queue: DispatchQueue(label: "com.operation-jarvis.pi-terminal-path"))
    }
}

private extension PiTerminalConnectionStatus {
    var isFailure: Bool {
        if case .failed = self { return true }
        return false
    }
}
