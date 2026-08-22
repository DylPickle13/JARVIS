import CryptoKit
import Foundation
import NIOCore
import NIOPosix
import NIOSSH
import SwiftTerm
import UIKit

final class PiPendingHostTrust: Identifiable, @unchecked Sendable {
    let id = UUID()
    let host: String
    let port: Int
    let publicKey: String
    let fingerprint: String

    private let promise: EventLoopPromise<Void>
    private let lock = NSLock()
    private var resolved = false

    init(host: String, port: Int, publicKey: String, promise: EventLoopPromise<Void>) {
        self.host = host
        self.port = port
        self.publicKey = publicKey
        self.fingerprint = Self.fingerprint(for: publicKey)
        self.promise = promise
    }

    func accept() {
        resolve { promise.succeed(()) }
    }

    func reject() {
        resolve { promise.fail(PiSSHError.hostKeyRejected) }
    }

    private func resolve(_ action: () -> Void) {
        lock.lock()
        guard !resolved else {
            lock.unlock()
            return
        }
        resolved = true
        lock.unlock()
        action()
    }

    private static func fingerprint(for publicKey: String) -> String {
        let components = publicKey.split(separator: " ", maxSplits: 2)
        guard components.count >= 2,
              let bytes = Data(base64Encoded: String(components[1])) else {
            return "Unavailable"
        }
        let digest = SHA256.hash(data: bytes)
        return "SHA256:" + Data(digest).base64EncodedString().replacingOccurrences(of: "=", with: "")
    }
}

enum PiTerminalKeyDeck {
    static let slashBytes: [UInt8] = [0x2f]
}

enum PiTerminalKeyboard {
    // SwiftTerm's UIKeyInput reports `hasText == false` when its temporary
    // local buffer is empty, which makes iOS stop software-keyboard Backspace
    // auto-repeat even though the remote terminal still has editable input.
    // This marked, zero-width sentinel keeps Backspace enabled without sending
    // any sentinel bytes to SSH; real text replaces it normally.
    static let backspaceRepeatSentinel = "\u{200B}"
}

enum PiTerminalTouchScroll {
    static let deliveryFramesPerSecond = 60
    static let maximumPendingSteps = 8

    static func pointsPerWheelStep(fontSize: CGFloat) -> CGFloat {
        max(36, fontSize * 2.5)
    }

    static func pendingSteps(after current: Int, scrollingUp: Bool) -> Int {
        let direction = scrollingUp ? 1 : -1
        let alignedCurrent = current.signum() == direction ? current : 0
        return min(max(alignedCurrent + direction, -maximumPendingSteps), maximumPendingSteps)
    }

    static func wheelBytes(scrollingUp: Bool, column: Int, row: Int) -> [UInt8] {
        let button = scrollingUp ? 64 : 65
        return Array("\u{1b}[<\(button);\(max(1, column));\(max(1, row))M".utf8)
    }
}

enum PiTerminalPresentation {
    static let fontSizeDefaultsKey = "jarvis.pi-terminal.font-size"
    static let zoomSchemaDefaultsKey = "jarvis.pi-terminal.zoom-schema"
    static let currentZoomSchema = 1
    static let minimumFontSize: CGFloat = 9
    static let defaultFontSize: CGFloat = 18
    static let maximumFontSize: CGFloat = 20

    static func resolvedFontSize(savedValue: Double, savedZoomSchema: Int) -> CGFloat {
        guard savedZoomSchema >= currentZoomSchema, savedValue > 0 else {
            return defaultFontSize
        }
        return min(max(CGFloat(savedValue), minimumFontSize), maximumFontSize)
    }
}

private enum PiSSHError: LocalizedError {
    case invalidChannelType
    case hostKeyChanged
    case hostKeyRejected
    case sessionEnded

    var errorDescription: String? {
        switch self {
        case .invalidChannelType:
            return "The SSH server returned an unsupported channel."
        case .hostKeyChanged:
            return "The Mac’s SSH host key changed. Forget the trusted host in Settings before reconnecting."
        case .hostKeyRejected:
            return "The Mac’s SSH host key was not trusted."
        case .sessionEnded:
            return "The Pi terminal session ended."
        }
    }
}

private final class PiHostKeyValidator: NIOSSHClientServerAuthenticationDelegate, @unchecked Sendable {
    private let host: String
    private let port: Int
    private let trustedKey: String?
    private let requestTrust: @Sendable (PiPendingHostTrust) -> Void

    init(
        host: String,
        port: Int,
        trustedKey: String?,
        requestTrust: @escaping @Sendable (PiPendingHostTrust) -> Void
    ) {
        self.host = host
        self.port = port
        self.trustedKey = trustedKey
        self.requestTrust = requestTrust
    }

    func validateHostKey(hostKey: NIOSSHPublicKey, validationCompletePromise: EventLoopPromise<Void>) {
        let offered = String(openSSHPublicKey: hostKey)
        if let trustedKey {
            if trustedKey == offered {
                validationCompletePromise.succeed(())
            } else {
                validationCompletePromise.fail(PiSSHError.hostKeyChanged)
            }
            return
        }
        requestTrust(
            PiPendingHostTrust(
                host: host,
                port: port,
                publicKey: offered,
                promise: validationCompletePromise
            )
        )
    }
}

private final class PiSSHErrorHandler: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = Any

    private let onError: @Sendable (Error) -> Void

    init(onError: @escaping @Sendable (Error) -> Void) {
        self.onError = onError
    }

    func errorCaught(context: ChannelHandlerContext, error: Error) {
        onError(error)
        context.close(promise: nil)
    }
}

private final class PiSSHSessionHandler: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = SSHChannelData

    private let term: String
    private let initialWindowSize: (cols: Int, rows: Int)
    private let onOutput: @Sendable ([UInt8]) -> Void
    private let onReady: @Sendable () -> Void
    private let onEnded: @Sendable () -> Void

    init(
        term: String,
        initialWindowSize: (cols: Int, rows: Int),
        onOutput: @escaping @Sendable ([UInt8]) -> Void,
        onReady: @escaping @Sendable () -> Void,
        onEnded: @escaping @Sendable () -> Void
    ) {
        self.term = term
        self.initialWindowSize = initialWindowSize
        self.onOutput = onOutput
        self.onReady = onReady
        self.onEnded = onEnded
    }

    func handlerAdded(context: ChannelHandlerContext) {
        context.channel.setOption(ChannelOptions.allowRemoteHalfClosure, value: true).whenFailure { error in
            context.fireErrorCaught(error)
        }
    }

    func channelActive(context: ChannelHandlerContext) {
        let pty = SSHChannelRequestEvent.PseudoTerminalRequest(
            wantReply: false,
            term: term,
            terminalCharacterWidth: initialWindowSize.cols,
            terminalRowHeight: initialWindowSize.rows,
            terminalPixelWidth: 0,
            terminalPixelHeight: 0,
            terminalModes: SSHTerminalModes([:])
        )
        context.triggerUserOutboundEvent(pty, promise: nil)
        context.triggerUserOutboundEvent(
            SSHChannelRequestEvent.EnvironmentRequest(wantReply: false, name: "LANG", value: "en_US.UTF-8"),
            promise: nil
        )
        context.triggerUserOutboundEvent(
            SSHChannelRequestEvent.EnvironmentRequest(wantReply: false, name: "COLORTERM", value: "truecolor"),
            promise: nil
        )
        context.triggerUserOutboundEvent(
            SSHChannelRequestEvent.ExecRequest(command: PiTerminalConfiguration.remoteCommand, wantReply: false),
            promise: nil
        )
        onReady()
    }

    func channelRead(context: ChannelHandlerContext, data: NIOAny) {
        let payload = unwrapInboundIn(data)
        guard case .byteBuffer(var buffer) = payload.data,
              let bytes = buffer.readBytes(length: buffer.readableBytes),
              !bytes.isEmpty else { return }
        onOutput(bytes)
    }

    func userInboundEventTriggered(context: ChannelHandlerContext, event: Any) {
        if let status = event as? SSHChannelRequestEvent.ExitStatus {
            onOutput(Array("\r\n[Pi exited with status \(status.exitStatus)]\r\n".utf8))
        } else if let signal = event as? SSHChannelRequestEvent.ExitSignal {
            onOutput(Array("\r\n[Pi session closed: \(signal.signalName)]\r\n".utf8))
        } else {
            context.fireUserInboundEventTriggered(event)
        }
    }

    func channelInactive(context: ChannelHandlerContext) {
        onEnded()
        context.fireChannelInactive()
    }
}

private final class PiSSHConnection: @unchecked Sendable {
    private let configuration: PiTerminalConfiguration
    private let trustedHostKey: String?
    private let initialWindowSize: (cols: Int, rows: Int)
    private let onOutput: @Sendable ([UInt8]) -> Void
    private let onReady: @Sendable () -> Void
    private let onTrust: @Sendable (PiPendingHostTrust) -> Void
    private let onFailure: @Sendable (Error) -> Void

    private let stateLock = NSLock()
    private var didFail = false
    private var intentionalClose = false
    private var group: EventLoopGroup?
    private var channel: Channel?
    private var sessionChannel: Channel?

    init(
        configuration: PiTerminalConfiguration,
        trustedHostKey: String?,
        initialWindowSize: (cols: Int, rows: Int),
        onOutput: @escaping @Sendable ([UInt8]) -> Void,
        onReady: @escaping @Sendable () -> Void,
        onTrust: @escaping @Sendable (PiPendingHostTrust) -> Void,
        onFailure: @escaping @Sendable (Error) -> Void
    ) {
        self.configuration = configuration
        self.trustedHostKey = trustedHostKey
        self.initialWindowSize = initialWindowSize
        self.onOutput = onOutput
        self.onReady = onReady
        self.onTrust = onTrust
        self.onFailure = onFailure
    }

    func connect() {
        let group = MultiThreadedEventLoopGroup(numberOfThreads: 1)
        self.group = group

        let userAuth = SimplePasswordDelegate(
            username: configuration.username,
            password: configuration.password
        )
        let serverAuth = PiHostKeyValidator(
            host: configuration.host,
            port: configuration.port,
            trustedKey: trustedHostKey,
            requestTrust: onTrust
        )

        let bootstrap = ClientBootstrap(group: group)
            .channelInitializer { channel in
                channel.eventLoop.makeCompletedFuture {
                    let sshHandler = NIOSSHHandler(
                        role: .client(
                            .init(
                                userAuthDelegate: userAuth,
                                serverAuthDelegate: serverAuth
                            )
                        ),
                        allocator: channel.allocator,
                        inboundChildChannelInitializer: nil
                    )
                    let sync = channel.pipeline.syncOperations
                    try sync.addHandler(sshHandler)
                    try sync.addHandler(PiSSHErrorHandler { [weak self] error in
                        self?.fail(error)
                    })
                }
            }
            .channelOption(ChannelOptions.socket(SocketOptionLevel(SOL_SOCKET), SO_REUSEADDR), value: 1)
            .channelOption(ChannelOptions.socket(SocketOptionLevel(IPPROTO_TCP), TCP_NODELAY), value: 1)

        bootstrap.connect(host: configuration.host, port: configuration.port).whenComplete { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error):
                self.fail(error)
                self.shutdownGroup()
            case .success(let channel):
                self.channel = channel
                channel.closeFuture.whenComplete { [weak self] _ in self?.shutdownGroup() }
                self.createSessionChannel(on: channel)
            }
        }
    }

    func send(_ data: Data) {
        guard let sessionChannel else { return }
        sessionChannel.eventLoop.execute {
            var buffer = sessionChannel.allocator.buffer(capacity: data.count)
            buffer.writeBytes(data)
            sessionChannel.writeAndFlush(
                SSHChannelData(type: .channel, data: .byteBuffer(buffer)),
                promise: nil
            )
        }
    }

    func resize(cols: Int, rows: Int) {
        guard cols > 0, rows > 0, let sessionChannel else { return }
        sessionChannel.eventLoop.execute {
            sessionChannel.triggerUserOutboundEvent(
                SSHChannelRequestEvent.WindowChangeRequest(
                    terminalCharacterWidth: cols,
                    terminalRowHeight: rows,
                    terminalPixelWidth: 0,
                    terminalPixelHeight: 0
                ),
                promise: nil
            )
        }
    }

    func disconnect() {
        stateLock.lock()
        intentionalClose = true
        stateLock.unlock()

        let parent = channel
        let group = group
        channel = nil
        sessionChannel = nil
        self.group = nil

        if let parent, let group {
            parent.closeFuture.whenComplete { _ in
                group.shutdownGracefully { _ in }
            }
            parent.close(promise: nil)
        } else if let group {
            group.shutdownGracefully { _ in }
        }
    }

    private func createSessionChannel(on channel: Channel) {
        channel.pipeline.handler(type: NIOSSHHandler.self).flatMap { [weak self] (sshHandler: NIOSSHHandler) -> EventLoopFuture<Channel> in
            guard let self else {
                return channel.eventLoop.makeFailedFuture(PiSSHError.invalidChannelType)
            }
            let promise = channel.eventLoop.makePromise(of: Channel.self)
            sshHandler.createChannel(promise, channelType: .session) { childChannel, channelType in
                guard channelType == .session else {
                    return channel.eventLoop.makeFailedFuture(PiSSHError.invalidChannelType)
                }
                return childChannel.eventLoop.makeCompletedFuture {
                    let sync = childChannel.pipeline.syncOperations
                    try sync.addHandler(
                        PiSSHSessionHandler(
                            term: "xterm-256color",
                            initialWindowSize: self.initialWindowSize,
                            onOutput: self.onOutput,
                            onReady: self.onReady,
                            onEnded: { [weak self] in self?.sessionEnded() }
                        )
                    )
                    try sync.addHandler(PiSSHErrorHandler { [weak self] error in
                        self?.fail(error)
                    })
                }
            }
            return promise.futureResult
        }.whenComplete { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error):
                self.fail(error)
            case .success(let childChannel):
                self.sessionChannel = childChannel
                self.resize(cols: self.initialWindowSize.cols, rows: self.initialWindowSize.rows)
            }
        }
    }

    private func sessionEnded() {
        stateLock.lock()
        let shouldReport = !intentionalClose
        stateLock.unlock()
        if shouldReport {
            fail(PiSSHError.sessionEnded)
            channel?.close(promise: nil)
        }
    }

    private func fail(_ error: Error) {
        stateLock.lock()
        guard !intentionalClose, !didFail else {
            stateLock.unlock()
            return
        }
        didFail = true
        stateLock.unlock()
        onFailure(error)
    }

    private func shutdownGroup() {
        stateLock.lock()
        let group = self.group
        self.group = nil
        stateLock.unlock()
        group?.shutdownGracefully { _ in }
    }
}

final class PiTerminalHostView: TerminalView, TerminalViewDelegate, UIGestureRecognizerDelegate {
    var stateChanged: ((PiTerminalConnectionStatus) -> Void)?
    var hostTrustRequested: ((PiPendingHostTrust) -> Void)?
    var controlLatchChanged: ((Bool) -> Void)?
    var keyboardFocusChanged: ((Bool) -> Void)?

    private var sshConnection: PiSSHConnection?
    private var connectionID = UUID()
    private var controlLatched = false {
        didSet { controlLatchChanged?(controlLatched) }
    }
    private var pinchStartFontSize = PiTerminalPresentation.defaultFontSize
    private var touchScrollPan: UIPanGestureRecognizer!
    private var keyboardDismissPan: UIPanGestureRecognizer!
    private var remoteMouseModeEnabled = false
    private var touchScrollRemainder: CGFloat = 0
    private var pendingTouchScrollSteps = 0
    private var pendingTouchScrollLocation = (column: 1, row: 1)
    private var touchScrollDisplayLink: CADisplayLink?
    var isRoutingTouchScrollToPi: Bool { remoteMouseModeEnabled }

    override init(frame: CGRect) {
        super.init(frame: frame)
        terminalDelegate = self
        nativeBackgroundColor = .black
        nativeForegroundColor = .white
        let defaults = UserDefaults.standard
        let savedFontSize = defaults.double(forKey: PiTerminalPresentation.fontSizeDefaultsKey)
        let savedZoomSchema = defaults.integer(forKey: PiTerminalPresentation.zoomSchemaDefaultsKey)
        let fontSize = PiTerminalPresentation.resolvedFontSize(
            savedValue: savedFontSize,
            savedZoomSchema: savedZoomSchema
        )
        defaults.set(Double(fontSize), forKey: PiTerminalPresentation.fontSizeDefaultsKey)
        defaults.set(PiTerminalPresentation.currentZoomSchema, forKey: PiTerminalPresentation.zoomSchemaDefaultsKey)
        font = .monospacedSystemFont(ofSize: fontSize, weight: .regular)
        pinchStartFontSize = fontSize
        optionAsMetaKey = true
        allowMouseReporting = false
        linkReporting = .implicit
        autocapitalizationType = .none
        autocorrectionType = .no
        spellCheckingType = .no
        smartDashesType = .no
        smartQuotesType = .no
        inputAccessoryView = nil
        keyboardDismissMode = .interactive
        prioritizeTouchScrolling()

        addGestureRecognizer(UIPinchGestureRecognizer(target: self, action: #selector(handleFontPinch(_:))))
        let dismissPan = UIPanGestureRecognizer(target: self, action: #selector(handleKeyboardDismissPan(_:)))
        dismissPan.cancelsTouchesInView = false
        dismissPan.delegate = self
        keyboardDismissPan = dismissPan
        addGestureRecognizer(dismissPan)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    deinit {
        stopTouchScrollDelivery(clearPending: true)
        sshConnection?.disconnect()
    }

    private func prioritizeTouchScrolling() {
        alwaysBounceVertical = true
        isDirectionalLockEnabled = true

        // SwiftTerm installs long-press and multi-tap selection recognizers.
        // The phone terminal reserves touch drags for Pi viewport scrolling;
        // copy-response and paste remain available from the fixed key deck.
        for recognizer in gestureRecognizers ?? [] {
            if recognizer is UILongPressGestureRecognizer {
                recognizer.isEnabled = false
            } else if let tap = recognizer as? UITapGestureRecognizer,
                      tap.numberOfTapsRequired > 1 {
                tap.isEnabled = false
            }
        }

        let scrollPan = UIPanGestureRecognizer(target: self, action: #selector(handleTouchScrollPan(_:)))
        scrollPan.cancelsTouchesInView = false
        scrollPan.delegate = self
        touchScrollPan = scrollPan
        addGestureRecognizer(scrollPan)
        panGestureRecognizer.require(toFail: scrollPan)
    }

    override func mouseModeChanged(source: Terminal) {
        // Pi owns its fullscreen transcript. Suppress SwiftTerm's button-drag
        // recognizer (which selects text) and route vertical touch movement to
        // SGR wheel events instead. Outside mouse mode, native scrollback wins.
        remoteMouseModeEnabled = source.mouseMode != .off
        if !remoteMouseModeEnabled {
            stopTouchScrollDelivery(clearPending: true)
            touchScrollRemainder = 0
        }
    }

    func connect(configuration: PiTerminalConfiguration, trustedHostKey: String?) {
        disconnectSSH()
        let id = UUID()
        connectionID = id
        stateChanged?(.connecting)

        let terminal = getTerminal()
        let dimensions = (
            cols: terminal.cols > 0 ? terminal.cols : 80,
            rows: terminal.rows > 0 ? terminal.rows : 24
        )

        let connection = PiSSHConnection(
            configuration: configuration,
            trustedHostKey: trustedHostKey,
            initialWindowSize: dimensions,
            onOutput: { [weak self] bytes in
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.connectionID == id else { return }
                    self.feed(byteArray: bytes[...])
                }
            },
            onReady: { [weak self] in
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.connectionID == id else { return }
                    self.stateChanged?(.connected)
                }
            },
            onTrust: { [weak self] request in
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.connectionID == id else {
                        request.reject()
                        return
                    }
                    self.hostTrustRequested?(request)
                }
            },
            onFailure: { [weak self] error in
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.connectionID == id else { return }
                    self.stateChanged?(.failed(error.localizedDescription))
                }
            }
        )
        sshConnection = connection
        connection.connect()
    }

    func disconnectSSH() {
        connectionID = UUID()
        let connection = sshConnection
        sshConnection = nil
        connection?.disconnect()
        controlLatched = false
        remoteMouseModeEnabled = false
        touchScrollRemainder = 0
        stopTouchScrollDelivery(clearPending: true)
    }

    @objc private func handleFontPinch(_ recognizer: UIPinchGestureRecognizer) {
        if recognizer.state == .began {
            pinchStartFontSize = font.pointSize
        }
        let nextSize = min(
            max(pinchStartFontSize * recognizer.scale, PiTerminalPresentation.minimumFontSize),
            PiTerminalPresentation.maximumFontSize
        )
        font = .monospacedSystemFont(ofSize: nextSize, weight: .regular)
        if recognizer.state == .ended || recognizer.state == .cancelled {
            UserDefaults.standard.set(Double(nextSize), forKey: PiTerminalPresentation.fontSizeDefaultsKey)
        }
    }

    @objc private func handleTouchScrollPan(_ recognizer: UIPanGestureRecognizer) {
        switch recognizer.state {
        case .began:
            touchScrollRemainder = 0
        case .changed:
            touchScrollRemainder += recognizer.translation(in: self).y
            recognizer.setTranslation(.zero, in: self)

            let pointsPerWheelStep = PiTerminalTouchScroll.pointsPerWheelStep(fontSize: font.pointSize)
            let location = recognizer.location(in: self)
            let terminal = getTerminal()
            let column = min(
                max(1, Int((location.x / max(bounds.width, 1)) * CGFloat(max(terminal.cols, 1))) + 1),
                max(terminal.cols, 1)
            )
            let row = min(
                max(1, Int((location.y / max(bounds.height, 1)) * CGFloat(max(terminal.rows, 1))) + 1),
                max(terminal.rows, 1)
            )

            while abs(touchScrollRemainder) >= pointsPerWheelStep {
                let scrollingUp = touchScrollRemainder > 0
                enqueueTouchScrollStep(scrollingUp: scrollingUp, column: column, row: row)
                touchScrollRemainder += scrollingUp ? -pointsPerWheelStep : pointsPerWheelStep
            }
        case .ended, .cancelled, .failed:
            touchScrollRemainder = 0
        default:
            break
        }
    }

    private func enqueueTouchScrollStep(scrollingUp: Bool, column: Int, row: Int) {
        guard sshConnection != nil, remoteMouseModeEnabled else { return }
        pendingTouchScrollLocation = (column, row)
        pendingTouchScrollSteps = PiTerminalTouchScroll.pendingSteps(
            after: pendingTouchScrollSteps,
            scrollingUp: scrollingUp
        )
        guard touchScrollDisplayLink == nil else { return }

        let displayLink = CADisplayLink(target: self, selector: #selector(deliverNextTouchScrollStep(_:)))
        displayLink.preferredFramesPerSecond = PiTerminalTouchScroll.deliveryFramesPerSecond
        displayLink.add(to: .main, forMode: .common)
        touchScrollDisplayLink = displayLink
    }

    @objc private func deliverNextTouchScrollStep(_ displayLink: CADisplayLink) {
        guard sshConnection != nil, remoteMouseModeEnabled, pendingTouchScrollSteps != 0 else {
            stopTouchScrollDelivery(clearPending: true)
            return
        }

        let scrollingUp = pendingTouchScrollSteps > 0
        pendingTouchScrollSteps += scrollingUp ? -1 : 1
        sendAccessoryBytes(PiTerminalTouchScroll.wheelBytes(
            scrollingUp: scrollingUp,
            column: pendingTouchScrollLocation.column,
            row: pendingTouchScrollLocation.row
        ))
        if pendingTouchScrollSteps == 0 {
            stopTouchScrollDelivery(clearPending: false)
        }
    }

    private func stopTouchScrollDelivery(clearPending: Bool) {
        touchScrollDisplayLink?.invalidate()
        touchScrollDisplayLink = nil
        if clearPending {
            pendingTouchScrollSteps = 0
        }
    }

    @objc private func handleKeyboardDismissPan(_ recognizer: UIPanGestureRecognizer) {
        guard recognizer.state == .ended,
              recognizer.translation(in: self).y >= 44 else { return }
        _ = resignFirstResponder()
    }

    override func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
        guard let pan = gestureRecognizer as? UIPanGestureRecognizer else { return true }
        let velocity = pan.velocity(in: self)
        let isVertical = abs(velocity.y) > abs(velocity.x)
        if gestureRecognizer === touchScrollPan {
            return remoteMouseModeEnabled && isVertical
        }
        if gestureRecognizer === keyboardDismissPan {
            return isFirstResponder && velocity.y > 0 && isVertical
        }
        return true
    }

    func gestureRecognizer(
        _ gestureRecognizer: UIGestureRecognizer,
        shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
    ) -> Bool {
        gestureRecognizer === keyboardDismissPan || otherGestureRecognizer === keyboardDismissPan
    }

    override func becomeFirstResponder() -> Bool {
        let becameFirstResponder = super.becomeFirstResponder()
        if becameFirstResponder {
            ensureBackspaceAutoRepeatSentinel()
            keyboardFocusChanged?(true)
        }
        return becameFirstResponder
    }

    override func resignFirstResponder() -> Bool {
        let resignedFirstResponder = super.resignFirstResponder()
        if resignedFirstResponder {
            keyboardFocusChanged?(false)
        }
        return resignedFirstResponder
    }

    func sendAccessoryBytes(_ bytes: [UInt8]) {
        guard sshConnection != nil else { return }
        sshConnection?.send(Data(bytes))
    }

    func toggleControlLatch() {
        controlLatched.toggle()
    }

    override func insertText(_ text: String) {
        if controlLatched,
           text.unicodeScalars.count == 1,
           let scalar = text.lowercased().unicodeScalars.first,
           scalar.value >= 0x40,
           scalar.value <= 0x7f {
            sendAccessoryBytes([UInt8(scalar.value) & 0x1f])
            controlLatched = false
            return
        }
        super.insertText(text)
        ensureBackspaceAutoRepeatSentinel()
    }

    override func deleteBackward() {
        super.deleteBackward()
        ensureBackspaceAutoRepeatSentinel()
    }

    func ensureBackspaceAutoRepeatSentinel() {
        guard !hasText else { return }
        let sentinel = PiTerminalKeyboard.backspaceRepeatSentinel
        setMarkedText(sentinel, selectedRange: NSRange(location: sentinel.utf16.count, length: 0))
    }

    func scrolled(source: TerminalView, position: Double) {}
    func setTerminalTitle(source: TerminalView, title: String) {}
    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}

    func sizeChanged(source: TerminalView, newCols: Int, newRows: Int) {
        sshConnection?.resize(cols: newCols, rows: newRows)
    }

    func send(source: TerminalView, data: ArraySlice<UInt8>) {
        sshConnection?.send(Data(data))
    }

    func clipboardCopy(source: TerminalView, content: Data) {
        if let text = String(data: content, encoding: .utf8) {
            UIPasteboard.general.string = text
        }
    }

    func clipboardRead(source: TerminalView) -> Data? { nil }
    func iTermContent(source: TerminalView, content: ArraySlice<UInt8>) {}
    func rangeChanged(source: TerminalView, startY: Int, endY: Int) {}
    func bell(source: TerminalView) { UINotificationFeedbackGenerator().notificationOccurred(.success) }

    func requestOpenLink(source: TerminalView, link: String, params: [String: String]) {
        guard let url = URL(string: link), ["http", "https"].contains(url.scheme?.lowercased() ?? "") else { return }
        UIApplication.shared.open(url)
    }
}
