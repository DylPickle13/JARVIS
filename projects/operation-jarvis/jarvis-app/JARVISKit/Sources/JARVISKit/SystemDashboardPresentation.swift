import Foundation

/// Read-only dashboard projection. A failed/stale collector keeps its cached
/// inventory visible, but cannot establish any service's current process state.
public struct SystemDashboardService: Identifiable, Equatable, Sendable {
    public let id: String
    public let row: SystemHealthRow
    public let description: String?
    public let requirement: String
    public let executionMode: String
    public let technicalDetails: [String]
}

public struct SystemDashboardPresentation: Equatable, Sendable {
    public let health: SystemHealthPresentation
    public let services: [SystemDashboardService]
    public let isConnected: Bool
    public let backendVersion: String?
    public let uptimeText: String?

    public func freshnessFraction(for row: SystemHealthRow) -> Double? {
        guard let limit = SystemHealthPresentation.freshnessLimits[row.id],
              let age = row.ageSeconds, age.isFinite, age >= 0 else { return nil }
        return min(1, age / limit)
    }
    public var subsystemRows: [SystemHealthRow] {
        var rows = health.rows.filter { !$0.id.hasPrefix("service:") }
        // The compact health model replaces a fresh service collector row with
        // process rows. Keep its observation-age panel stable on this dashboard.
        if !rows.contains(where: { $0.id == "services" }), let service = services.first {
            rows.insert(.init(id: "services", title: "Background service data", state: .healthy,
                detail: "Observation current", ageSeconds: service.row.ageSeconds), at: 0)
        }
        return rows.map { row in
            guard !isConnected else { return row }
            return .init(id: row.id, title: row.title, state: .unknown,
                         detail: "Offline · current status unverified", ageSeconds: row.ageSeconds)
        }
    }
    public var summary: String { isConnected ? health.summary : "Offline · cached data" }
    public var state: SystemHealthState { isConnected ? health.state : .unknown }
    public var healthyServiceCount: Int { services.filter { $0.row.state == .healthy }.count }
    public var issueServiceCount: Int { services.filter { $0.row.state == .issue }.count }
    public var unknownServiceCount: Int {
        services.filter { [.unknown, .checking].contains($0.row.state) }.count
    }
    public var inactiveServiceCount: Int { services.filter { $0.row.state == .inactive }.count }

    public init(snapshot: StateSnapshot?, requestStartedAt: Date?, isConnected: Bool = true, now: Date = Date()) {
        let health = SystemHealthPresentation(snapshot: snapshot, requestStartedAt: requestStartedAt, now: now)
        self.health = health
        self.isConnected = isConnected
        self.backendVersion = snapshot?.version
        if let uptime = snapshot?.uptimeSeconds, uptime.isFinite, uptime >= 0 {
            let days = Int(min(uptime / 86400, 999999))
            let hours = Int(uptime.truncatingRemainder(dividingBy: 86400) / 3600)
            let minutes = Int(uptime.truncatingRemainder(dividingBy: 3600) / 60)
            self.uptimeText = days > 0 ? "\(days)d \(hours)h" : hours > 0 ? "\(hours)h \(minutes)m" : "\(minutes)m"
        } else { self.uptimeText = nil }
        let collector = health.rows.first { $0.id == "services" }
        let inventory = snapshot?.subsystems?.services?.services ?? [:]
        self.services = inventory.keys.sorted { lhs, rhs in
            let left = inventory[lhs]?.sortOrder ?? Int.max
            let right = inventory[rhs]?.sortOrder ?? Int.max
            return left == right ? lhs < rhs : left < right
        }.map { key in
            let service = inventory[key]!
            let observed = health.rows.first { $0.id == "service:\(key)" }
            let row: SystemHealthRow
            if isConnected, let observed {
                row = observed
            } else {
                row = .init(id: "service:\(key)", title: service.displayName ?? key,
                    state: isConnected && collector?.state == .checking ? .checking : .unknown,
                    detail: isConnected ? "Current status unverified · \(collector?.detail ?? "Freshness unknown")" : "Offline · current status unverified",
                    ageSeconds: observed?.ageSeconds ?? collector?.ageSeconds)
            }
            var details = ["Service: \(key)"]
            if let label = service.label { details.append("Registration: \(label)") }
            if let configured = service.configured { details.append("Configured: \(configured ? "Yes" : "No")") }
            if let loaded = service.loaded { details.append("Loaded: \(loaded ? "Yes" : "No")") }
            if let running = service.running { details.append("Running: \(running ? "Yes" : "No")") }
            if let pid = service.pid { details.append("PID: \(pid)") }
            if let code = service.lastExitCode { details.append("Last exit code: \(code)") }
            if let signal = service.lastExitSignal { details.append("Last exit signal: \(signal)") }
            if let error = service.error, !error.isEmpty { details.append("Error: \(error)") }
            return SystemDashboardService(id: key, row: row, description: service.description,
                requirement: service.critical.map { $0 ? "Required" : "Optional" } ?? "Requirement unknown",
                executionMode: service.executionMode == "continuous" ? "Continuous" : service.executionMode == "periodic" ? "Scheduled" : "Execution mode unknown",
                technicalDetails: details)
        }.sorted { lhs, rhs in
            // Swift's stable sort preserves configured order within each priority.
            func priority(_ state: SystemHealthState) -> Int {
                switch state { case .issue: return 0; case .unknown, .checking: return 1; default: return 2 }
            }
            return priority(lhs.row.state) < priority(rhs.row.state)
        }
    }

    /// Watch snapshots may arrive long after generation via application context
    /// or disk. Receipt/save time must never rejuvenate cached collector ages.
    /// Missing or future generation dates remain unverified in the health model.
    public static func snapshotGeneratedAt(_ snapshot: StateSnapshot?) -> Date? {
        guard let text = snapshot?.generatedAt else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: text) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: text)
    }
}
