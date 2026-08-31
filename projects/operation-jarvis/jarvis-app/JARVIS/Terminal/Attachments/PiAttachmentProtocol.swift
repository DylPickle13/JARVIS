import Foundation
import JARVISKit

struct PiAttachmentLimits: Codable, Equatable, Sendable {
    let maxFiles: Int
    let maxFileBytes: Int64
    let maxTotalBytes: Int64

    static let safeFallback = PiAttachmentLimits(
        maxFiles: 10,
        maxFileBytes: 50 * 1024 * 1024,
        maxTotalBytes: 100 * 1024 * 1024
    )

    var isValid: Bool {
        (1...100).contains(maxFiles)
            && (1...(2 * 1024 * 1024 * 1024)).contains(maxFileBytes)
            && (1...(4 * 1024 * 1024 * 1024)).contains(maxTotalBytes)
    }
}

struct PiRemoteAttachment: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let name: String
    let sizeBytes: Int64
    let sha256: String
    let mimeType: String
}

struct PiAttachmentSnapshot: Equatable, Sendable {
    let generation: String
    let revision: Int
    let limits: PiAttachmentLimits
    let staged: [PiRemoteAttachment]
}

struct PiAttachmentLocalFile: Equatable, Identifiable, Sendable {
    let id: UUID
    let displayName: String
    let url: URL
    let sizeBytes: Int64
    let sha256: String
}

enum PiAttachmentDraftItem: Equatable, Identifiable, Sendable {
    case remote(PiRemoteAttachment)
    case local(PiAttachmentLocalFile)

    var id: String {
        switch self {
        case .remote(let item): "remote:\(item.id)"
        case .local(let item): "local:\(item.id.uuidString)"
        }
    }

    var displayName: String {
        switch self {
        case .remote(let item): item.name
        case .local(let item): item.displayName
        }
    }

    var sizeBytes: Int64 {
        switch self {
        case .remote(let item): item.sizeBytes
        case .local(let item): item.sizeBytes
        }
    }

    var remoteID: String? {
        guard case .remote(let item) = self else { return nil }
        return item.id
    }

    var localFile: PiAttachmentLocalFile? {
        guard case .local(let item) = self else { return nil }
        return item
    }
}

struct PiAttachmentWireFile: Codable, Equatable, Sendable {
    let name: String
    let sizeBytes: Int64
    let sha256: String
}

struct PiAttachmentWireRequest: Codable, Equatable, Sendable {
    let version: Int
    let operation: String
    let requestID: String
    let expectedGeneration: String?
    let expectedRevision: Int?
    let keepIds: [String]?
    let files: [PiAttachmentWireFile]?
    let targetRequestID: String?

    static func snapshot(requestID: UUID = UUID()) -> Self {
        Self(
            version: PiAttachmentProtocol.version,
            operation: "snapshot",
            requestID: requestID.uuidString.lowercased(),
            expectedGeneration: nil,
            expectedRevision: nil,
            keepIds: nil,
            files: nil,
            targetRequestID: nil
        )
    }

    static func reconcile(
        requestID: UUID,
        snapshot: PiAttachmentSnapshot,
        keepIds: [String],
        files: [PiAttachmentLocalFile]
    ) -> Self {
        Self(
            version: PiAttachmentProtocol.version,
            operation: "reconcile",
            requestID: requestID.uuidString.lowercased(),
            expectedGeneration: snapshot.generation,
            expectedRevision: snapshot.revision,
            keepIds: keepIds,
            files: files.map {
                PiAttachmentWireFile(
                    name: $0.displayName,
                    sizeBytes: $0.sizeBytes,
                    sha256: $0.sha256
                )
            },
            targetRequestID: nil
        )
    }

    static func requestStatus(
        requestID: UUID = UUID(),
        generation: String,
        targetRequestID: UUID
    ) -> Self {
        Self(
            version: PiAttachmentProtocol.version,
            operation: "requestStatus",
            requestID: requestID.uuidString.lowercased(),
            expectedGeneration: generation,
            expectedRevision: nil,
            keepIds: nil,
            files: nil,
            targetRequestID: targetRequestID.uuidString.lowercased()
        )
    }
}

struct PiAttachmentWireResponse: Codable, Equatable, Sendable {
    let version: Int
    let ok: Bool
    let operation: String
    let requestID: String?
    let generation: String?
    let revision: Int?
    let limits: PiAttachmentLimits?
    let staged: [PiRemoteAttachment]?
    let targetRequestID: String?
    let state: String?
    let committedResponse: PiAttachmentCommittedResponse?
    let error: String?

    func validatedSnapshot(
        expectedOperation: String,
        expectedRequestID: String,
        expectedGeneration: String? = nil,
        expectedCommittedRevision: Int? = nil
    ) throws -> PiAttachmentSnapshot {
        guard version == PiAttachmentProtocol.version,
              requestID == expectedRequestID,
              expectedGeneration == nil || generation == expectedGeneration else {
            throw PiAttachmentTransportError.invalidResponse
        }
        guard ok else {
            guard operation == "error" else {
                throw PiAttachmentTransportError.invalidResponse
            }
            throw PiAttachmentTransportError.rejected(
                String((error ?? "The attachment operation failed.").prefix(500))
            )
        }
        guard operation == expectedOperation,
              let generation,
              let revision,
              expectedCommittedRevision == nil || revision == expectedCommittedRevision,
              let limits,
              let staged else {
            throw PiAttachmentTransportError.invalidResponse
        }
        return try PiAttachmentProtocol.validatedSnapshot(
            generation: generation,
            revision: revision,
            limits: limits,
            staged: staged
        )
    }
}

struct PiAttachmentCommittedResponse: Codable, Equatable, Sendable {
    let version: Int
    let ok: Bool
    let operation: String
    let requestID: String?
    let generation: String?
    let revision: Int?
    let limits: PiAttachmentLimits?
    let staged: [PiRemoteAttachment]?

    func validatedSnapshot(
        expectedRequestID: String,
        expectedGeneration: String,
        expectedCommittedRevision: Int
    ) throws -> PiAttachmentSnapshot {
        guard version == PiAttachmentProtocol.version,
              ok,
              operation == "reconcile",
              requestID == expectedRequestID,
              generation == expectedGeneration,
              revision == expectedCommittedRevision,
              let generation,
              let revision,
              let limits,
              let staged else {
            throw PiAttachmentTransportError.invalidResponse
        }
        return try PiAttachmentProtocol.validatedSnapshot(
            generation: generation,
            revision: revision,
            limits: limits,
            staged: staged
        )
    }
}

enum PiAttachmentTransportError: LocalizedError, Equatable, Sendable {
    case unavailable
    case cancelled
    case timedOut
    case invalidRequest
    case invalidResponse
    case responseTooLarge
    case rejected(String)
    case ambiguous(requestID: UUID, generation: String)

    var errorDescription: String? {
        switch self {
        case .unavailable:
            "The live Pi attachment endpoint is unavailable."
        case .cancelled:
            "Attachment selection was cancelled."
        case .timedOut:
            "The attachment operation timed out."
        case .invalidRequest:
            "The attachment request could not be encoded."
        case .invalidResponse:
            "The live Pi attachment endpoint returned an invalid response."
        case .responseTooLarge:
            "The live Pi attachment endpoint returned too much data."
        case .rejected(let message):
            message
        case .ambiguous:
            "The attachment result could not be confirmed. No automatic retry was performed."
        }
    }
}

enum PiAttachmentProtocol {
    static let version = 1
    static let headerLimit = 64 * 1024
    static let responseLimit = 64 * 1024
    static let chunkSize = 64 * 1024
    static let maximumSafeWireInteger = 9_007_199_254_740_991
    static let receiverCommand = "/opt/homebrew/bin/node /Users/dylanrapanan/JARVIS/.pi/scripts/pi-attach-mobile-receiver.mjs"

    static func receiverCommand(for slot: JARVISTerminalSlot) -> String {
        "\(receiverCommand) --slot \(slot.rawValue)"
    }

    private static let hardMaxFiles = 100
    private static let hardMaxFileBytes: Int64 = 2 * 1024 * 1024 * 1024
    private static let hardMaxTotalBytes: Int64 = 4 * 1024 * 1024 * 1024

    static func requestFrame(_ request: PiAttachmentWireRequest) throws -> Data {
        guard isValidRequest(request) else {
            throw PiAttachmentTransportError.invalidRequest
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let body: Data
        do {
            body = try encoder.encode(request)
        } catch {
            throw PiAttachmentTransportError.invalidRequest
        }
        guard !body.isEmpty, body.count <= headerLimit else {
            throw PiAttachmentTransportError.invalidRequest
        }
        var length = UInt32(body.count).bigEndian
        var result = Data(bytes: &length, count: MemoryLayout<UInt32>.size)
        result.append(body)
        return result
    }

    static func responseLength(from data: Data) throws -> Int? {
        guard data.count >= 4 else { return nil }
        let length = data.prefix(4).reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
        guard length > 0, length <= responseLimit else {
            throw PiAttachmentTransportError.responseTooLarge
        }
        return Int(length)
    }

    static func decodeResponse(_ data: Data) throws -> PiAttachmentWireResponse {
        guard let length = try responseLength(from: data), data.count == length + 4 else {
            throw PiAttachmentTransportError.invalidResponse
        }
        let body = Data(data.dropFirst(4))
        guard String(data: body, encoding: .utf8) != nil else {
            throw PiAttachmentTransportError.invalidResponse
        }
        do {
            return try JSONDecoder().decode(PiAttachmentWireResponse.self, from: body)
        } catch {
            throw PiAttachmentTransportError.invalidResponse
        }
    }

    private static func isValidRequest(_ request: PiAttachmentWireRequest) -> Bool {
        guard request.version == version,
              request.requestID.range(
                of: "^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                options: .regularExpression
              ) != nil else {
            return false
        }

        switch request.operation {
        case "snapshot":
            return request.expectedGeneration == nil
                && request.expectedRevision == nil
                && request.keepIds == nil
                && request.files == nil
                && request.targetRequestID == nil
        case "reconcile":
            guard let generation = request.expectedGeneration,
                  generation.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil,
                  let revision = request.expectedRevision,
                  (0...maximumSafeWireInteger).contains(revision),
                  let keepIds = request.keepIds,
                  let files = request.files,
                  request.targetRequestID == nil,
                  keepIds.count + files.count <= hardMaxFiles,
                  Set(keepIds).count == keepIds.count,
                  keepIds.allSatisfy({
                    $0.range(
                        of: "^[0-9a-f-]{1,128}$",
                        options: .regularExpression
                    ) != nil
                  }) else {
                return false
            }
            var totalBytes: Int64 = 0
            for file in files {
                guard !file.name.isEmpty,
                      file.name.utf8.count <= 160,
                      PiAttachmentTemporaryStore.sanitizeDisplayName(file.name) == file.name,
                      (0...hardMaxFileBytes).contains(file.sizeBytes),
                      file.sha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
                    return false
                }
                let (nextTotal, overflow) = totalBytes.addingReportingOverflow(file.sizeBytes)
                guard !overflow, nextTotal <= hardMaxTotalBytes else { return false }
                totalBytes = nextTotal
            }
            return true
        case "requestStatus":
            return request.expectedGeneration?.range(
                of: "^[0-9a-f]{32}$",
                options: .regularExpression
            ) != nil
                && request.expectedRevision == nil
                && request.keepIds == nil
                && request.files == nil
                && request.targetRequestID?.range(
                    of: "^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                    options: .regularExpression
                ) != nil
        default:
            return false
        }
    }

    static func validatedSnapshot(
        generation: String,
        revision: Int,
        limits: PiAttachmentLimits,
        staged: [PiRemoteAttachment]
    ) throws -> PiAttachmentSnapshot {
        guard generation.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil,
              (0...maximumSafeWireInteger).contains(revision),
              limits.isValid,
              staged.count <= limits.maxFiles else {
            throw PiAttachmentTransportError.invalidResponse
        }

        var ids = Set<String>()
        var totalBytes: Int64 = 0
        for item in staged {
            guard item.id.range(
                of: "^[0-9a-f-]{1,128}$",
                options: .regularExpression
            ) != nil,
                  ids.insert(item.id).inserted,
                  !item.name.isEmpty,
                  item.name.utf8.count <= 160,
                  PiAttachmentTemporaryStore.sanitizeDisplayName(item.name) == item.name,
                  item.sizeBytes >= 0,
                  item.sizeBytes <= limits.maxFileBytes,
                  item.sha256.range(
                    of: "^[0-9a-f]{64}$",
                    options: .regularExpression
                  ) != nil,
                  item.mimeType.utf8.count <= 128,
                  item.mimeType.range(
                    of: "^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$",
                    options: [.regularExpression, .caseInsensitive]
                  ) != nil else {
                throw PiAttachmentTransportError.invalidResponse
            }
            let (nextTotal, overflow) = totalBytes.addingReportingOverflow(item.sizeBytes)
            guard !overflow else { throw PiAttachmentTransportError.invalidResponse }
            totalBytes = nextTotal
        }
        guard totalBytes <= limits.maxTotalBytes else {
            throw PiAttachmentTransportError.invalidResponse
        }
        return PiAttachmentSnapshot(
            generation: generation.lowercased(),
            revision: revision,
            limits: limits,
            staged: staged
        )
    }
}
