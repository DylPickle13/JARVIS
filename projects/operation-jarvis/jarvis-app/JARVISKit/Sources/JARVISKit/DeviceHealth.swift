import Foundation

/// Separate from aggregate system health: a green legacy summary is not complete coverage.
public struct DeviceHealthCoverage: Codable, Equatable, Sendable {
    public let version: Int
    public let scope: String
    public let devices: [DeviceHealthCheck]

    public var supported: Bool { version == 1 && scope == "device_check_coverage" && devices.count <= 40 }
    public var coverageText: String {
        guard supported else { return "Device coverage unavailable" }
        let background = devices.filter { $0.coverage == "background" }.count
        let unmonitored = devices.filter { $0.coverage == "unmonitored" }.count
        let onDemand = devices.filter { $0.coverage == "on_demand" }.count
        return "\(background)/\(devices.count) background checks · \(unmonitored) unmonitored · \(onDemand) on demand"
    }
}

public struct DeviceHealthCheck: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let name: String
    public let scope: String
    public let expectation: String
    public let coverage: String
    public let state: String
    public let reason: String
    public let ageSeconds: Double?
    public let lastAttemptAt: String?
    public let lastSuccessAt: String?
    public let consecutiveFailures: Int?
    public let freshnessLimitSeconds: Double?
    public let dependsOn: [String]
    public let blockedBy: [String]
    public let incidentOpen: Bool
    public let incidentStartedAt: String?

    /// Expire evidence locally even if the app stops receiving state updates.
    public func effectiveState(now: Date = Date()) -> String {
        guard coverage != "unmonitored" else { return "unmonitored" }
        guard let raw = lastAttemptAt ?? lastSuccessAt,
              let date = SystemHistoryDates.parse(raw),
              let limit = freshnessLimitSeconds, limit.isFinite, limit > 0,
              now >= date, now.timeIntervalSince(date) <= limit else { return "unknown" }
        return ["available", "unavailable", "unknown"].contains(state) ? state : "unknown"
    }

    public var scopeLabel: String {
        switch scope {
        case "tcp_reachability": return "TCP reachability only"
        case "usb_attachment": return "USB attachment only"
        case "process_heartbeat": return "Process heartbeat only"
        case "status_read": return "Status read · radio freshness unknown"
        case "integration_read": return "Integration read"
        default: return "No check configured"
        }
    }

    public func detail(now: Date = Date()) -> String {
        if effectiveState(now: now) == "unknown" && state == "available" { return "Evidence expired or incomplete" }
        switch reason {
        case "current": return "Check succeeded"
        case "monitoring_disabled": return "Monitoring disabled"
        case "no_check_configured": return "No check configured"
        case "observation_expired": return "Observation expired"
        case "connection_timeout": return "Connection timed out"
        case "connection_refused": return "Connection refused"
        case "network_unreachable": return "Network unreachable"
        case "usb_not_attached": return "USB device not attached"
        case "heartbeat_expired": return "Process heartbeat expired"
        case "process_fault": return "Process reports a fault"
        case "optional_device_unreachable": return "Optional device not reachable; may be off or sleeping"
        case "collector_read_failed", "integration_read_failed", "read_failed", "check_failed": return "Latest check failed"
        default: return "Not checked or evidence unavailable"
        }
    }
}
