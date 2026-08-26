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

enum PiTerminalHistoryMonitor {
    // Read only one numeric tmux metadata field. This companion SSH channel
    // never captures pane text, sends pane input, enters copy mode, or changes
    // tmux configuration/session state.
    static let remoteCommand = "while /opt/homebrew/bin/tmux -L jarvis-mobile has-session -t '=jarvis-ios' 2>/dev/null; do /opt/homebrew/bin/tmux -L jarvis-mobile display-message -p -t '=jarvis-ios:.%0' '#{history_size}'; /bin/sleep 0.025; done"
}

struct PiTerminalHistorySizeParser {
    private var pending: [UInt8] = []

    mutating func consume(_ bytes: [UInt8]) -> [Int] {
        var values: [Int] = []
        for byte in bytes {
            if byte == 0x0a {
                var line = pending
                pending.removeAll(keepingCapacity: true)
                if line.last == 0x0d { line.removeLast() }
                guard !line.isEmpty,
                      line.allSatisfy({ (0x30...0x39).contains($0) }),
                      let value = Int(String(decoding: line, as: UTF8.self)),
                      value >= 0 else { continue }
                values.append(value)
            } else if pending.count < 32 {
                pending.append(byte)
            } else {
                pending.removeAll(keepingCapacity: true)
            }
        }
        return values
    }
}

struct PiTerminalHistoryPromotionState {
    private(set) var latestHistorySize: Int?

    mutating func observe(historySize: Int) -> Int {
        guard historySize >= 0 else { return 0 }
        guard let previous = latestHistorySize else {
            latestHistorySize = historySize
            return 0
        }
        latestHistorySize = historySize
        guard historySize >= previous else {
            // A clear or newly created tmux session becomes the new baseline;
            // local history is never deleted or synthetically rewound.
            return 0
        }
        return historySize - previous
    }

    mutating func rebaseline(historySize: Int) {
        guard historySize >= 0 else { return }
        latestHistorySize = historySize
    }

    mutating func reset() {
        latestHistorySize = nil
    }
}

enum PiTerminalOutputSegment: Equatable {
    case bytes([UInt8])
    case fullScreenScrollUp(Int)
}

struct PiTerminalOutputBatch: Equatable {
    var segments: [PiTerminalOutputSegment] = []

    mutating func append(bytes: [UInt8]) {
        guard !bytes.isEmpty else { return }
        if case .bytes(let existing)? = segments.last {
            segments[segments.count - 1] = .bytes(existing + bytes)
        } else {
            segments.append(.bytes(bytes))
        }
    }
}

struct PiTerminalControlSequenceCounts: Equatable {
    var lineFeeds = 0
    var indexes = 0
    var csiSequences = 0
    var c1CSIBytes = 0
    var scrollUpCommands = 0
    var scrollUpRows = 0
    var deleteLineCommands = 0
    var deleteLineRows = 0
    var insertLineCommands = 0
    var eraseDisplayCommands = 0
    var eraseLineCommands = 0
    var cursorPositionCommands = 0
    var verticalPositionCommands = 0
    var scrollRegionCommands = 0
    var restrictedScrollRegionCommands = 0
}

struct PiTerminalControlSequenceDiagnostics {
    private enum State {
        case ground
        case escape
        case csi
        case controlString
        case controlStringEscape
    }

    private(set) var counts = PiTerminalControlSequenceCounts()
    private var state = State.ground
    private var csiBody: [UInt8] = []

    mutating func consume(_ bytes: [UInt8], terminalRows: Int) {
        for byte in bytes {
            switch state {
            case .ground:
                switch byte {
                case 0x0a:
                    counts.lineFeeds += 1
                case 0x1b:
                    state = .escape
                case 0x84:
                    counts.indexes += 1
                case 0x90, 0x98, 0x9d, 0x9e, 0x9f:
                    state = .controlString
                case 0x9b:
                    counts.c1CSIBytes += 1
                    csiBody.removeAll(keepingCapacity: true)
                    state = .csi
                default:
                    break
                }

            case .escape:
                switch byte {
                case 0x5b:
                    csiBody.removeAll(keepingCapacity: true)
                    state = .csi
                case 0x44:
                    counts.indexes += 1
                    state = .ground
                case 0x50, 0x58, 0x5d, 0x5e, 0x5f:
                    state = .controlString
                case 0x1b:
                    state = .escape
                default:
                    state = .ground
                }

            case .csi:
                if (0x40...0x7e).contains(byte) {
                    recordCSI(final: byte, body: csiBody, terminalRows: terminalRows)
                    csiBody.removeAll(keepingCapacity: true)
                    state = .ground
                } else if (0x20...0x3f).contains(byte), csiBody.count < 64 {
                    csiBody.append(byte)
                } else if byte == 0x1b {
                    csiBody.removeAll(keepingCapacity: true)
                    state = .escape
                } else {
                    csiBody.removeAll(keepingCapacity: true)
                    state = .ground
                }

            case .controlString:
                if byte == 0x07 || byte == 0x9c {
                    state = .ground
                } else if byte == 0x1b {
                    state = .controlStringEscape
                }

            case .controlStringEscape:
                if byte == 0x5c {
                    state = .ground
                } else if byte != 0x1b {
                    state = .controlString
                }
            }
        }
    }

    mutating func reset() {
        counts = PiTerminalControlSequenceCounts()
        state = .ground
        csiBody.removeAll(keepingCapacity: true)
    }

    private mutating func recordCSI(final: UInt8, body: [UInt8], terminalRows: Int) {
        counts.csiSequences += 1
        let parameters = plainParameters(body)
        let requested = parameters?.first.flatMap { $0 } ?? 1
        let rows = max(requested, 1)

        switch final {
        case 0x53 where parameters != nil:
            counts.scrollUpCommands += 1
            counts.scrollUpRows += rows
        case 0x4d where parameters != nil:
            counts.deleteLineCommands += 1
            counts.deleteLineRows += rows
        case 0x4c where parameters != nil:
            counts.insertLineCommands += 1
        case 0x4a where parameters != nil:
            counts.eraseDisplayCommands += 1
        case 0x4b where parameters != nil:
            counts.eraseLineCommands += 1
        case 0x48 where parameters != nil:
            counts.cursorPositionCommands += 1
        case 0x66 where parameters != nil:
            counts.cursorPositionCommands += 1
        case 0x64 where parameters != nil:
            counts.verticalPositionCommands += 1
        case 0x72 where parameters != nil:
            counts.scrollRegionCommands += 1
            guard terminalRows > 0 else { break }
            let top = parameters?.first.flatMap { $0 } ?? 1
            let bottom = (parameters?.count ?? 0) > 1 ? (parameters?[1] ?? terminalRows) : terminalRows
            if top != 1 || bottom != terminalRows {
                counts.restrictedScrollRegionCommands += 1
            }
        default:
            break
        }
    }

    private func plainParameters(_ body: [UInt8]) -> [Int?]? {
        guard body.allSatisfy({ (0x30...0x39).contains($0) || $0 == 0x3b }) else { return nil }
        if body.isEmpty { return [] }
        return String(decoding: body, as: UTF8.self)
            .split(separator: ";", omittingEmptySubsequences: false)
            .map { $0.isEmpty ? nil : Int($0) }
    }
}

struct PiTerminalOutputFilter {
    private static let outerAlternateScreenSequences: Set<[UInt8]> = [
        Array("\u{1b}[?1049h".utf8),
        Array("\u{1b}[?1049l".utf8)
    ]

    private var pendingEscape: [UInt8] = []
    private var fullScreenScrollRegion = true

    mutating func consume(_ bytes: [UInt8], terminalRows: Int) -> PiTerminalOutputBatch {
        var batch = PiTerminalOutputBatch()
        var literal: [UInt8] = []
        literal.reserveCapacity(bytes.count)

        func flushLiteral() {
            batch.append(bytes: literal)
            literal.removeAll(keepingCapacity: true)
        }

        for byte in bytes {
            if pendingEscape.isEmpty {
                if byte == 0x1b {
                    pendingEscape.append(byte)
                } else {
                    literal.append(byte)
                }
                continue
            }

            pendingEscape.append(byte)
            if pendingEscape.count == 2, byte != 0x5b {
                literal.append(contentsOf: pendingEscape)
                pendingEscape.removeAll(keepingCapacity: true)
                continue
            }

            guard pendingEscape.count >= 3 else { continue }
            if (0x40...0x7e).contains(byte) {
                let sequence = pendingEscape
                pendingEscape.removeAll(keepingCapacity: true)

                if Self.outerAlternateScreenSequences.contains(sequence) {
                    continue
                }

                if byte == 0x72,
                   let parameters = plainCSIParameters(sequence),
                   terminalRows > 0 {
                    let top = parameters.first.flatMap { $0 } ?? 1
                    let bottom = parameters.count > 1 ? (parameters[1] ?? terminalRows) : terminalRows
                    fullScreenScrollRegion = top == 1 && bottom == terminalRows
                }

                if byte == 0x53,
                   fullScreenScrollRegion,
                   let parameters = plainCSIParameters(sequence),
                   terminalRows > 0 {
                    let requested = parameters.first.flatMap { $0 } ?? 1
                    let count = min(max(requested, 1), terminalRows * 2)
                    flushLiteral()
                    batch.segments.append(.fullScreenScrollUp(count))
                } else {
                    literal.append(contentsOf: sequence)
                }
                continue
            }

            if pendingEscape.count > 64 || byte < 0x20 || byte > 0x3f {
                literal.append(contentsOf: pendingEscape)
                pendingEscape.removeAll(keepingCapacity: true)
            }
        }

        flushLiteral()
        return batch
    }

    mutating func reset() {
        pendingEscape.removeAll(keepingCapacity: true)
        fullScreenScrollRegion = true
    }

    private func plainCSIParameters(_ sequence: [UInt8]) -> [Int?]? {
        guard sequence.count >= 3,
              sequence[0] == 0x1b,
              sequence[1] == 0x5b else { return nil }
        let body = sequence.dropFirst(2).dropLast()
        guard body.allSatisfy({ (0x30...0x39).contains($0) || $0 == 0x3b }) else { return nil }
        if body.isEmpty { return [] }
        return String(decoding: body, as: UTF8.self)
            .split(separator: ";", omittingEmptySubsequences: false)
            .map { $0.isEmpty ? nil : Int($0) }
    }
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

enum PiTerminalPresentation {
    static let fontSizeDefaultsKey = "jarvis.pi-terminal.font-size"
    static let zoomSchemaDefaultsKey = "jarvis.pi-terminal.zoom-schema"
    static let currentZoomSchema = 1
    static let minimumFontSize: CGFloat = 9
    static let defaultFontSize: CGFloat = 18
    static let maximumFontSize: CGFloat = 20
    static let localScrollbackLines = 100_000

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

private final class PiSSHHistorySizeHandler: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = SSHChannelData

    private let onHistorySize: @Sendable (Int) -> Void
    private var parser = PiTerminalHistorySizeParser()

    init(onHistorySize: @escaping @Sendable (Int) -> Void) {
        self.onHistorySize = onHistorySize
    }

    func channelActive(context: ChannelHandlerContext) {
        context.triggerUserOutboundEvent(
            SSHChannelRequestEvent.ExecRequest(
                command: PiTerminalHistoryMonitor.remoteCommand,
                wantReply: false
            ),
            promise: nil
        )
    }

    func channelRead(context: ChannelHandlerContext, data: NIOAny) {
        let payload = unwrapInboundIn(data)
        guard case .byteBuffer(var buffer) = payload.data,
              let bytes = buffer.readBytes(length: buffer.readableBytes),
              !bytes.isEmpty else { return }
        for historySize in parser.consume(bytes) {
            onHistorySize(historySize)
        }
    }
}

private final class PiSSHConnection: @unchecked Sendable {
    private let configuration: PiTerminalConfiguration
    private let trustedHostKey: String?
    private let windowState: PiTerminalWindowState
    private let onOutput: @Sendable ([UInt8]) -> Void
    private let onHistorySize: @Sendable (Int) -> Void
    private let onReady: @Sendable () -> Void
    private let onTrust: @Sendable (PiPendingHostTrust) -> Void
    private let onFailure: @Sendable (Error) -> Void

    private let stateLock = NSLock()
    private var didFail = false
    private var intentionalClose = false
    private var group: EventLoopGroup?
    private var channel: Channel?
    private var sessionChannel: Channel?
    private var historyMonitorChannel: Channel?

    init(
        configuration: PiTerminalConfiguration,
        trustedHostKey: String?,
        initialWindowSize: PiTerminalWindowSize,
        onOutput: @escaping @Sendable ([UInt8]) -> Void,
        onHistorySize: @escaping @Sendable (Int) -> Void,
        onReady: @escaping @Sendable () -> Void,
        onTrust: @escaping @Sendable (PiPendingHostTrust) -> Void,
        onFailure: @escaping @Sendable (Error) -> Void
    ) {
        self.configuration = configuration
        self.trustedHostKey = trustedHostKey
        self.windowState = PiTerminalWindowState(initial: initialWindowSize)
        self.onOutput = onOutput
        self.onHistorySize = onHistorySize
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
        historyMonitorChannel = nil
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
                self.createHistoryMonitorChannel(on: channel)
            }
        }
    }

    private func createHistoryMonitorChannel(on channel: Channel) {
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
                    try childChannel.pipeline.syncOperations.addHandler(
                        PiSSHHistorySizeHandler(onHistorySize: self.onHistorySize)
                    )
                }
            }
            return promise.futureResult
        }.whenSuccess { [weak self] childChannel in
            guard let self else { return }
            self.stateLock.lock()
            self.historyMonitorChannel = childChannel
            self.stateLock.unlock()
        }
        // History metadata is an optional, read-only enhancement. If its child
        // channel is unavailable, terminal output remains live and the existing
        // explicit CSI-S promotion remains the safe fallback.
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

final class PiTerminalHostView: TerminalView, TerminalViewDelegate {
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
    private var outputFilter = PiTerminalOutputFilter()
    private var controlSequenceDiagnostics = PiTerminalControlSequenceDiagnostics()
    private var historyPromotionState = PiTerminalHistoryPromotionState()
    private var pendingRemoteOutput: [[UInt8]] = []
    private var pendingHistoryRows = 0
    private var historyMetadataGeneration = 0
    private var requiredHistoryMetadataGeneration: Int?
    private var rebaselineNextHistorySample = false
    private var pendingOutputDeadline: DispatchWorkItem?
    private var receivedOutputBytes = 0
    private var filteredOutputBytes = 0
    private var promotedScrollRows = 0
    private var metadataPromotedScrollRows = 0
    private var lastOutputDiagnosticUptime: TimeInterval = 0
    private var lastDiagnosticLayoutSize = CGSize.zero
    var outboundBytesObserver: (([UInt8]) -> Void)?
    var isTerminalKeyboardFocused: Bool { keyboardResponder.isFirstResponder }

    private static let scrollDiagnosticsURL: URL = {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("JARVIS-terminal-scroll-diagnostics.log")
    }()

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
        configureNativeTextScrolling()
        // Match the protected tmux history bound locally. SwiftTerm's default
        // 500 rows is too small for one wrapped Pi response and can recycle rows
        // underneath a reader who has scrolled away from the live edge.
        getTerminal().changeHistorySize(PiTerminalPresentation.localScrollbackLines)
        resetScrollDiagnostics()
        recordScrollDiagnostics("init")
        // Pi paints its own inverse-video cursor in the fixed input editor. Keep
        // the terminal hardware cursor hidden so tmux redraw/copy-mode cursor
        // movements can never flash over transcript rows.
        getTerminal().hideCursor()

        addGestureRecognizer(UIPinchGestureRecognizer(target: self, action: #selector(handleFontPinch(_:))))
        // Observe the scroll view's own pan for keyboard dismissal. A second
        // simultaneous pan recognizer can win differently on physical iOS and
        // leave the native scroll view rubber-banding without moving history.
        panGestureRecognizer.addTarget(self, action: #selector(handleNativeTerminalPan(_:)))
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
        if abs(bounds.width - lastDiagnosticLayoutSize.width) >= 8 ||
            abs(bounds.height - lastDiagnosticLayoutSize.height) >= 8 {
            lastDiagnosticLayoutSize = bounds.size
            recordScrollDiagnostics("layout")
        }
    }

    private func resetScrollDiagnostics() {
        pendingOutputDeadline?.cancel()
        pendingOutputDeadline = nil
        pendingRemoteOutput.removeAll(keepingCapacity: false)
        pendingHistoryRows = 0
        historyMetadataGeneration = 0
        requiredHistoryMetadataGeneration = nil
        rebaselineNextHistorySample = false
        historyPromotionState.reset()
        receivedOutputBytes = 0
        filteredOutputBytes = 0
        promotedScrollRows = 0
        metadataPromotedScrollRows = 0
        controlSequenceDiagnostics.reset()
        lastOutputDiagnosticUptime = 0
        try? Data().write(to: Self.scrollDiagnosticsURL, options: .atomic)
    }

    private func recordScrollDiagnostics(_ event: String, pan: UIPanGestureRecognizer? = nil) {
        let terminal = getTerminal()
        let normalLines = terminal.getBufferAsData(kind: .normal).reduce(into: 0) { count, byte in
            if byte == 0x0a { count += 1 }
        }
        let panDetails: String
        if let pan {
            let translation = pan.translation(in: self)
            let velocity = pan.velocity(in: self)
            panDetails = String(
                format: " pan=%ld translation=(%.1f,%.1f) velocity=(%.1f,%.1f)",
                pan.state.rawValue,
                translation.x,
                translation.y,
                velocity.x,
                velocity.y
            )
        } else {
            panDetails = ""
        }
        let operations = controlSequenceDiagnostics.counts
        let line = String(
            format: "%.3f event=%@ bytes=%d/%d promoted=%d/%d tmuxHistory=%d pendingHistory=%d terminal=%dx%d normalLines=%d alt=%d yDisp=%d trimmed=%d region=%d-%d ops=(lf:%d ind:%d csi:%d c1:%d su:%d/%d dl:%d/%d il:%d ed:%d el:%d cup:%d vpa:%d csr:%d/%d) bounds=%.1fx%.1f content=%.1fx%.1f offset=(%.1f,%.1f) inset=(%.1f,%.1f) tracking=%d dragging=%d decelerating=%d keyboard=%d%@\n",
            ProcessInfo.processInfo.systemUptime,
            event,
            receivedOutputBytes,
            filteredOutputBytes,
            promotedScrollRows,
            metadataPromotedScrollRows,
            historyPromotionState.latestHistorySize ?? -1,
            pendingHistoryRows,
            terminal.cols,
            terminal.rows,
            normalLines,
            terminal.isCurrentBufferAlternate ? 1 : 0,
            terminal.buffer.yDisp,
            terminal.buffer.totalLinesTrimmed,
            terminal.buffer.scrollTop + 1,
            terminal.buffer.scrollBottom + 1,
            operations.lineFeeds,
            operations.indexes,
            operations.csiSequences,
            operations.c1CSIBytes,
            operations.scrollUpCommands,
            operations.scrollUpRows,
            operations.deleteLineCommands,
            operations.deleteLineRows,
            operations.insertLineCommands,
            operations.eraseDisplayCommands,
            operations.eraseLineCommands,
            operations.cursorPositionCommands,
            operations.verticalPositionCommands,
            operations.scrollRegionCommands,
            operations.restrictedScrollRegionCommands,
            bounds.width,
            bounds.height,
            contentSize.width,
            contentSize.height,
            contentOffset.x,
            contentOffset.y,
            adjustedContentInset.top,
            adjustedContentInset.bottom,
            isTracking ? 1 : 0,
            isDragging ? 1 : 0,
            isDecelerating ? 1 : 0,
            isTerminalKeyboardFocused ? 1 : 0,
            panDetails
        )
        guard let data = line.data(using: .utf8),
              let handle = try? FileHandle(forWritingTo: Self.scrollDiagnosticsURL) else { return }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
            try handle.close()
        } catch {
            try? handle.close()
        }
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

    private func configureNativeTextScrolling() {
        // TerminalView is already a UIScrollView. Let its real contentOffset,
        // rubber-banding, and deceleration move SwiftTerm's retained text just
        // like ordinary webpage content. No parallel gesture surface or visual
        // snapshot is involved.
        alwaysBounceVertical = true
        isDirectionalLockEnabled = true
        decelerationRate = .normal

        // SwiftTerm installs long-press and multi-tap selection recognizers.
        // Keep the accepted phone interaction: vertical drags belong solely to
        // the native scroll view, while copy-response and paste remain on the
        // fixed key deck.
        for recognizer in gestureRecognizers ?? [] {
            if recognizer is UILongPressGestureRecognizer {
                recognizer.isEnabled = false
            } else if let tap = recognizer as? UITapGestureRecognizer,
                      tap.numberOfTapsRequired > 1 {
                tap.isEnabled = false
            }
        }
    }

    override func mouseModeChanged(source: Terminal) {
        // Intentionally do not call super. Pi may enable terminal mouse mode,
        // but finger scrolling is always local and read-only on iPhone. Calling
        // SwiftTerm's implementation would install a remote mouse-drag gesture.
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
                    self.queueRemoteOutput(bytes)
                }
            },
            onHistorySize: { [weak self] historySize in
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.connectionID == id else { return }
                    self.observeRemoteHistorySize(historySize)
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
        outputFilter.reset()
        resetScrollDiagnostics()
        let terminal = getTerminal()
        terminal.resetToInitialState()
        terminal.hideCursor()
        clearSelection()
    }

    private func queueRemoteOutput(_ bytes: [UInt8]) {
        guard !bytes.isEmpty else { return }
        pendingRemoteOutput.append(bytes)
        guard requiredHistoryMetadataGeneration == nil else { return }

        // Wait for one metadata sample taken after these terminal bytes arrived.
        // tmux has already updated history_size before painting its synchronized
        // cursor-addressed redraw, so this short read-only barrier lets us retain
        // displaced rows before applying that redraw locally.
        requiredHistoryMetadataGeneration = historyMetadataGeneration + 1
        let requiredGeneration = requiredHistoryMetadataGeneration
        let deadline = DispatchWorkItem { [weak self] in
            guard let self,
                  self.requiredHistoryMetadataGeneration == requiredGeneration else { return }
            // Metadata must never stall live rendering. If the companion channel
            // misses its 150 ms bound, render immediately and rebaseline its next
            // sample rather than applying a late scroll to the wrong screen.
            self.rebaselineNextHistorySample = true
            self.flushPendingRemoteOutput()
        }
        pendingOutputDeadline?.cancel()
        pendingOutputDeadline = deadline
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: deadline)
    }

    private func observeRemoteHistorySize(_ historySize: Int) {
        historyMetadataGeneration += 1
        if rebaselineNextHistorySample {
            historyPromotionState.rebaseline(historySize: historySize)
            rebaselineNextHistorySample = false
        } else {
            pendingHistoryRows += historyPromotionState.observe(historySize: historySize)
        }

        guard let required = requiredHistoryMetadataGeneration,
              historyMetadataGeneration >= required else { return }
        flushPendingRemoteOutput()
    }

    private func flushPendingRemoteOutput() {
        guard !pendingRemoteOutput.isEmpty else {
            requiredHistoryMetadataGeneration = nil
            pendingOutputDeadline?.cancel()
            pendingOutputDeadline = nil
            return
        }
        let chunks = pendingRemoteOutput
        let historyRows = pendingHistoryRows
        pendingRemoteOutput.removeAll(keepingCapacity: true)
        pendingHistoryRows = 0
        requiredHistoryMetadataGeneration = nil
        pendingOutputDeadline?.cancel()
        pendingOutputDeadline = nil
        consumeRemoteOutput(chunks, historyRows: historyRows)
    }

    func consumeRemoteOutput(_ bytes: [UInt8]) {
        consumeRemoteOutput(bytes, historyRows: 0)
    }

    func consumeRemoteOutput(_ bytes: [UInt8], historyRows: Int) {
        consumeRemoteOutput([bytes], historyRows: historyRows)
    }

    private func consumeRemoteOutput(_ chunks: [[UInt8]], historyRows: Int) {
        // tmux wraps every attached outer client in DECSET 1049 even when the
        // pane itself (Pi regular mode) uses the main screen. SwiftTerm correctly
        // gives its alternate buffer no history, so accepting that wrapper would
        // make native scrolling bounce without any rows to reveal. Suppress only
        // tmux's local-client envelope before parsing; pane bytes, SSH input, the
        // persistent session, and tmux configuration remain untouched.
        var batches: [PiTerminalOutputBatch] = []
        var explicitScrollRows = 0
        for bytes in chunks {
            receivedOutputBytes += bytes.count
            controlSequenceDiagnostics.consume(bytes, terminalRows: getTerminal().rows)
            let batch = outputFilter.consume(bytes, terminalRows: getTerminal().rows)
            explicitScrollRows += batch.segments.reduce(into: 0) { count, segment in
                if case .fullScreenScrollUp(let rows) = segment { count += rows }
            }
            batches.append(batch)
        }

        // Pi regular mode wraps every update in synchronized output. tmux keeps
        // the pane's real history but can reduce the client stream to CUP + EL
        // screen redraws, erasing all scroll semantics. The companion channel
        // reports only history_size. Promote its positive delta before applying
        // the corresponding redraw, preserving exactly rows received after this
        // phone attached without fetching history text or mutating tmux.
        let metadataRows = max(0, historyRows - explicitScrollRows)
        if metadataRows > 0 {
            promotedScrollRows += metadataRows
            metadataPromotedScrollRows += metadataRows
            for _ in 0..<metadataRows {
                getTerminal().scroll()
            }
        }

        // Keep CSI-S as a no-metadata fallback. Subtracting it above prevents a
        // history-size sample and an explicit tmux scroll command from promoting
        // the same displaced row twice.
        for batch in batches {
            for segment in batch.segments {
                switch segment {
                case .bytes(let filtered):
                    filteredOutputBytes += filtered.count
                    feed(byteArray: filtered[...])
                case .fullScreenScrollUp(let count):
                    promotedScrollRows += count
                    for _ in 0..<count {
                        getTerminal().scroll()
                    }
                }
            }
        }

        // SwiftTerm owns contentSize, contentOffset, momentum, history freeze,
        // and live-edge following. Never write contentOffset from an SSH output
        // callback: physical Pi repaint packets can arrive during a finger drag,
        // and even a same-value write can interfere with UIScrollView tracking.
        let now = ProcessInfo.processInfo.systemUptime
        if now - lastOutputDiagnosticUptime >= 0.5 {
            lastOutputDiagnosticUptime = now
            recordScrollDiagnostics("output")
        }
    }

    func disconnectSSH() {
        connectionID = UUID()
        pendingOutputDeadline?.cancel()
        pendingOutputDeadline = nil
        pendingRemoteOutput.removeAll(keepingCapacity: false)
        pendingHistoryRows = 0
        requiredHistoryMetadataGeneration = nil
        rebaselineNextHistorySample = false
        historyPromotionState.reset()
        let connection = sshConnection
        sshConnection = nil
        connection?.disconnect()
        controlLatched = false
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

    @objc private func handleNativeTerminalPan(_ recognizer: UIPanGestureRecognizer) {
        if recognizer.state == .began || recognizer.state == .ended ||
            recognizer.state == .cancelled || recognizer.state == .failed {
            recordScrollDiagnostics("pan", pan: recognizer)
        }
        guard isTerminalKeyboardFocused,
              recognizer.state == .ended,
              recognizer.translation(in: self).y >= 44 else { return }
        _ = resignFirstResponder()
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
        recordScrollDiagnostics("size-\(newCols)x\(newRows)")
        sshConnection?.resize(cols: newCols, rows: newRows)
    }

    func send(source: TerminalView, data: ArraySlice<UInt8>) {
        outboundBytesObserver?(Array(data))
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
