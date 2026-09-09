import Foundation

/// One fixed row per host. Never expands with models or combines request rates.
public struct OMLXServerSummary: Equatable, Identifiable, Sendable {
    public let id: String
    public let serverLabel: String
    public let status: String
    public let metric: String?
    public let accessibilityValue: String
    public let phase: OMLXPhase
    public let fresh: Bool

    public init(id: String, server: OMLXServerStatus?, now: Date, requestStartedAt: Date?,
                available: Bool, checking: Bool = false) {
        self.id = id
        serverLabel = id == "mac-mini-64" ? "64 GB" : "16 GB"
        fresh = available && server?.isFresh(requestStartedAt: requestStartedAt, now: now) == true
        phase = fresh ? (server?.phase ?? .unknown) : .unknown
        guard fresh, let server else {
            status = checking ? "Checking" : (server?.lastSuccessAt != nil ? "Stale" : "Unavailable")
            metric = nil
            accessibilityValue = "\(status). Activity is not live."
            return
        }
        status = phase == .prefill ? "Prefill" : phase.title
        let models = server.models ?? []
        func total(_ key: KeyPath<OMLXModelStatus, Int>) -> Int {
            models.reduce(0) { partial, model in
                let (sum, overflow) = partial.addingReportingOverflow(max(0, model[keyPath: key]))
                return overflow ? Int.max : sum
            }
        }
        let active = total(\.activeRequests)
        let queued = total(\.queuedRequests)
        let requests = models.flatMap(\.requests).filter { $0.phase != .queued }
        var value: String?
        var spoken: String?
        if queued > 0 {
            value = "\(queued) queued"
        } else if server.busyModels.count > 1 {
            value = "\(server.busyModels.count) models"
        } else if active > 1 {
            value = "\(active) active"
        } else if phase == .generating, requests.count == 1,
                  let speed = requests[0].tokensPerSecond, speed.isFinite, speed > 0 {
            let number = speed.formatted(.number.precision(.fractionLength(0)))
            value = "\(number) t/s"
            spoken = "Average generation speed \(number) tokens per second"
        } else if phase == .prefill, requests.count == 1, let fraction = requests[0].prefillFraction {
            value = "\(Int(fraction * 100))%"
            spoken = "\(Int(fraction * 100)) percent of prompt processed"
        } else if phase == .ready {
            value = "\(models.count) loaded"
        }
        metric = value
        accessibilityValue = status + (spoken.map { ". \($0)" } ?? value.map { ". \($0)" } ?? "")
    }
}

public enum OMLXRefreshSurface: Sendable {
    case iPhoneHome, watchSystem
    public var interval: TimeInterval {
        switch self {
        case .iPhoneHome: return 2
        case .watchSystem: return 5
        }
    }
}

/// Endpoint and visible-surface changes invalidate the SwiftUI task owner.
/// Used by both hosts; covered, inactive/AOD and off-page views never fetch.
public struct OMLXPollConfiguration: Hashable, Sendable {
    public let endpoint: JarvisEndpoint?
    public let interval: TimeInterval
    public init(endpoint: JarvisEndpoint?, surface: OMLXRefreshSurface,
                visible: Bool, interactive: Bool, covered: Bool = false) {
        self.endpoint = visible && interactive && !covered ? endpoint : nil
        interval = surface.interval
    }
    public func hash(into hasher: inout Hasher) {
        hasher.combine(endpoint?.baseURL)
        hasher.combine(endpoint?.token)
        hasher.combine(interval)
    }
}

/// Decorative motion never encodes throughput or progress and never owns a timer.
public struct OMLXMotionPolicy: Equatable, Sendable {
    public let enabled: Bool
    public let pulsesCPU: Bool

    public init(rows: [OMLXServerSummary], active: Bool, sceneActive: Bool,
                reduceMotion: Bool, luminanceReduced: Bool) {
        enabled = ActivityMotionGate.allows(active: active, sceneActive: sceneActive,
            reduceMotion: reduceMotion, luminanceReduced: luminanceReduced)
        pulsesCPU = enabled && rows.contains { $0.fresh && $0.phase == .generating }
    }

    public func transitionsMetric(for row: OMLXServerSummary) -> Bool {
        enabled && row.fresh && row.metric != nil
    }
}
