import Foundation

/// Read-only, versioned activity telemetry. Not part of persisted Home/Watch/
/// widget snapshots, and never contains oMLX credentials or inference content.
public struct OMLXSnapshot: Decodable, Equatable, Sendable {
    public static let serverIDs = ["mac-mini-64", "mac-mini-16"]
    public let version: Int
    public let servers: [OMLXServerStatus]

    private enum CodingKeys: String, CodingKey { case ok, version, servers }
    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        version = try values.decode(Int.self, forKey: .version)
        servers = try values.decode([OMLXServerStatus].self, forKey: .servers)
        guard try values.decode(Bool.self, forKey: .ok), version == 1,
              servers.count == Self.serverIDs.count,
              Set(servers.map(\.id)) == Set(Self.serverIDs) else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                debugDescription: "Unsupported oMLX status response."))
        }
    }
}

public enum OMLXPhase: String, Sendable {
    case ready, loading, prefill, generating, processing, queued, unknown

    public var title: String {
        switch self {
        case .ready: return "Ready"
        case .loading: return "Loading"
        case .prefill: return "Processing prompt"
        case .generating: return "Generating"
        case .processing: return "Processing"
        case .queued: return "Queued"
        case .unknown: return "Unknown"
        }
    }
}

public struct OMLXServerStatus: Decodable, Equatable, Identifiable, Sendable {
    public let id: String
    public let ok: Bool?
    public let stale: Bool?
    public let ageSeconds: Double?
    public let lastSuccessAt: String?
    public let error: String?
    public let models: [OMLXModelStatus]?
    public let memoryUsedBytes: Double?
    public let memoryLimitBytes: Double?
    public let memoryKind: String?
    public let memoryPressure: String?

    /// Add elapsed client time to the *source* age, not the age of the last
    /// successful HTTP poll. requestStartedAt also conservatively counts RTT.
    public func sourceAge(requestStartedAt: Date?, now: Date) -> Double? {
        guard let ageSeconds, ageSeconds.isFinite, ageSeconds >= 0,
              let requestStartedAt else { return nil }
        return ageSeconds + max(0, now.timeIntervalSince(requestStartedAt))
    }

    public func isFresh(requestStartedAt: Date?, now: Date) -> Bool {
        guard ok == true, stale == false, models != nil,
              let age = sourceAge(requestStartedAt: requestStartedAt, now: now) else { return false }
        return age <= 6
    }

    public var busyModels: [OMLXModelStatus] { (models ?? []).filter { $0.phase != .ready } }
    public var idleModels: [OMLXModelStatus] { (models ?? []).filter { $0.phase == .ready } }
    public var phase: OMLXPhase {
        guard let models else { return .unknown }
        let phases = Set(models.map { $0.phase }.filter { $0 != .ready })
        if phases.count > 1 { return .processing }
        return phases.first ?? .ready
    }
}

public struct OMLXModelStatus: Decodable, Equatable, Identifiable, Sendable {
    public let id: String
    public let isLoading: Bool
    public let activeRequests: Int
    public let queuedRequests: Int
    public let requests: [OMLXRequestStatus]
    public let estimatedBytes: Double?
    public let observedBytes: Double?
    public let loadingElapsedSeconds: Double?

    public var phase: OMLXPhase {
        guard activeRequests >= 0, queuedRequests >= 0 else { return .unknown }
        if isLoading { return .loading }
        let working = Set(requests.map(\.phase).filter { $0 != .queued })
        if working.count > 1 { return .processing }
        if let phase = working.first { return phase }
        if activeRequests > 0 { return .processing }
        if queuedRequests > 0 || !requests.isEmpty { return .queued }
        return .ready
    }
}

public struct OMLXRequestStatus: Decodable, Equatable, Identifiable, Sendable {
    public let id: String
    private let phaseValue: String
    public let processedTokens: Int?
    public let totalTokens: Int?
    public let generatedTokens: Int?
    public let tokensPerSecond: Double?
    public let elapsedSeconds: Double?
    public let lastActivityAgeSeconds: Double?
    public let queuePosition: Int?

    private enum CodingKeys: String, CodingKey {
        case id, phaseValue = "phase", processedTokens, totalTokens, generatedTokens
        case tokensPerSecond, elapsedSeconds, lastActivityAgeSeconds, queuePosition
    }
    public var phase: OMLXPhase { OMLXPhase(rawValue: phaseValue) ?? .unknown }
    public var prefillFraction: Double? {
        guard phase == .prefill, let processedTokens, let totalTokens,
              processedTokens >= 0, totalTokens > 0 else { return nil }
        return min(1, Double(processedTokens) / Double(totalTokens))
    }
}
