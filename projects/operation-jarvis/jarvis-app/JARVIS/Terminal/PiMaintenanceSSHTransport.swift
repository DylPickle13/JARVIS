import Foundation
import JARVISKit
import NIOCore
import NIOPosix
import NIOSSH

private enum PiMaintenanceTransportError: LocalizedError {
    case missingTrustedHost
    case invalidRequest
    case invalidResponse
    case responseTooLarge
    case rejected(String)
    case timedOut
    case unavailable

    var errorDescription: String? {
        switch self {
        case .missingTrustedHost:
            return "Connect and trust the Mac in Pi Terminal settings before restarting sessions."
        case .invalidRequest:
            return "The session maintenance request was invalid."
        case .invalidResponse:
            return "The Mac returned an invalid session maintenance response."
        case .responseTooLarge:
            return "The Mac returned an oversized session maintenance response."
        case .rejected(let message):
            return message
        case .timedOut:
            return "The secure session maintenance timed out."
        case .unavailable:
            return "The secure session maintenance channel is unavailable."
        }
    }
}

private final class PiMaintenanceOperation: @unchecked Sendable {
    private let lock = NSLock()
    private let group: MultiThreadedEventLoopGroup
    private var completion: (@Sendable (Result<PiMaintenanceResult, Error>) -> Void)?
    private var parent: Channel?
    private var child: Channel?
    private var finished = false

    init(
        group: MultiThreadedEventLoopGroup,
        completion: @escaping @Sendable (Result<PiMaintenanceResult, Error>) -> Void
    ) {
        self.group = group
        self.completion = completion
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + .seconds(12)) { [weak self] in
            self?.finish(.failure(PiMaintenanceTransportError.timedOut))
        }
    }

    func bind(parent: Channel) {
        lock.lock()
        if finished {
            lock.unlock()
            parent.close(promise: nil)
            return
        }
        self.parent = parent
        lock.unlock()
    }

    func bind(child: Channel) {
        lock.lock()
        if finished {
            lock.unlock()
            child.close(promise: nil)
            return
        }
        self.child = child
        lock.unlock()
    }

    func finish(_ result: Result<PiMaintenanceResult, Error>) {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        let parent = self.parent
        let child = self.child
        let completion = self.completion
        self.completion = nil
        lock.unlock()

        child?.close(promise: nil)
        parent?.close(promise: nil)
        completion?(result)
        group.shutdownGracefully { _ in }
    }
}

private final class PiMaintenanceParentErrorHandler: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = Any
    private let operation: PiMaintenanceOperation

    init(operation: PiMaintenanceOperation) {
        self.operation = operation
    }

    func errorCaught(context: ChannelHandlerContext, error: Error) {
        operation.finish(.failure(error))
        context.close(promise: nil)
    }

    func channelInactive(context: ChannelHandlerContext) {
        operation.finish(.failure(PiMaintenanceTransportError.unavailable))
        context.fireChannelInactive()
    }
}

private final class PiMaintenanceSessionHandler: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = SSHChannelData

    private let command: String
    private let request: Data
    private let operation: PiMaintenanceOperation
    private var response = Data()
    private var standardError = Data()

    init(
        command: String,
        request: Data,
        operation: PiMaintenanceOperation
    ) {
        self.command = command
        self.request = request
        self.operation = operation
    }

    func channelActive(context: ChannelHandlerContext) {
        context.triggerUserOutboundEvent(
            SSHChannelRequestEvent.ExecRequest(command: command, wantReply: false),
            promise: nil
        )
        var buffer = context.channel.allocator.buffer(capacity: request.count)
        buffer.writeBytes(request)
        context.channel.writeAndFlush(
            SSHChannelData(type: .channel, data: .byteBuffer(buffer))
        ).whenComplete { result in
            switch result {
            case .success:
                context.channel.close(mode: .output, promise: nil)
            case .failure(let error):
                self.operation.finish(.failure(error))
                context.close(promise: nil)
            }
        }
    }

    func channelRead(context: ChannelHandlerContext, data: NIOAny) {
        let payload = unwrapInboundIn(data)
        guard case .byteBuffer(var buffer) = payload.data,
              let bytes = buffer.readBytes(length: buffer.readableBytes),
              !bytes.isEmpty else { return }
        if payload.type == .stdErr {
            if standardError.count < 512 {
                standardError.append(contentsOf: bytes.prefix(512 - standardError.count))
            }
            return
        }
        guard payload.type == .channel else { return }
        response.append(contentsOf: bytes)
        if response.count > 4_096 {
            operation.finish(.failure(PiMaintenanceTransportError.responseTooLarge))
            context.close(promise: nil)
        }
    }

    func errorCaught(context: ChannelHandlerContext, error: Error) {
        operation.finish(.failure(error))
        context.close(promise: nil)
    }

    func channelInactive(context: ChannelHandlerContext) {
        do {
            let acknowledgement = try JSONDecoder().decode(
                PiMaintenanceResult.self,
                from: response
            )
            guard acknowledgement.state != "rejected" else {
                throw PiMaintenanceTransportError.rejected(acknowledgement.message)
            }
            operation.finish(.success(acknowledgement))
        } catch let error as PiMaintenanceTransportError {
            operation.finish(.failure(error))
        } catch {
            if let message = String(data: standardError, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
               !message.isEmpty {
                operation.finish(.failure(PiMaintenanceTransportError.rejected(String(message.prefix(240)))))
            } else {
                operation.finish(.failure(PiMaintenanceTransportError.invalidResponse))
            }
        }
        context.fireChannelInactive()
    }
}

struct PiMaintenanceSSHTransport {
    static let command = "/usr/bin/python3 /Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app/scripts/jarvis-mobile-maintenance.py"

    func send(
        action: String,
        operationID: String,
        configuration: PiTerminalConfiguration,
        trustedHostKey: String?
    ) async throws -> PiMaintenanceResult {
        guard let trustedHostKey, !trustedHostKey.isEmpty else {
            throw PiMaintenanceTransportError.missingTrustedHost
        }
        var request = try JSONSerialization.data(withJSONObject: ["action": action, "operationID": operationID])
        request.append(0x0A)
        guard request.count <= 1_024 else {
            throw PiMaintenanceTransportError.invalidRequest
        }

        return try await withCheckedThrowingContinuation { continuation in
            let group = MultiThreadedEventLoopGroup(numberOfThreads: 1)
            let operation = PiMaintenanceOperation(group: group) { result in
                continuation.resume(with: result)
            }
            let serverAuth = PiHostKeyValidator(
                host: configuration.host,
                port: configuration.port,
                trustedKey: trustedHostKey,
                requestTrust: { pending in pending.reject() }
            )
            let username = configuration.username
            let password = configuration.password
            let bootstrap = ClientBootstrap(group: group)
                .channelInitializer { channel in
                    channel.eventLoop.makeCompletedFuture {
                        let userAuth = SimplePasswordDelegate(username: username, password: password)
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
                        try sync.addHandler(PiMaintenanceParentErrorHandler(operation: operation))
                    }
                }
                .channelOption(
                    ChannelOptions.socket(SocketOptionLevel(SOL_SOCKET), SO_REUSEADDR),
                    value: 1
                )
                .channelOption(
                    ChannelOptions.socket(SocketOptionLevel(IPPROTO_TCP), TCP_NODELAY),
                    value: 1
                )

            bootstrap.connect(host: configuration.host, port: configuration.port).whenComplete { result in
                switch result {
                case .failure(let error):
                    operation.finish(.failure(error))
                case .success(let parent):
                    operation.bind(parent: parent)
                    parent.pipeline.handler(type: NIOSSHHandler.self).flatMap { sshHandler in
                        let promise = parent.eventLoop.makePromise(of: Channel.self)
                        sshHandler.createChannel(promise, channelType: .session) { child, channelType in
                            guard channelType == .session else {
                                return child.eventLoop.makeFailedFuture(PiSSHError.invalidChannelType)
                            }
                            return child.eventLoop.makeCompletedFuture {
                                guard let synchronousOptions = child.syncOptions else {
                                    throw PiSSHError.invalidChannelType
                                }
                                try synchronousOptions.setOption(.allowRemoteHalfClosure, value: true)
                                try child.pipeline.syncOperations.addHandler(
                                    PiMaintenanceSessionHandler(
                                        command: Self.command,
                                        request: request,
                                        operation: operation
                                    )
                                )
                                operation.bind(child: child)
                            }
                        }
                        return promise.futureResult
                    }.whenFailure { error in
                        operation.finish(.failure(error))
                    }
                }
            }
        }
    }
}

struct PiMaintenanceResult: Decodable, Sendable {
    let operationID: String
    let state: String
    let completed: Int
    let message: String
}
