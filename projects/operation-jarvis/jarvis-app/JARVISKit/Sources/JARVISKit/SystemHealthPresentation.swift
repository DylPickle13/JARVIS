import Foundation

public enum SystemHealthState: String, Equatable, Sendable {
    case healthy, issue, unknown, checking, inactive
}

public struct SystemHealthRow: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let state: SystemHealthState
    public let detail: String
    /// Last-good observation age, not time since a failed attempt.
    public let ageSeconds: Double?

    public var ageText: String {
        guard let ageSeconds, ageSeconds.isFinite, ageSeconds >= 0 else { return "Observation age unknown" }
        if ageSeconds < 60 { return "Last good read \(Int(ageSeconds))s ago" }
        if ageSeconds < 3600 { return "Last good read \(Int(ageSeconds / 60))m ago" }
        if ageSeconds < 86400 { return "Last good read \(Int(ageSeconds / 3600))h ago" }
        return "Last good read \(Int(min(ageSeconds / 86400, 999999)))d ago"
    }
}

/// Read-only projection of /api/v1/state. Never fetches services or devices.
/// Caps mirror StateCoordinator.DEFAULT_STALE_AFTER (2026-09-22), including
/// the new Pi/services/network expiry rules. Explicit server stale/error flags
/// always win; local elapsed time also expires a frozen or older-host snapshot.
public struct SystemHealthPresentation: Equatable, Sendable {
    public let rows: [SystemHealthRow]
    public var issueCount: Int { rows.filter { $0.state == .issue }.count }
    public var unknownCount: Int { rows.filter { [.unknown, .checking].contains($0.state) }.count }
    public var state: SystemHealthState {
        if issueCount > 0 { return .issue }
        if rows.contains(where: { $0.state == .unknown }) { return .unknown }
        if rows.isEmpty || rows.contains(where: { $0.state == .checking }) { return .checking }
        return .healthy
    }
    public var summary: String {
        if issueCount > 0 {
            let issues = "\(issueCount) \(issueCount == 1 ? "issue" : "issues")"
            return unknownCount > 0 ? issues + " · \(unknownCount) unknown" : issues
        }
        switch state {
        case .healthy: return "Healthy"
        case .checking: return "Checking"
        default: return "Status unknown"
        }
    }

    /// Default to the actual evaluation time, not a TimelineView's previous tick.
    /// Keep injection for deterministic expiry tests and reject genuinely future timestamps.
    public init(snapshot: StateSnapshot?, requestStartedAt: Date?, now: Date = Date()) {
        let elapsed = requestStartedAt.map { now.timeIntervalSince($0) }
        let validElapsed = elapsed.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
        let categories: [(String, String, Double)] = [
            ("services", "Background services", 660), ("pi", "Pi session data", 180),
            ("plugs", "Plugs", 30), ("purifier", "Air purifiers", 90),
            ("network", "Network data", 1260), ("codexQuota", "Codex usage", 900),
        ]
        var result: [SystemHealthRow] = []
        if snapshot?.ok == false {
            result.append(.init(id: "backend", title: "Backend", state: .issue,
                                detail: "State request reported a failure", ageSeconds: nil))
        }
        for (id, title, limit) in categories {
            let meta = snapshot?.subsystemsMeta?[id]
            let age: Double? = {
                guard let value = meta?.ageSeconds, value.isFinite, value >= 0,
                      let validElapsed, (value + validElapsed).isFinite else { return nil }
                return value + validElapsed
            }()
            func row(_ state: SystemHealthState, _ detail: String) -> SystemHealthRow {
                .init(id: id, title: title, state: state, detail: detail, ageSeconds: age)
            }
            guard let meta else {
                result.append(row(snapshot == nil || snapshot?.loading == true ? .checking : .unknown,
                                  "No collector metadata"))
                continue
            }
            if meta.refreshing == true && meta.ageSeconds == nil {
                result.append(row(.checking, "Waiting for the first observation"))
                continue
            }
            if meta.ok == false || (meta.error?.isEmpty == false && meta.error != "loading") {
                result.append(row(.issue, "Latest collector read failed"))
                continue
            }
            if meta.stale == true || age.map({ $0 > limit }) == true {
                result.append(row(.issue, meta.refreshing == true ? "Stale observation; refreshing" : "Stale observation"))
                continue
            }
            guard meta.ok == true, meta.stale == false, age != nil else {
                result.append(row(.unknown, "Freshness could not be verified"))
                continue
            }
            if id == "services" {
                guard let services = snapshot?.subsystems?.services?.services else {
                    result.append(row(.unknown, "Service details unavailable on this snapshot"))
                    continue
                }
                if services.isEmpty { result.append(row(.healthy, "No services configured")) }
                for key in services.keys.sorted() {
                    guard let service = services[key] else { continue }
                    let status: SystemHealthState
                    let detail: String
                    if !service.ok {
                        status = .issue; detail = "Service status read failed"
                    } else if service.critical == true && service.configured == false {
                        status = .issue; detail = "Required service is not configured"
                    } else if service.executionMode == "periodic" {
                        if service.loaded == false {
                            status = service.critical == true ? .issue : service.critical == false ? .inactive : .unknown
                            detail = "Scheduled service is not loaded"
                        } else if service.loaded != true {
                            status = .unknown; detail = "Scheduled service registration is unknown"
                        } else if let signal = service.lastExitSignal {
                            status = .issue; detail = "Last scheduled check ended with signal \(signal)"
                        } else if let code = service.lastExitCode, code != 0 {
                            status = .issue; detail = "Last scheduled check failed (exit \(code))"
                        } else if service.running == true {
                            status = .healthy; detail = "Running scheduled check"
                        } else if service.running == false && service.lastExitCode == 0 {
                            status = .healthy; detail = "Scheduled · idle between checks"
                        } else {
                            status = .unknown; detail = "Scheduled check completion is unknown"
                        }
                    } else if service.running == true {
                        status = .healthy; detail = "Running"
                    } else if service.critical == false && service.running == false {
                        status = .inactive; detail = "Stopped · not marked required"
                    } else if service.critical == true && service.running == false && service.executionMode == "continuous" {
                        status = .issue; detail = "Required service is stopped"
                    } else {
                        status = .unknown; detail = "Service state or execution mode is unknown"
                    }
                    result.append(.init(id: "service:\(key)", title: service.displayName ?? key,
                                        state: status, detail: detail, ageSeconds: age))
                }
            } else if id == "plugs" {
                guard let plugs = snapshot?.subsystems?.plugs?.plugs else {
                    result.append(row(.unknown, "Individual plug observations unavailable")); continue
                }
                let failed = plugs.values.filter { $0.ok == false || $0.stale == true }.count
                let unknown = plugs.values.contains { $0.ok == nil || $0.stale == nil || $0.isOn == nil }
                result.append(failed > 0 ? row(.issue, "\(failed) plug observation(s) unavailable or stale")
                              : unknown ? row(.unknown, "Some plug observations are incomplete")
                              : row(.healthy, meta.refreshing == true ? "Current; refreshing" : "Observations current"))
            } else if id == "purifier" {
                guard let purifier = snapshot?.subsystems?.purifier else {
                    result.append(row(.unknown, "Purifier observations unavailable")); continue
                }
                let devices = purifier.devices.map { Array($0.values) } ?? [purifier]
                let failed = devices.contains { $0.ok == false || $0.stale == true }
                let unknown = devices.isEmpty || devices.contains { $0.ok == nil || $0.stale == nil }
                result.append(failed ? row(.issue, "A purifier observation is unavailable or stale")
                              : unknown ? row(.unknown, "Purifier observations are incomplete")
                              : row(.healthy, meta.refreshing == true ? "Current; refreshing" : "Observations current"))
            } else {
                result.append(row(.healthy, meta.refreshing == true ? "Current; refreshing" : "Observation current"))
            }
        }
        rows = result
    }
}
