import Foundation

// Shared connection lifecycle state (used by both host apps).
public enum ConnectionState: Equatable, Sendable {
    case idle
    case connecting
    case connected
    case failed
}

// MARK: - Health

public struct HealthResponse: Codable, Equatable, Sendable {
    public let ok: Bool
    public let version: String?
    public let uptimeSeconds: Double?

    public init(ok: Bool, version: String? = nil, uptimeSeconds: Double? = nil) {
        self.ok = ok
        self.version = version
        self.uptimeSeconds = uptimeSeconds
    }
}

// MARK: - Developer signing renewal

public enum SigningRenewalStep: String, CaseIterable, Sendable {
    case preparing
    case provisioning
    case building
    case auditing
    case installingIPhone
    case installingWatch
    case verifying
}

public enum SigningRenewalStepState: Equatable, Sendable {
    case completed
    case current
    case pending
    case failed
}

public struct SigningRenewalStatus: Codable, Equatable, Sendable {
    public let ok: Bool
    public let available: Bool
    public let phase: String
    public let running: Bool
    public let message: String?
    public let startedAt: String?
    public let updatedAt: String?
    public let completedAt: String?
    public let expiresAt: String?
    public let iPhoneInstalled: Bool?
    public let watchInstalled: Bool?
    public let failedPhase: String?

    public init(
        ok: Bool,
        available: Bool,
        phase: String,
        running: Bool,
        message: String? = nil,
        startedAt: String? = nil,
        updatedAt: String? = nil,
        completedAt: String? = nil,
        expiresAt: String? = nil,
        iPhoneInstalled: Bool? = nil,
        watchInstalled: Bool? = nil,
        failedPhase: String? = nil
    ) {
        self.ok = ok
        self.available = available
        self.phase = phase
        self.running = running
        self.message = message
        self.startedAt = startedAt
        self.updatedAt = updatedAt
        self.completedAt = completedAt
        self.expiresAt = expiresAt
        self.iPhoneInstalled = iPhoneInstalled
        self.watchInstalled = watchInstalled
        self.failedPhase = failedPhase
    }

    public var expirationDate: Date? { date(from: expiresAt) }
    public var startedDate: Date? { date(from: startedAt) }
    public var updatedDate: Date? { date(from: updatedAt) }
    public var completedDate: Date? { date(from: completedAt) }

    public var activeStep: SigningRenewalStep? {
        if phase == "failed", let failedPhase {
            return SigningRenewalStep(rawValue: failedPhase)
        }
        return SigningRenewalStep(rawValue: phase)
    }

    public var completedStepCount: Int {
        if phase == "succeeded" { return SigningRenewalStep.allCases.count }
        guard let activeStep,
              let index = SigningRenewalStep.allCases.firstIndex(of: activeStep) else { return 0 }
        return index
    }

    public var displayedStepNumber: Int? {
        if phase == "succeeded" { return SigningRenewalStep.allCases.count }
        guard let activeStep,
              let index = SigningRenewalStep.allCases.firstIndex(of: activeStep) else { return nil }
        return index + 1
    }

    public func state(for step: SigningRenewalStep) -> SigningRenewalStepState {
        if phase == "succeeded" { return .completed }
        guard let activeStep,
              let activeIndex = SigningRenewalStep.allCases.firstIndex(of: activeStep),
              let stepIndex = SigningRenewalStep.allCases.firstIndex(of: step) else { return .pending }
        if stepIndex < activeIndex { return .completed }
        if stepIndex > activeIndex { return .pending }
        return phase == "failed" ? .failed : .current
    }

    private func date(from value: String?) -> Date? {
        guard let value else { return nil }
        return ISO8601DateFormatter().date(from: value)
    }
}

// MARK: - State snapshot

public struct StateSnapshot: Codable, Equatable, Sendable {
    public let ok: Bool
    public let loading: Bool?
    public let refreshing: Bool?
    public let stale: Bool?
    public let ageSeconds: Double?
    public let generatedAt: String?
    public let version: String?
    public let uptimeSeconds: Double?
    public let summary: Summary?
    public let subsystems: Subsystems?
    public let subsystemsMeta: [String: SubsystemMetadata]?

    public init(
        ok: Bool,
        loading: Bool? = nil,
        refreshing: Bool? = nil,
        stale: Bool? = nil,
        ageSeconds: Double? = nil,
        generatedAt: String? = nil,
        version: String? = nil,
        uptimeSeconds: Double? = nil,
        summary: Summary? = nil,
        subsystems: Subsystems? = nil,
        subsystemsMeta: [String: SubsystemMetadata]? = nil
    ) {
        self.ok = ok
        self.loading = loading
        self.refreshing = refreshing
        self.stale = stale
        self.ageSeconds = ageSeconds
        self.generatedAt = generatedAt
        self.version = version
        self.uptimeSeconds = uptimeSeconds
        self.summary = summary
        self.subsystems = subsystems
        self.subsystemsMeta = subsystemsMeta
    }
}

public struct SubsystemMetadata: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let updatedAt: String?
    public let ageSeconds: Double?
    public let stale: Bool?
    public let refreshing: Bool?
    public let error: String?
}

public struct Summary: Codable, Equatable, Sendable {
    public let plugsOn: Int?
    public let plugsTotal: Int?
    public let purifierOn: Bool?
    public let pm25: Int?
    public let piActive: Int?
}

public struct Subsystems: Codable, Equatable, Sendable {
    public let plugs: PlugsSubsystem?
    public let purifier: PurifierSubsystem?
    public let pi: PiSubsystem?
    public let services: ServicesSubsystem?
    public let network: NetworkSubsystem?
    public let codexQuota: CodexQuotaSubsystem?
}

public struct PlugsSubsystem: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let stale: Bool?
    public let refreshing: Bool?
    public let updatedAt: String?
    public let count: Int?
    public let onCount: Int?
    public let plugs: [String: PlugState]?
    public let error: String?
    public let lastError: String?
}

public struct PlugState: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let stale: Bool?
    public let isOn: Bool?
    public let host: String?
    public let rssi: Int?
    public let alias: String?
    public let error: String?
}

public extension StateSnapshot {
    /// Returns a snapshot with one confirmed desired-state plug result applied.
    /// This lets an interactive widget render the command response immediately
    /// while its next direct daemon refresh is being scheduled.
    func applyingConfirmedPlugState(name: String, isOn: Bool, at date: Date = Date()) -> StateSnapshot {
        guard let subsystems, let currentPlugs = subsystems.plugs else { return self }
        var plugMap = currentPlugs.plugs ?? [:]
        let current = plugMap[name]
        plugMap[name] = PlugState(
            ok: true,
            stale: false,
            isOn: isOn,
            host: current?.host,
            rssi: current?.rssi,
            alias: current?.alias,
            error: nil
        )
        let onCount = plugMap.values.filter { $0.isOn == true }.count
        let updatedAt = ISO8601DateFormatter().string(from: date)
        let updatedPlugs = PlugsSubsystem(
            ok: true,
            stale: false,
            refreshing: false,
            updatedAt: updatedAt,
            count: currentPlugs.count ?? plugMap.count,
            onCount: onCount,
            plugs: plugMap,
            error: nil,
            lastError: nil
        )
        let updatedSubsystems = Subsystems(
            plugs: updatedPlugs,
            purifier: subsystems.purifier,
            pi: subsystems.pi,
            services: subsystems.services,
            network: subsystems.network,
            codexQuota: subsystems.codexQuota
        )
        let updatedSummary = summary.map {
            Summary(
                plugsOn: onCount,
                plugsTotal: $0.plugsTotal ?? plugMap.count,
                purifierOn: $0.purifierOn,
                pm25: $0.pm25,
                piActive: $0.piActive
            )
        }
        return StateSnapshot(
            ok: ok,
            loading: loading,
            refreshing: refreshing,
            stale: stale,
            ageSeconds: ageSeconds,
            generatedAt: generatedAt,
            version: version,
            uptimeSeconds: uptimeSeconds,
            summary: updatedSummary,
            subsystems: updatedSubsystems,
            subsystemsMeta: subsystemsMeta
        )
    }
}

public struct PurifierPendingCommand: Codable, Equatable, Sendable {
    public let setting: String
    public let value: String?
    public let level: Int?
}

public struct PurifierSubsystem: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let stale: Bool?
    public let refreshing: Bool?
    public let updatedAt: String?
    public let verificationPending: Bool?
    public let pendingCommand: PurifierPendingCommand?
    public let isOn: Bool?
    public let power: String?
    public let mode: String?
    public let fanLevel: Int?
    public let fanSetLevel: Int?
    public let pm25: Int?
    public let airQualityLevel: Int?
    public let filterLife: Int?
    public let childLock: Bool?
    public let display: String?
    public let timer: String?
    public let name: String?
    public let model: String?
    public let error: String?
    public let lastError: String?
}

public struct PiMobileSession: Codable, Equatable, Sendable {
    public let sessionID: Int
    public let active: Bool?
}

public struct PiSubsystem: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let stale: Bool?
    public let refreshing: Bool?
    public let updatedAt: String?
    public let active: Int?
    public let localActive: Int?
    public let localTotal: Int?
    public let rpcActive: Int?
    public let mobileSessions: [PiMobileSession]?
    public let error: String?
    public let lastError: String?
}

public struct CodexQuotaSubsystem: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let available: Bool?
    public let stale: Bool?
    public let refreshing: Bool?
    public let updatedAt: String?
    public let checkedAt: String?
    public let planType: String?
    public let allowed: Bool?
    public let limitReached: Bool?
    public let weekly: CodexQuotaWindow?
    public let fiveHour: CodexQuotaWindow?
    public let fiveHourEnforced: Bool?
    public let fiveHourStatus: String?
    public let creditBalance: Double?
    public let error: String?
    public let lastError: String?
}

public struct CodexQuotaWindow: Codable, Equatable, Sendable {
    public let usedPercent: Double?
    public let remainingPercent: Double?
    public let resetAfterSeconds: Int?
    public let resetAt: String?
}

public enum CodexQuotaPresentationPolicy {
    public static let criticalRemainingPercent = 30.0

    public static func isCritical(remainingPercent: Double) -> Bool {
        remainingPercent < criticalRemainingPercent
    }
}

/// The state endpoint's services entry is a map in the daemon JSON. This
/// struct remains permissive for compatibility with older snapshots.
public struct ServicesSubsystem: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let stale: Bool?
    public let refreshing: Bool?
    public let updatedAt: String?
    public let label: String?
    public let running: Bool?
    public let pid: Int?
    public let description: String?
    public let error: String?
}

public struct NetworkSubsystem: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let stale: Bool?
    public let refreshing: Bool?
    public let updatedAt: String?
    public let macLanIp: String?
    public let tailscaleIp: String?
    public let error: String?
}

// MARK: - Events

public struct EventItem: Codable, Equatable, Identifiable, Sendable {
    public var id: Int { seq }
    public let seq: Int
    public let receivedAt: String?
    public let source: String?
    public let eventType: String?
    public let action: String?
    public let ok: Bool?
    public let summary: String?
    public let error: String?
    public let at: String?

    public init(
        seq: Int,
        receivedAt: String? = nil,
        source: String? = nil,
        eventType: String? = nil,
        action: String? = nil,
        ok: Bool? = nil,
        summary: String? = nil,
        error: String? = nil,
        at: String? = nil
    ) {
        self.seq = seq
        self.receivedAt = receivedAt
        self.source = source
        self.eventType = eventType
        self.action = action
        self.ok = ok
        self.summary = summary
        self.error = error
        self.at = at
    }
}

public struct EventsResponse: Codable, Equatable, Sendable {
    public let ok: Bool
    public let count: Int
    public let events: [EventItem]
}

// MARK: - Commands

public struct CommandRequest: Codable, Sendable {
    public let action: String
    public let params: [String: JSONValue]?

    public init(action: String, params: [String: JSONValue]? = nil) {
        self.action = action
        self.params = params
    }
}

public struct WatchCommandError: Codable, Equatable, Sendable {
    public let message: String

    public init(message: String) {
        self.message = message
    }
}

public struct CommandResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let action: String?
    public let error: String?
    public let plug: PlugCommandData?
    public let airPurifier: PurifierCommandData?
    public let summary: String?

    public var purifierVerificationPending: Bool {
        guard case .bool(let pending)? = airPurifier?.data?["verification_pending"] else { return false }
        return pending
    }

    public init(
        ok: Bool,
        action: String? = nil,
        error: String? = nil,
        plug: PlugCommandData? = nil,
        airPurifier: PurifierCommandData? = nil,
        summary: String? = nil
    ) {
        self.ok = ok
        self.action = action
        self.error = error
        self.plug = plug
        self.airPurifier = airPurifier
        self.summary = summary
    }
}

public struct PlugCommandData: Codable, Equatable, Sendable {
    public let name: String?
    public let is_on: Bool?
    public let host: String?
    public let rssi: Int?
    public let alias: String?

    public init(name: String? = nil, is_on: Bool? = nil, host: String? = nil, rssi: Int? = nil, alias: String? = nil) {
        self.name = name
        self.is_on = is_on
        self.host = host
        self.rssi = rssi
        self.alias = alias
    }
}

public struct PurifierCommandData: Codable, Equatable, Sendable {
    public let ok: Bool?
    public let data: [String: JSONValue]?
}

// MARK: - Services control

public struct ServiceActionResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let service: String?
    public let action: String?
    public let label: String?
    public let displayName: String?
    public let loaded: Bool?
    public let running: Bool?
    public let pid: Int?
    public let description: String?
    public let sortOrder: Int?
    public let critical: Bool?
    public let configured: Bool?
    public let allowedActions: [String]?
    public let returncode: Int?
    public let stderr: String?
    public let error: String?
    public let known: [String]?
}

public struct ServicesListResponse: Codable, Equatable, Sendable {
    public let ok: Bool
    public let services: [String: ServiceActionResult]
}

// MARK: - Scheduled jobs

public struct ScheduledJobsSummary: Codable, Equatable, Sendable {
    public let total: Int
    public let enabled: Int
    public let running: Int
    public let errors: Int
}

public struct ScheduledJob: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let kind: String
    public let schedule: String
    public let enabled: Bool
    public let nextRunAt: String?
    public let lastRunAt: String?
    public let lastStatus: String?
    public let runCount: Int
    public let description: String?
    public let lastSilentSuccessAt: String?
    public let lastOutputAt: String?
    public let lastErrorAt: String?
    public let consecutiveErrors: Int?
}

public struct ScheduledJobsResponse: Codable, Equatable, Sendable {
    public let ok: Bool
    public let generatedAt: String?
    public let summary: ScheduledJobsSummary
    public let jobs: [ScheduledJob]
    public let error: String?
}

public struct ScheduledJobResult: Codable, Equatable, Identifiable, Sendable {
    public let sequence: Int
    public let id: String
    public let jobId: String
    public let jobName: String
    public let status: String
    public let outputKind: String
    public let startedAt: String
    public let finishedAt: String
    public let durationSeconds: Double
    public let exitCode: Int?
    public let title: String
    public let summary: String
    public let output: String?
    public let error: String?
    public let truncated: Bool
}

public struct ScheduledJobResultsResponse: Codable, Equatable, Sendable {
    public let ok: Bool
    public let generatedAt: String?
    public let results: [ScheduledJobResult]
    public let hasMore: Bool
    public let nextAfter: Int
    public let error: String?
}

// MARK: - Flexible JSON value

public enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let b = try? container.decode(Bool.self) { self = .bool(b) }
        else if let i = try? container.decode(Int.self) { self = .number(Double(i)) }
        else if let d = try? container.decode(Double.self) { self = .number(d) }
        else if let s = try? container.decode(String.self) { self = .string(s) }
        else if let a = try? container.decode([JSONValue].self) { self = .array(a) }
        else if let o = try? container.decode([String: JSONValue].self) { self = .object(o) }
        else { self = .null }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    public var stringValue: String? {
        if case .string(let value) = self { return value }
        return nil
    }

    public var intValue: Int? {
        if case .number(let value) = self { return Int(value) }
        return nil
    }

    public var boolValue: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }
}
