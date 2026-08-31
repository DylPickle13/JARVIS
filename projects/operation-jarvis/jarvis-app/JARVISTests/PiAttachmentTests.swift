import CryptoKit
import Foundation
import XCTest
@testable import JARVIS

@MainActor
final class PiAttachmentTests: XCTestCase {
    private let generation = "0123456789abcdef0123456789abcdef"

    func testAttachmentProtocolFramesRequestsAndValidatesExactResponses() throws {
        let requestID = UUID(uuidString: "11111111-2222-4333-8444-555555555555")!
        let request = PiAttachmentWireRequest.snapshot(requestID: requestID)
        let frame = try PiAttachmentProtocol.requestFrame(request)
        XCTAssertEqual(frame.prefix(4).reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }, UInt32(frame.count - 4))

        let remote = PiRemoteAttachment(
            id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            name: "fixture.txt",
            sizeBytes: 7,
            sha256: String(repeating: "a", count: 64),
            mimeType: "text/plain"
        )
        let response = PiAttachmentWireResponse(
            version: PiAttachmentProtocol.version,
            ok: true,
            operation: "snapshot",
            requestID: request.requestID,
            generation: generation,
            revision: 4,
            limits: PiAttachmentLimits(maxFiles: 10, maxFileBytes: 1024, maxTotalBytes: 2048),
            staged: [remote],
            targetRequestID: nil,
            state: nil,
            committedResponse: nil,
            error: nil
        )
        let decoded = try PiAttachmentProtocol.decodeResponse(try framed(response))
        let snapshot = try decoded.validatedSnapshot(
            expectedOperation: request.operation,
            expectedRequestID: request.requestID
        )
        XCTAssertEqual(snapshot.generation, generation)
        XCTAssertEqual(snapshot.revision, 4)
        XCTAssertEqual(snapshot.staged, [remote])
        XCTAssertThrowsError(try decoded.validatedSnapshot(
            expectedOperation: request.operation,
            expectedRequestID: request.requestID,
            expectedGeneration: String(repeating: "f", count: 32)
        ))
        XCTAssertThrowsError(try decoded.validatedSnapshot(
            expectedOperation: request.operation,
            expectedRequestID: request.requestID,
            expectedGeneration: generation,
            expectedCommittedRevision: 5
        ))
    }

    func testAttachmentProtocolRejectsMismatchesAndUnboundedMetadata() throws {
        let request = PiAttachmentWireRequest.snapshot()
        let limits = PiAttachmentLimits(maxFiles: 1, maxFileBytes: 8, maxTotalBytes: 8)
        let invalidRemote = PiRemoteAttachment(
            id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            name: "../unsafe.txt",
            sizeBytes: 9,
            sha256: "not-a-hash",
            mimeType: "text/plain"
        )
        let invalid = PiAttachmentWireResponse(
            version: PiAttachmentProtocol.version,
            ok: true,
            operation: "reconcile",
            requestID: request.requestID,
            generation: generation,
            revision: 0,
            limits: limits,
            staged: [invalidRemote],
            targetRequestID: nil,
            state: nil,
            committedResponse: nil,
            error: nil
        )
        XCTAssertThrowsError(
            try invalid.validatedSnapshot(
                expectedOperation: request.operation,
                expectedRequestID: request.requestID
            )
        ) { XCTAssertEqual($0 as? PiAttachmentTransportError, .invalidResponse) }

        var oversizedLength = UInt32(PiAttachmentProtocol.responseLimit + 1).bigEndian
        let oversizedPrefix = Data(bytes: &oversizedLength, count: 4)
        XCTAssertThrowsError(try PiAttachmentProtocol.responseLength(from: oversizedPrefix)) {
            XCTAssertEqual($0 as? PiAttachmentTransportError, .responseTooLarge)
        }

        let oversizedRequest = PiAttachmentWireRequest(
            version: PiAttachmentProtocol.version,
            operation: "snapshot",
            requestID: UUID().uuidString.lowercased(),
            expectedGeneration: nil,
            expectedRevision: nil,
            keepIds: Array(repeating: String(repeating: "a", count: 128), count: 600),
            files: nil,
            targetRequestID: nil
        )
        XCTAssertThrowsError(try PiAttachmentProtocol.requestFrame(oversizedRequest)) {
            XCTAssertEqual($0 as? PiAttachmentTransportError, .invalidRequest)
        }
    }

    func testAttachmentCommittedStatusRequiresTheOriginalRequestIdentity() throws {
        let target = UUID()
        let remote = PiRemoteAttachment(
            id: UUID().uuidString.lowercased(),
            name: "photo.png",
            sizeBytes: 1,
            sha256: String(repeating: "b", count: 64),
            mimeType: "image/png"
        )
        let committed = PiAttachmentCommittedResponse(
            version: PiAttachmentProtocol.version,
            ok: true,
            operation: "reconcile",
            requestID: target.uuidString.lowercased(),
            generation: generation,
            revision: 1,
            limits: PiAttachmentLimits(maxFiles: 2, maxFileBytes: 10, maxTotalBytes: 10),
            staged: [remote]
        )
        XCTAssertEqual(
            try committed.validatedSnapshot(
                expectedRequestID: target.uuidString.lowercased(),
                expectedGeneration: generation,
                expectedCommittedRevision: 1
            ).staged,
            [remote]
        )
        XCTAssertThrowsError(try committed.validatedSnapshot(
            expectedRequestID: UUID().uuidString.lowercased(),
            expectedGeneration: generation,
            expectedCommittedRevision: 1
        ))
        XCTAssertThrowsError(try committed.validatedSnapshot(
            expectedRequestID: target.uuidString.lowercased(),
            expectedGeneration: String(repeating: "f", count: 32),
            expectedCommittedRevision: 1
        ))
        XCTAssertThrowsError(try committed.validatedSnapshot(
            expectedRequestID: target.uuidString.lowercased(),
            expectedGeneration: generation,
            expectedCommittedRevision: 2
        ))
    }

    func testAttachmentTemporaryStoreStreamsPrivateWorkflowFilesAndCleansIndependently() async throws {
        let manager = FileManager.default
        let root = manager.temporaryDirectory
            .appendingPathComponent("JARVIS-Attachment-Unit-\(UUID().uuidString)", isDirectory: true)
        try manager.createDirectory(at: root, withIntermediateDirectories: false)
        defer { try? manager.removeItem(at: root) }

        let firstSource = root.appendingPathComponent("first report.txt")
        let secondSource = root.appendingPathComponent("second.txt")
        try Data("first\n".utf8).write(to: firstSource)
        try Data("second\n".utf8).write(to: secondSource)

        let store = PiAttachmentTemporaryStore()
        let limits = PiAttachmentLimits(maxFiles: 2, maxFileBytes: 1024, maxTotalBytes: 2048)
        let firstWorkflow = UUID()
        let secondWorkflow = UUID()
        let first = try await store.importSecurityScopedFile(
            firstSource,
            workflowID: firstWorkflow,
            limits: limits
        )
        let second = try await store.importSecurityScopedFile(
            secondSource,
            workflowID: secondWorkflow,
            limits: limits
        )

        XCTAssertEqual(try Data(contentsOf: first.url), Data("first\n".utf8))
        XCTAssertEqual(first.sha256, SHA256.hash(data: Data("first\n".utf8)).hexString)
        XCTAssertLessThanOrEqual(first.displayName.utf8.count, 160)
        let firstMode = try XCTUnwrap(
            manager.attributesOfItem(atPath: first.url.path)[.posixPermissions] as? NSNumber
        )
        XCTAssertEqual(firstMode.intValue & 0o777, 0o600)

        await store.cleanup(workflowID: firstWorkflow)
        XCTAssertFalse(manager.fileExists(atPath: first.url.path))
        XCTAssertTrue(manager.fileExists(atPath: second.url.path))
        await store.cleanup(workflowID: secondWorkflow)
        XCTAssertFalse(manager.fileExists(atPath: second.url.path))
    }

    func testTransferredPhotoCleanupIsConfinedToPrivateTransferDirectories() async throws {
        let manager = FileManager.default
        let limits = PiAttachmentLimits(maxFiles: 1, maxFileBytes: 1024, maxTotalBytes: 1024)
        let store = PiAttachmentTemporaryStore()

        let unrelatedDirectory = manager.temporaryDirectory
            .appendingPathComponent("JARVIS-Unrelated-\(UUID().uuidString)", isDirectory: true)
        try manager.createDirectory(at: unrelatedDirectory, withIntermediateDirectories: false)
        let unrelatedFile = unrelatedDirectory.appendingPathComponent("photo.jpg")
        try Data("not a photo".utf8).write(to: unrelatedFile)
        defer { try? manager.removeItem(at: unrelatedDirectory) }
        do {
            _ = try await store.importTransferredPhoto(
                unrelatedFile,
                displayName: "photo.jpg",
                workflowID: UUID(),
                limits: limits
            )
            XCTFail("An arbitrary temporary parent must not be treated as an owned photo transfer.")
        } catch {
            XCTAssertEqual(error as? PiAttachmentTransportError, .invalidRequest)
        }
        XCTAssertTrue(manager.fileExists(atPath: unrelatedFile.path))

        let transferDirectory = manager.temporaryDirectory
            .appendingPathComponent("JARVIS-Pi-Photo-\(UUID().uuidString)", isDirectory: true)
        try manager.createDirectory(at: transferDirectory, withIntermediateDirectories: false)
        let transferFile = transferDirectory.appendingPathComponent(UUID().uuidString.lowercased())
        try Data("photo bytes".utf8).write(to: transferFile)
        let workflowID = UUID()
        let imported = try await store.importTransferredPhoto(
            transferFile,
            displayName: "photo.jpg",
            workflowID: workflowID,
            limits: limits
        )
        XCTAssertFalse(manager.fileExists(atPath: transferDirectory.path))
        XCTAssertEqual(try Data(contentsOf: imported.url), Data("photo bytes".utf8))
        await store.cleanup(workflowID: workflowID)
        XCTAssertFalse(manager.fileExists(atPath: imported.url.path))
    }

    func testAttachmentTemporaryStoreSanitizesNamesByUTF8BytesAndHonorsCancellation() async throws {
        let sanitized = PiAttachmentTemporaryStore.sanitizeDisplayName(
            "../" + String(repeating: "📎", count: 100) + ".txt"
        )
        XCTAssertFalse(sanitized.contains("/"))
        XCTAssertLessThanOrEqual(sanitized.utf8.count, 160)

        let manager = FileManager.default
        let source = manager.temporaryDirectory
            .appendingPathComponent("JARVIS-Cancel-\(UUID().uuidString).bin")
        try Data(repeating: 0x5a, count: 1024 * 1024).write(to: source)
        defer { try? manager.removeItem(at: source) }

        let store = PiAttachmentTemporaryStore()
        let workflowID = UUID()
        let task = Task {
            try await store.importSecurityScopedFile(
                source,
                workflowID: workflowID,
                limits: PiAttachmentLimits(
                    maxFiles: 1,
                    maxFileBytes: 2 * 1024 * 1024,
                    maxTotalBytes: 2 * 1024 * 1024
                )
            )
        }
        task.cancel()
        do {
            _ = try await task.value
            XCTFail("A cancelled attachment import must not complete.")
        } catch is CancellationError {
            // Expected.
        }
        await store.cleanup(workflowID: workflowID)
    }

    func testAttachmentOperationTimeoutStartsBeforeChildChannelBinds() async throws {
        let resultBox = PiAttachmentResultBox { _ in }
        let operation = PiAttachmentSSHOperation(
            resultBox: resultBox,
            timeout: .milliseconds(10)
        )

        try await Task.sleep(for: .milliseconds(100))

        XCTAssertTrue(resultBox.isFinished)
        XCTAssertTrue(operation.isCancelled)
    }

    func testAttachmentReceiverCommandIsFixedAndTakesNoSelectionData() {
        XCTAssertEqual(
            PiAttachmentProtocol.receiverCommand,
            "/opt/homebrew/bin/node /Users/dylanrapanan/JARVIS/.pi/scripts/pi-attach-mobile-receiver.mjs"
        )
        XCTAssertFalse(PiAttachmentProtocol.receiverCommand.contains("%s"))
        XCTAssertFalse(PiAttachmentProtocol.receiverCommand.contains("$"))
    }

    private func framed<T: Encodable>(_ value: T) throws -> Data {
        let body = try JSONEncoder().encode(value)
        var length = UInt32(body.count).bigEndian
        var frame = Data(bytes: &length, count: 4)
        frame.append(body)
        return frame
    }
}

private extension SHA256.Digest {
    var hexString: String {
        map { String(format: "%02x", $0) }.joined()
    }
}
