import Foundation

public enum SystemHistoryWindow: String, Codable, Sendable {
    case hour = "1h", day = "24h", week = "7d"
    public var seconds: Double { switch self { case .hour: return 3600; case .day: return 86400; case .week: return 604800 } }
    public var resolution: Double { switch self { case .hour: return 60; case .day: return 300; case .week: return 1800 } }
    public var bucketCount: Int { Int(seconds / resolution) }
}

public enum SystemHistoryState: String, Codable, CaseIterable, Sendable {
    case inactive, healthy, unknown, degraded, unavailable
    public var title: String { switch self {
        case .inactive: return "Inactive"
        case .healthy: return "Healthy observation"
        case .unknown: return "Unverified"
        case .degraded: return "Degraded"
        case .unavailable: return "Observation unavailable"
    } }
    public var symbol: String { switch self {
        case .inactive: return "pause.circle"
        case .healthy: return "checkmark.circle"
        case .unknown: return "questionmark.circle"
        case .degraded: return "exclamationmark.triangle"
        case .unavailable: return "xmark.circle"
    } }
    public var priority: Int { Self.allCases.firstIndex(of: self)! }
}

public enum SystemHistoryDates {
    public static func parse(_ value: String) -> Date? {
        guard value.count <= 64, value.hasSuffix("Z") || value.range(of: #"[+-]\d{2}:\d{2}$"#, options: .regularExpression) != nil else { return nil }
        return (try? Date.ISO8601FormatStyle(includingFractionalSeconds: true).parse(value))
            ?? (try? Date.ISO8601FormatStyle().parse(value))
    }
}

public struct SystemHistoryBucket: Codable, Equatable, Sendable {
    public let from: String
    public let to: String
    public let state: SystemHistoryState
    public let reasonCodes: [String]
    public let coverageSeconds: Double
    public let stateSeconds: [String: Double]
    public let missingSeconds: Double
    public let mixed: Bool
    public let sourceObservedAt: String?
    public var start: Date? { SystemHistoryDates.parse(from) }
    public var end: Date? { SystemHistoryDates.parse(to) }
    /// Order within an aggregated bucket is unknown. This is a colour key for
    /// observed evidence, not permission to invent a sequence or extend green.
    public var observedState: SystemHistoryState? {
        stateSeconds.filter { $0.value > 0 }.keys.compactMap(SystemHistoryState.init(rawValue:))
            .max { $0.priority < $1.priority }
    }
    public var hasGap: Bool { missingSeconds > 0 }
}

public struct SystemHistorySeries: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let buckets: [SystemHistoryBucket]
    /// Bucket bounds are not exact incident start/end times. Unknown evidence
    /// and uncovered seconds never count as observed failures or healthy time.
    public var inlineSummary: String {
        let issues = buckets.filter {
            ($0.stateSeconds["degraded"] ?? 0) + ($0.stateSeconds["unavailable"] ?? 0) > 0
        }
        let covered = buckets.reduce(0) { $0 + $1.coverageSeconds }
        let missing = buckets.reduce(0) { $0 + $1.missingSeconds }
        let unknown = buckets.reduce(0) { $0 + ($1.stateSeconds["unknown"] ?? 0) }
        let coverage = "\(Int(covered / 60))m observed · \(Int(ceil(missing / 60)))m gaps"
            + (unknown > 0 ? " · \(Int(ceil(unknown / 60)))m unverified" : "")
        guard covered > 0 else { return "No recorded observations · \(coverage)" }
        guard !issues.isEmpty else {
            return "No observed errors · \(coverage)"
        }
        let recent = issues.suffix(2).map { bucket in
            let lo = bucket.start?.formatted(date: .omitted, time: .shortened) ?? "?"
            let hi = bucket.end?.formatted(date: .omitted, time: .shortened) ?? "?"
            let reasons = bucket.reasonCodes.filter { $0 != "current" }
                .map { $0.replacingOccurrences(of: "_", with: " ") }.joined(separator: ", ")
            return "\(lo)–\(hi)\(reasons.isEmpty ? "" : ": " + reasons)"
        }.joined(separator: "\n")
        return "\(issues.count) error buckets · \(coverage)\nLatest error buckets: \(recent)"
    }

    public var title: String { switch id {
        case "services": return "Services"
        case "pi": return "Pi"
        case "network": return "Network"
        case "devices": return "Devices"
        case "overall": return "System"
        case "security": return "Sensor reads"
        default: return id
    } }
}

public struct SystemHistoryResponse: Codable, Equatable, Sendable {
    public let ok: Bool
    public let schemaVersion: Int
    public let scope: String
    public let window: SystemHistoryWindow
    public let from: String
    public let to: String
    public let sampleIntervalSeconds: Int
    public let resolutionSeconds: Int
    public let coverageLeaseSeconds: Int
    public let retentionSeconds: Int
    public let earliestSampleAt: String?
    public let latestSampleAt: String?
    public let series: [SystemHistorySeries]
    public var start: Date? { SystemHistoryDates.parse(from) }
    public var end: Date? { SystemHistoryDates.parse(to) }
    public var latestSample: Date? { latestSampleAt.flatMap(SystemHistoryDates.parse) }

    /// Shared sanitized reason vocabulary for history and cached current health.
    static let allowedReasonCodes: Set<String> = ["current", "optional_inactive", "metadata_missing", "timestamp_invalid",
        "observation_expired", "collector_failed", "loading", "details_missing", "required_service_missing",
        "required_service_stopped", "service_read_failed", "scheduled_check_failed", "scheduled_completion_unknown",
        "service_state_unknown", "device_observation_failed", "device_observation_unknown", "snapshot_failed", "inventory_limit",
        "monitoring_disabled", "not_checked", "sensor_read_failed", "sensor_read_unknown"]

    public func validated(window expected: SystemHistoryWindow, component: String? = nil, now: Date = Date()) throws -> Self {
        func require(_ value: Bool) throws { if !value { throw JarvisError.decoding("Invalid bounded System history response.") } }
        try require(ok && schemaVersion == 1 && scope == "cached_status_health" && window == expected)
        try require(sampleIntervalSeconds == 60 && resolutionSeconds == Int(expected.resolution)
            && coverageLeaseSeconds == 90 && retentionSeconds == 604800)
        guard let start, let end else { throw JarvisError.decoding("Invalid history dates.") }
        try require(abs(end.timeIntervalSince(start) - expected.seconds) < 0.01 && end <= now.addingTimeInterval(5))
        let ids = component.map { Set([$0]) } ?? Set(["services", "pi", "network", "devices", "overall"])
        try require(series.count == ids.count && Set(series.map(\.id)) == ids)
        let earliest = earliestSampleAt.flatMap(SystemHistoryDates.parse)
        let latest = latestSample
        try require(earliestSampleAt == nil || earliest != nil)
        try require(latestSampleAt == nil || latest != nil)
        if let earliest { try require(earliest <= end) }
        if let latest { try require(latest <= end && earliest != nil && latest >= earliest!) }
        let reasons = Self.allowedReasonCodes
        for series in series {
            try require(series.buckets.count == expected.bucketCount)
            for (index, bucket) in series.buckets.enumerated() {
                guard let lo = bucket.start, let hi = bucket.end else { throw JarvisError.decoding("Invalid history bucket dates.") }
                try require(abs(lo.timeIntervalSince(start) - Double(index) * expected.resolution) < 0.01
                    && abs(hi.timeIntervalSince(lo) - expected.resolution) < 0.01)
                try require(bucket.coverageSeconds.isFinite && bucket.missingSeconds.isFinite
                    && bucket.coverageSeconds >= 0 && bucket.missingSeconds >= 0
                    && abs(bucket.coverageSeconds + bucket.missingSeconds - expected.resolution) < 0.01)
                try require(bucket.stateSeconds.count <= SystemHistoryState.allCases.count
                    && bucket.stateSeconds.allSatisfy { SystemHistoryState(rawValue: $0.key) != nil && $0.value.isFinite && $0.value > 0 }
                    && abs(bucket.stateSeconds.values.reduce(0, +) - bucket.coverageSeconds) < 0.01)
                try require(bucket.reasonCodes.count <= reasons.count && Set(bucket.reasonCodes).isSubset(of: reasons))
                var states = bucket.stateSeconds.keys.compactMap(SystemHistoryState.init(rawValue:))
                if bucket.hasGap { states.append(.unknown) }
                let worst = states.max { $0.priority < $1.priority } ?? .unknown
                try require(bucket.state == worst && bucket.mixed == (Set(states).count > 1))
                if let text = bucket.sourceObservedAt {
                    guard let date = SystemHistoryDates.parse(text) else { throw JarvisError.decoding("Invalid source date.") }
                    try require(date <= hi && latest != nil && date <= latest!.addingTimeInterval(0.001))
                }
                if let earliest, let latest {
                    let permittedStart = max(lo, earliest)
                    let permittedEnd = min(hi, latest.addingTimeInterval(Double(coverageLeaseSeconds)))
                    try require(bucket.coverageSeconds <= max(0, permittedEnd.timeIntervalSince(permittedStart)) + 0.01)
                }
                if let earliest, hi <= earliest { try require(bucket.coverageSeconds == 0 && bucket.state == .unknown) }
                if latest == nil { try require(bucket.coverageSeconds == 0) }
            }
        }
        return self
    }
}
