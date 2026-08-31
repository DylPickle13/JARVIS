import Foundation
import NIOCore
import NIOSSH

struct PiAttachmentUncheckedResult: @unchecked Sendable {
    let value: Result<PiAttachmentWireResponse, Error>
}

final class PiAttachmentResultBox: @unchecked Sendable {
    private let lock = NSLock()
    private var finished = false
    private let completion: @Sendable (Result<PiAttachmentWireResponse, Error>) -> Void

    init(completion: @escaping @Sendable (Result<PiAttachmentWireResponse, Error>) -> Void) {
        self.completion = completion
    }

    var isFinished: Bool {
        lock.lock()
        let value = finished
        lock.unlock()
        return value
    }

    func finish(_ result: Result<PiAttachmentWireResponse, Error>) {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        lock.unlock()
        completion(result)
    }
}

final class PiAttachmentSSHOperation: @unchecked Sendable {
    private let lock = NSLock()
    private let resultBox: PiAttachmentResultBox
    private var channel: Channel?
    private var stopped = false

    init(
        resultBox: PiAttachmentResultBox,
        timeout: DispatchTimeInterval = .seconds(5 * 60)
    ) {
        self.resultBox = resultBox
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + timeout) { [weak self] in
            self?.expire()
        }
    }

    func bind(channel: Channel) {
        lock.lock()
        if stopped || resultBox.isFinished {
            lock.unlock()
            channel.close(promise: nil)
            return
        }
        self.channel = channel
        lock.unlock()
    }

    func cancel() {
        lock.lock()
        guard !stopped else {
            lock.unlock()
            return
        }
        stopped = true
        let channel = self.channel
        lock.unlock()
        resultBox.finish(.failure(PiAttachmentTransportError.cancelled))
        channel?.close(promise: nil)
    }

    var isCancelled: Bool {
        lock.lock()
        let value = stopped
        lock.unlock()
        return value
    }

    private func expire() {
        lock.lock()
        guard !stopped, !resultBox.isFinished else {
            lock.unlock()
            return
        }
        stopped = true
        let channel = self.channel
        lock.unlock()
        if let channel {
            // Let channelInactive distinguish a fully sent reconcile (ambiguous)
            // from a request that could not have committed.
            channel.close(promise: nil)
        } else {
            resultBox.finish(.failure(PiAttachmentTransportError.timedOut))
        }
    }
}

private final class PiAttachmentOutboundStreamer: @unchecked Sendable {
    private let requestFrame: Data
    private let files: [PiAttachmentLocalFile]
    private let progress: @Sendable (Int64, Int64) -> Void
    private let resultBox: PiAttachmentResultBox
    private let operation: PiAttachmentSSHOperation
    private let queue = DispatchQueue(label: "com.operation-jarvis.pi-attachment-upload", qos: .userInitiated)
    private var sentBytes: Int64 = 0
    private let totalBytes: Int64

    init(
        requestFrame: Data,
        files: [PiAttachmentLocalFile],
        progress: @escaping @Sendable (Int64, Int64) -> Void,
        resultBox: PiAttachmentResultBox,
        operation: PiAttachmentSSHOperation
    ) {
        self.requestFrame = requestFrame
        self.files = files
        self.progress = progress
        self.resultBox = resultBox
        self.operation = operation
        self.totalBytes = files.reduce(0) { $0 + $1.sizeBytes }
    }

    func start(on channel: Channel, didFinishSending: @escaping @Sendable () -> Void) {
        write(requestFrame, on: channel) { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error): self.fail(error, channel: channel)
            case .success:
                self.queue.async {
                    self.streamFile(at: 0, on: channel, didFinishSending: didFinishSending)
                }
            }
        }
    }

    private func streamFile(
        at index: Int,
        on channel: Channel,
        didFinishSending: @escaping @Sendable () -> Void
    ) {
        guard !operation.isCancelled, !resultBox.isFinished else { return }
        guard index < files.count else {
            channel.eventLoop.execute {
                didFinishSending()
                channel.close(mode: .output, promise: nil)
            }
            return
        }

        let file = files[index]
        do {
            let values = try file.url.resourceValues(forKeys: [
                .isRegularFileKey,
                .isSymbolicLinkKey,
                .fileSizeKey,
            ])
            guard values.isRegularFile == true,
                  values.isSymbolicLink != true,
                  Int64(values.fileSize ?? -1) == file.sizeBytes else {
                throw PiAttachmentTransportError.rejected("A prepared attachment changed before upload.")
            }
            let handle = try FileHandle(forReadingFrom: file.url)
            streamChunk(
                from: handle,
                file: file,
                fileBytesSent: 0,
                nextIndex: index + 1,
                channel: channel,
                didFinishSending: didFinishSending
            )
        } catch {
            fail(error, channel: channel)
        }
    }

    private func streamChunk(
        from handle: FileHandle,
        file: PiAttachmentLocalFile,
        fileBytesSent: Int64,
        nextIndex: Int,
        channel: Channel,
        didFinishSending: @escaping @Sendable () -> Void
    ) {
        guard !operation.isCancelled, !resultBox.isFinished else {
            try? handle.close()
            return
        }
        do {
            guard let chunk = try handle.read(upToCount: PiAttachmentProtocol.chunkSize), !chunk.isEmpty else {
                try handle.close()
                guard fileBytesSent == file.sizeBytes else {
                    throw PiAttachmentTransportError.rejected("A prepared attachment changed size during upload.")
                }
                streamFile(at: nextIndex, on: channel, didFinishSending: didFinishSending)
                return
            }
            let nextFileBytes = fileBytesSent + Int64(chunk.count)
            guard nextFileBytes <= file.sizeBytes else {
                try? handle.close()
                throw PiAttachmentTransportError.rejected("A prepared attachment exceeded its declared size.")
            }
            write(chunk, on: channel) { [weak self] result in
                guard let self else {
                    try? handle.close()
                    return
                }
                switch result {
                case .failure(let error):
                    try? handle.close()
                    self.fail(error, channel: channel)
                case .success:
                    self.sentBytes += Int64(chunk.count)
                    self.progress(self.sentBytes, self.totalBytes)
                    self.queue.async {
                        self.streamChunk(
                            from: handle,
                            file: file,
                            fileBytesSent: nextFileBytes,
                            nextIndex: nextIndex,
                            channel: channel,
                            didFinishSending: didFinishSending
                        )
                    }
                }
            }
        } catch {
            try? handle.close()
            fail(error, channel: channel)
        }
    }

    private func write(
        _ data: Data,
        on channel: Channel,
        completion: @escaping @Sendable (Result<Void, Error>) -> Void
    ) {
        channel.eventLoop.execute {
            guard channel.isActive else {
                completion(.failure(PiAttachmentTransportError.unavailable))
                return
            }
            var buffer = channel.allocator.buffer(capacity: data.count)
            buffer.writeBytes(data)
            channel.writeAndFlush(
                SSHChannelData(type: .channel, data: .byteBuffer(buffer))
            ).whenComplete(completion)
        }
    }

    private func fail(_ error: Error, channel: Channel) {
        resultBox.finish(.failure(error))
        channel.close(promise: nil)
    }
}

final class PiSSHAttachmentSessionHandler: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = SSHChannelData

    private let request: PiAttachmentWireRequest
    private let receiverCommand: String
    private let streamer: PiAttachmentOutboundStreamer
    private let resultBox: PiAttachmentResultBox
    private let operation: PiAttachmentSSHOperation
    private var response = Data()
    private var standardError = Data()
    private var expectedResponseBytes: Int?
    private var didFinishSending = false

    init(
        request: PiAttachmentWireRequest,
        receiverCommand: String,
        requestFrame: Data,
        files: [PiAttachmentLocalFile],
        progress: @escaping @Sendable (Int64, Int64) -> Void,
        resultBox: PiAttachmentResultBox,
        operation: PiAttachmentSSHOperation
    ) {
        self.request = request
        self.receiverCommand = receiverCommand
        self.resultBox = resultBox
        self.operation = operation
        self.streamer = PiAttachmentOutboundStreamer(
            requestFrame: requestFrame,
            files: files,
            progress: progress,
            resultBox: resultBox,
            operation: operation
        )
    }

    func channelActive(context: ChannelHandlerContext) {
        guard !operation.isCancelled else {
            context.close(promise: nil)
            return
        }
        context.triggerUserOutboundEvent(
            SSHChannelRequestEvent.ExecRequest(
                command: receiverCommand,
                wantReply: false
            ),
            promise: nil
        )
        streamer.start(on: context.channel) { [weak self] in
            self?.didFinishSending = true
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
        if response.count > PiAttachmentProtocol.responseLimit + 4 {
            finishWithoutResponse(underlying: PiAttachmentTransportError.responseTooLarge)
            context.close(promise: nil)
            return
        }
        do {
            if expectedResponseBytes == nil,
               let length = try PiAttachmentProtocol.responseLength(from: response) {
                expectedResponseBytes = length + 4
            }
            if let expectedResponseBytes, response.count > expectedResponseBytes {
                throw PiAttachmentTransportError.invalidResponse
            }
        } catch {
            finishWithoutResponse(underlying: error)
            context.close(promise: nil)
        }
    }

    func errorCaught(context: ChannelHandlerContext, error: Error) {
        finishWithoutResponse(underlying: error)
        context.close(promise: nil)
    }

    func channelInactive(context: ChannelHandlerContext) {
        guard !resultBox.isFinished else {
            context.fireChannelInactive()
            return
        }
        do {
            if let expectedResponseBytes,
               response.count == expectedResponseBytes {
                let decoded = try PiAttachmentProtocol.decodeResponse(response)
                guard decoded.version == PiAttachmentProtocol.version,
                      decoded.requestID == request.requestID,
                      (decoded.ok
                        ? decoded.operation == request.operation
                        : decoded.operation == "error") else {
                    throw PiAttachmentTransportError.invalidResponse
                }
                resultBox.finish(.success(decoded))
            } else {
                finishWithoutResponse(underlying: nil)
            }
        } catch {
            finishWithoutResponse(underlying: error)
        }
        context.fireChannelInactive()
    }

    private func finishWithoutResponse(underlying: Error?) {
        if request.operation == "reconcile",
           didFinishSending,
           let requestID = UUID(uuidString: request.requestID),
           let generation = request.expectedGeneration {
            resultBox.finish(.failure(
                PiAttachmentTransportError.ambiguous(
                    requestID: requestID,
                    generation: generation
                )
            ))
            return
        }
        if !standardError.isEmpty,
           let message = String(data: standardError, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !message.isEmpty {
            resultBox.finish(.failure(PiAttachmentTransportError.rejected(String(message.prefix(500)))))
        } else {
            resultBox.finish(.failure(underlying ?? PiAttachmentTransportError.unavailable))
        }
    }
}
