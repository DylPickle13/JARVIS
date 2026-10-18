import Foundation

/// Presentation-only memory. Never deletes history, changes freshness or issues a request.
public struct SystemTelemetrySession: Equatable, Sendable {
    public private(set) var recoveryFloor: Date?
    private var sawProblem = false
    private var lastObservation: Date?

    public init() {}

    public mutating func observe(state: SystemHealthState, observedAt: Date?, trusted: Bool, now: Date = Date()) {
        guard trusted, let observedAt, observedAt <= now,
              lastObservation.map({ observedAt > $0 }) ?? true else { return }
        lastObservation = observedAt
        if state != .healthy { sawProblem = true }
        else if sawProblem {
            // A confirmed cached healthy observation, not an inferred physical recovery time.
            advance(to: observedAt)
            sawProblem = false
        }
    }

    public mutating func advance(to date: Date) {
        if recoveryFloor.map({ date > $0 }) ?? true { recoveryFloor = date }
    }
}

public struct SystemTelemetryWindow: Equatable, Sendable {
    public let buckets: [SystemHistoryBucket]
    public let title: String
    public let notice: String?
    public let muted: Bool
    public let recoveryCandidate: Date?
    public var start: Date? { buckets.first?.start }
    public var end: Date? { buckets.last?.end }
    /// The represented source, NOT a query/render timestamp. Partial/mixed tails have no beacon.
    public var beaconSource: Date? {
        guard !muted, let last = buckets.last, Self.isSolid(last),
              last.state != .unknown, last.state != .inactive else { return nil }
        return last.sourceObservedAt.flatMap(SystemHistoryDates.parse)
    }

    public static func isSolid(_ bucket: SystemHistoryBucket) -> Bool {
        !bucket.hasGap && !bucket.mixed && bucket.coverageSeconds > 0
    }
    public static func isHealthy(_ bucket: SystemHistoryBucket) -> Bool {
        isSolid(bucket) && bucket.state == .healthy && bucket.observedState == .healthy
    }

    public init(response: SystemHistoryResponse?, current: SystemHealthState, trusted: Bool,
                floor: Date? = nil, now: Date = Date()) {
        let original = response?.series.first { $0.id == "overall" }?.buckets ?? []
        // Whole buckets only: never invent the order of mixed observations across a reset.
        var visible = original.filter { bucket in
            guard let start = bucket.start, let end = bucket.end, start < end, end <= now else { return false }
            return floor.map { start >= $0 } ?? true
        }
        var candidate: Date?
        var heading = floor == nil ? "Recorded observations" : "Since recovery"
        var message: String?
        if !trusted {
            heading = "Cached trace"
            message = "Current trace unverified"
        } else if current == .healthy {
            if let lastProblem = visible.lastIndex(where: { !Self.isHealthy($0) }) {
                candidate = visible[lastProblem].end
                visible = Array(visible.dropFirst(lastProblem + 1))
                heading = "Since recovery"
            } else if floor == nil { heading = "Healthy observations" }
            if visible.isEmpty { message = "Waiting for verified healthy history" }
        } else {
            heading = current == .issue ? "Current incident" : "Unverified observations"
            if let last = visible.last, Self.isHealthy(last) {
                // Current state and recorder are independent; don't present a healthy endpoint
                // as if the new incident were already recorded.
                visible = []
                message = "Waiting for current history"
            } else if let context = visible.lastIndex(where: Self.isHealthy) {
                visible = Array(visible[context...])
            }
        }
        if response == nil || original.isEmpty { message = "History unavailable" }
        buckets = visible
        title = heading
        notice = message
        muted = !trusted
        recoveryCandidate = trusted && current == .healthy ? candidate : nil
    }

    public func bucket(at fraction: Double) -> SystemHistoryBucket? {
        guard fraction.isFinite, let start, let end, end > start, !buckets.isEmpty else { return nil }
        let date = start.addingTimeInterval(min(1, max(0, fraction)) * end.timeIntervalSince(start))
        return buckets.first { bucket in
            guard let lo = bucket.start, let hi = bucket.end else { return false }
            return date >= lo && (date < hi || (date == end && hi == end))
        }
    }

    public static func evidence(_ bucket: SystemHistoryBucket) -> String {
        let lo = bucket.start?.formatted(date: .omitted, time: .shortened) ?? "?"
        let hi = bucket.end?.formatted(date: .omitted, time: .shortened) ?? "?"
        return "\(lo)–\(hi). \(bucket.state.title). \(Int(bucket.coverageSeconds)) seconds observed, "
            + "\(Int(bucket.missingSeconds)) seconds missing. "
            + (bucket.mixed ? "Mixed bucket; event order and exact incident duration unknown. " : "")
            + bucket.reasonCodes.joined(separator: ", ")
    }
}

/// A beacon may react only to advancing source evidence, never redraws or repeat cache reads.
public struct SystemTelemetryBeacon: Equatable, Sendable {
    private var latest: Date?
    public init() {}
    public mutating func receive(_ source: Date?, allowed: Bool) -> Bool {
        guard let source else { return false }
        let isNew = latest.map { source > $0 } ?? false
        if latest.map({ source > $0 }) ?? true { latest = source }
        return allowed && isNew
    }
}

public extension SystemDashboardPresentation {
    var telemetryExceptions: [SystemVisualGroup] {
        visualGroups.filter { $0.state != .healthy }
    }
}
