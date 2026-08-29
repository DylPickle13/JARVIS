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
    // The invisible keyboard proxy owns this local sentinel so UIKit keeps
    // software-keyboard Backspace auto-repeat enabled. It never enters
    // SwiftTerm's full-screen UITextInput storage or the SSH byte stream.
    static let proxyBufferSentinel = "\u{200B}"
}

struct PiTerminalWindowSize: Equatable, Sendable {
    let cols: Int
    let rows: Int

    init?(cols: Int, rows: Int) {
        guard cols > 0, rows > 0 else { return nil }
        self.cols = cols
        self.rows = rows
    }
}

final class PiTerminalWindowState: @unchecked Sendable {
    private let lock = NSLock()
    private var value: PiTerminalWindowSize

    init(initial: PiTerminalWindowSize) {
        value = initial
    }

    @discardableResult
    func update(cols: Int, rows: Int) -> PiTerminalWindowSize? {
        guard let size = PiTerminalWindowSize(cols: cols, rows: rows) else { return nil }
        lock.lock()
        value = size
        lock.unlock()
        return size
    }

    func snapshot() -> PiTerminalWindowSize {
        lock.lock()
        let current = value
        lock.unlock()
        return current
    }
}

enum PiTerminalTouchScroll {
    static func pointsPerWheelStep(fontSize: CGFloat) -> CGFloat {
        max(36, fontSize * 2.5)
    }

    static func cursorLocation(column: Int, row: Int, columns: Int, rows: Int) -> (column: Int, row: Int) {
        (
            min(max(column + 1, 1), max(columns, 1)),
            min(max(row + 1, 1), max(rows, 1))
        )
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
    private let initialWindowSize: PiTerminalWindowSize
    private let onOutput: @Sendable ([UInt8]) -> Void
    private let onReady: @Sendable () -> Void
    private let onEnded: @Sendable () -> Void

    init(
        term: String,
        initialWindowSize: PiTerminalWindowSize,
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
    private let windowState: PiTerminalWindowState
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
        initialWindowSize: PiTerminalWindowSize,
        onOutput: @escaping @Sendable ([UInt8]) -> Void,
        onReady: @escaping @Sendable () -> Void,
        onTrust: @escaping @Sendable (PiPendingHostTrust) -> Void,
        onFailure: @escaping @Sendable (Error) -> Void
    ) {
        self.configuration = configuration
        self.trustedHostKey = trustedHostKey
        self.windowState = PiTerminalWindowState(initial: initialWindowSize)
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
        stateLock.lock()
        let sessionChannel = self.sessionChannel
        stateLock.unlock()
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
        // UIKit can finish the keyboard-hidden layout while SSH is still
        // authenticating. Retain that newest size even when no child session
        // channel exists yet; publishing only the stale PTY creation size can
        // leave tmux painting a short grid into SwiftTerm's taller viewport.
        guard let size = windowState.update(cols: cols, rows: rows) else { return }
        stateLock.lock()
        let sessionChannel = self.sessionChannel
        stateLock.unlock()
        guard let sessionChannel else { return }
        publishWindowChange(size, on: sessionChannel)
    }

    private func publishWindowChange(_ size: PiTerminalWindowSize, on sessionChannel: Channel) {
        sessionChannel.eventLoop.execute {
            sessionChannel.triggerUserOutboundEvent(
                SSHChannelRequestEvent.WindowChangeRequest(
                    terminalCharacterWidth: size.cols,
                    terminalRowHeight: size.rows,
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
        let parent = channel
        let group = group
        channel = nil
        sessionChannel = nil
        self.group = nil
        stateLock.unlock()

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
                    // NIOSSH invokes this initializer on the child channel's event loop,
                    // and SSHChildChannel explicitly supports synchronous options. Set
                    // half-closure before pipeline activation so no @Sendable future
                    // callback captures its event-loop-bound ChannelHandlerContext.
                    guard let synchronousOptions = childChannel.syncOptions else {
                        throw PiSSHError.invalidChannelType
                    }
                    try synchronousOptions.setOption(.allowRemoteHalfClosure, value: true)
                    let sync = childChannel.pipeline.syncOperations
                    try sync.addHandler(
                        PiSSHSessionHandler(
                            term: "xterm-256color",
                            initialWindowSize: self.windowState.snapshot(),
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
                self.stateLock.lock()
                self.sessionChannel = childChannel
                self.stateLock.unlock()
                // A SwiftUI layout resize may have arrived before the SSH child
                // channel. Publish the retained current viewport now rather
                // than replaying the stale PTY creation dimensions.
                self.publishWindowChange(self.windowState.snapshot(), on: childChannel)
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

final class PiTerminalKeyboardResponder: UITextView {
    var insertTextHandler: ((String) -> Void)?
    var deleteBackwardHandler: (() -> Void)?
    var focusChanged: ((Bool) -> Void)?

    init() {
        super.init(frame: .zero, textContainer: nil)
        text = PiTerminalKeyboard.proxyBufferSentinel
        selectedRange = NSRange(location: text.utf16.count, length: 0)
        backgroundColor = .clear
        textColor = .clear
        tintColor = .clear
        isScrollEnabled = false
        isAccessibilityElement = false
        autocapitalizationType = .none
        autocorrectionType = .no
        spellCheckingType = .no
        smartDashesType = .no
        smartQuotesType = .no
        inputAccessoryView = nil
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var hasText: Bool { true }

    override func insertText(_ text: String) {
        insertTextHandler?(text)
    }

    override func deleteBackward() {
        deleteBackwardHandler?()
    }

    override func becomeFirstResponder() -> Bool {
        let becameFirstResponder = super.becomeFirstResponder()
        if becameFirstResponder { focusChanged?(true) }
        return becameFirstResponder
    }

    override func resignFirstResponder() -> Bool {
        let wasFirstResponder = isFirstResponder
        let resignedFirstResponder = super.resignFirstResponder()
        if wasFirstResponder, resignedFirstResponder { focusChanged?(false) }
        return resignedFirstResponder
    }
}

// SwiftTerm's delegate predates actor annotations. Isolating this conformance
// keeps every synchronous UI/input callback on UIKit's main actor without
// queueing, reordering, or weakening the byte-exact terminal path.
final class PiTerminalHostView: TerminalView, @MainActor TerminalViewDelegate, UIGestureRecognizerDelegate {
    var stateChanged: ((PiTerminalConnectionStatus) -> Void)?
    var hostTrustRequested: ((PiPendingHostTrust) -> Void)?
    var controlLatchChanged: ((Bool) -> Void)?
    var keyboardFocusChanged: ((Bool) -> Void)?

    private var sshConnection: PiSSHConnection?
    private var connectionID = UUID()
    private let keyboardResponder = PiTerminalKeyboardResponder()
    private var controlLatched = false {
        didSet { controlLatchChanged?(controlLatched) }
    }
    private var pinchStartFontSize = PiTerminalPresentation.defaultFontSize
    private var touchScrollPan: UIPanGestureRecognizer!
    private var keyboardDismissPan: UIPanGestureRecognizer!
    private var remoteMouseModeEnabled = false
    private var touchScrollRemainder: CGFloat = 0
    var isRoutingTouchScrollToPi: Bool { remoteMouseModeEnabled }
    var isTerminalKeyboardFocused: Bool { keyboardResponder.isFirstResponder }
    var outboundBytesObserver: (([UInt8]) -> Void)?

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
        configureKeyboardResponder()
        configureFixedStepTouchScrolling()
        // Pi paints its own inverse-video cursor in the fixed input editor. Keep
        // the terminal hardware cursor hidden so tmux redraw/copy-mode cursor
        // movements can never flash over transcript rows.
        getTerminal().hideCursor()

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
        sshConnection?.disconnect()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        keyboardResponder.frame = CGRect(
            x: max(bounds.maxX - 1, 0),
            y: max(bounds.maxY - 1, 0),
            width: 1,
            height: 1
        )
    }

    private func configureKeyboardResponder() {
        keyboardResponder.insertTextHandler = { [weak self] text in
            self?.insertText(text)
        }
        keyboardResponder.deleteBackwardHandler = { [weak self] in
            self?.deleteBackward()
        }
        keyboardResponder.focusChanged = { [weak self] focused in
            self?.keyboardFocusChanged?(focused)
        }
        addSubview(keyboardResponder)
    }

    private func configureFixedStepTouchScrolling() {
        // Restore the accepted pre-native terminal interaction: one discrete Pi
        // wheel step per threshold, with no local UIScrollView momentum, bounce,
        // deceleration, snapshot, copy mode, or queued delivery.
        alwaysBounceVertical = false
        bounces = false
        isDirectionalLockEnabled = true
        panGestureRecognizer.isEnabled = false

        // SwiftTerm installs long-press and multi-tap selection recognizers.
        // The phone terminal reserves vertical drags for Pi's own exact viewport;
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
    }

    override func mouseModeChanged(source: Terminal) {
        // Do not call SwiftTerm's mouse implementation: it can install a fluid
        // drag recognizer. Pi owns the rendered viewport and receives only the
        // immediate fixed-step wheel events explicitly generated below.
        remoteMouseModeEnabled = source.mouseMode != .off
        if !remoteMouseModeEnabled { touchScrollRemainder = 0 }
    }

    override func showCursor(source: Terminal) {
        // The app-rendered Pi cursor remains visible in the input editor. A
        // hardware cursor is redundant and can momentarily appear wherever a
        // remote differential redraw or tmux copy operation left it.
        source.hideCursor()
    }

    func connect(configuration: PiTerminalConfiguration, trustedHostKey: String?) {
        disconnectSSH()
        prepareTerminalForFreshConnection()
        let id = UUID()
        connectionID = id
        stateChanged?(.connecting)

        let terminal = getTerminal()
        let dimensions = PiTerminalWindowSize(
            cols: terminal.cols > 0 ? terminal.cols : 80,
            rows: terminal.rows > 0 ? terminal.rows : 24
        )!

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

    func prepareTerminalForFreshConnection() {
        // Every SSH PTY is a new terminal byte stream. Reusing SwiftTerm's
        // parser, alternate-screen buffer, or repeat-character state from the
        // previous PTY can turn tmux's differential blank-cell redraws into a
        // viewport of stale periods while reconnecting. Reset only the local
        // emulator; the persistent tmux pane and Pi process remain untouched.
        let terminal = getTerminal()
        terminal.resetToInitialState()
        terminal.hideCursor()
        clearSelection()
    }

    func disconnectSSH() {
        connectionID = UUID()
        let connection = sshConnection
        sshConnection = nil
        connection?.disconnect()
        controlLatched = false
        remoteMouseModeEnabled = false
        touchScrollRemainder = 0
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
            let terminal = getTerminal()
            let location = PiTerminalTouchScroll.cursorLocation(
                column: terminal.buffer.x,
                row: terminal.buffer.y,
                columns: terminal.cols,
                rows: terminal.rows
            )

            // Emit at most one step for this UIKit update. Every generated byte
            // is sent immediately once; there is no wheel queue, display-link
            // pacing, replay, retry, or post-disconnect delivery.
            if abs(touchScrollRemainder) >= pointsPerWheelStep {
                let scrollingUp = touchScrollRemainder > 0
                touchScrollRemainder += scrollingUp ? -pointsPerWheelStep : pointsPerWheelStep
                sendTouchScrollStep(
                    scrollingUp: scrollingUp,
                    column: location.column,
                    row: location.row
                )
            }
        case .ended, .cancelled, .failed:
            touchScrollRemainder = 0
        default:
            break
        }
    }

    func sendTouchScrollStep(scrollingUp: Bool, column: Int, row: Int) {
        guard remoteMouseModeEnabled else { return }
        sendAccessoryBytes(PiTerminalTouchScroll.wheelBytes(
            scrollingUp: scrollingUp,
            column: column,
            row: row
        ))
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
            return isTerminalKeyboardFocused && velocity.y > 0 && isVertical
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
        keyboardResponder.becomeFirstResponder()
    }

    override func resignFirstResponder() -> Bool {
        guard keyboardResponder.isFirstResponder else { return true }
        return keyboardResponder.resignFirstResponder()
    }

    func sendAccessoryBytes(_ bytes: [UInt8]) {
        outboundBytesObserver?(bytes)
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
    }

    override func deleteBackward() {
        super.deleteBackward()
    }

    func scrolled(source: TerminalView, position: Double) {}
    func setTerminalTitle(source: TerminalView, title: String) {}
    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}

    func sizeChanged(source: TerminalView, newCols: Int, newRows: Int) {
        sshConnection?.resize(cols: newCols, rows: newRows)
    }

    func send(source: TerminalView, data: ArraySlice<UInt8>) {
        let bytes = Array(data)
        outboundBytesObserver?(bytes)
        sshConnection?.send(Data(bytes))
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
