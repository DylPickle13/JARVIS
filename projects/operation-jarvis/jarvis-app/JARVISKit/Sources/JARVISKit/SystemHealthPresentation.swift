import Foundation

public enum SystemHealthState: String, Equatable, Sendable {
    case healthy, issue, unknown, checking, inactive
}

public struct SystemHealthRow: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let state: SystemHealthState
    public let detail: String
    /// Collector last-good age; sensor read health uses the last status-read attempt.
    public let ageSeconds: Double?

    public var ageText: String {
        guard let ageSeconds, ageSeconds.isFinite, ageSeconds >= 0 else { return "Observation age unknown" }
        let label = id == "security" ? "Last status read" : "Last good read"
        if ageSeconds < 60 { return "\(label) \(Int(ageSeconds))s ago" }
        if ageSeconds < 3600 { return "\(label) \(Int(ageSeconds / 60))m ago" }
        if ageSeconds < 86400 { return "\(label) \(Int(ageSeconds / 3600))h ago" }
        return "\(label) \(Int(min(ageSeconds / 86400, 999999)))d ago"
    }
}

/// Read-only projection of /api/v1/state. Never fetches services or devices.
/// Caps mirror StateCoordinator.DEFAULT_STALE_AFTER (2026-09-22), including
/// the new Pi/services/network expiry rules. Explicit server stale/error flags
/// always win; local elapsed time also expires a frozen or older-host snapshot.
public struct SystemHealthPresentation: Equatable, Sendable {
    public static let freshnessLimits: [String: Double] = [
        "services": 660, "pi": 180, "plugs": 30, "purifier": 90,
        "network": 1260, "codexQuota": 900,
    ]
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
        let categories: [(String, String)] = [
            ("services", "Background services"), ("pi", "Pi session data"),
            ("plugs", "Plugs"), ("purifier", "Air purifiers"),
            ("network", "Network data"), ("codexQuota", "Codex usage"),
        ]
        var result: [SystemHealthRow] = []
        if snapshot?.ok == false {
            result.append(.init(id: "backend", title: "Backend", state: .issue,
                                detail: "State request reported a failure", ageSeconds: nil))
        }
        for (id, title) in categories {
            let limit = Self.freshnessLimits[id]!
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
                    if service.critical == false && service.healthPolicy == "informational" {
                        status = .inactive
                        if !service.ok {
                            detail = "Informational · status read unavailable"
                        } else if service.running == false {
                            detail = "Stopped · on demand"
                        } else if service.running == true {
                            detail = service.ready == false ? Self.readinessDetail(service.readinessReason)
                                : service.ready == nil && service.readinessReason != nil
                                    ? "Running · readiness unverified" : "Running · informational"
                        } else {
                            detail = "Informational · process status unverified"
                        }
                    } else if !service.ok {
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
                        if service.ready == false {
                            status = .issue; detail = Self.readinessDetail(service.readinessReason)
                        } else if service.ready == nil && service.readinessReason != nil {
                            status = .unknown; detail = "Running · readiness unverified"
                        } else {
                            status = .healthy; detail = "Running"
                        }
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
        // Older hosts retain their original six-collector scope. Once a health
        // summary is supplied, missing/malformed sensor evidence is never green.
        if let summary = snapshot?.health {
            // Keep the sensor check inside the ring's bounded segment prefix,
            // even when a host advertises a large service inventory.
            result.insert(Self.sensorRow(summary, validElapsed: validElapsed, now: now),
                          at: snapshot?.ok == false ? 1 : 0)
            // An optimistic local collector projection cannot override a failed,
            // expired or malformed backend overall summary. Avoid double-counting
            // when the underlying issue/uncertainty is already represented.
            let overall = Self.overallRow(summary, validElapsed: validElapsed, now: now)
            if (overall.state == .issue && !result.contains(where: { $0.state == .issue }))
                || (overall.state == .unknown && !result.contains(where: { [.issue, .unknown, .checking].contains($0.state) })) {
                result.insert(overall, at: 0)
            }
        }
        if let coverage = snapshot?.deviceHealth {
            if coverage.supported {
                let required = ["keyboard-watcher", "keyboard", "mouse", "led-strip", "room-audio-mac",
                                "hub", "door-sensor", "motion-sensor", "sensor-reader", "front-doorbell",
                                "indoor-camera", "room-audio-pi", "family-room-tv", "family-room-speaker"]
                let present = Set(coverage.devices.map(\.id))
                for id in required where !present.contains(id) {
                    result.append(.init(id: "device:\(id)", title: id, state: .unknown,
                                        detail: "No configured check evidence", ageSeconds: nil))
                }
                for device in coverage.devices where !["iphone-usb", "watch", "master-chief"].contains(device.id) {
                    let state: SystemHealthState
                    switch validElapsed == nil ? "unknown" : device.effectiveState(now: now) {
                    case "available": state = .healthy
                    case "unavailable": state = .issue
                    default: state = .unknown
                    }
                    result.append(.init(id: "device:\(device.id)", title: device.name,
                        state: state, detail: "\(device.scopeLabel) · \(device.detail(now: now))",
                        ageSeconds: device.ageSeconds.flatMap { age in
                            guard age.isFinite, age >= 0, let validElapsed,
                                  (age + validElapsed).isFinite else { return nil }
                            return age + validElapsed
                        }))
                }
            } else {
                result.append(.init(id: "deviceCoverage", title: "Device checks", state: .unknown,
                                    detail: "Unsupported device coverage", ageSeconds: nil))
            }
        }
        rows = result
    }

    public static func readinessDetail(_ reason: String?) -> String {
        switch reason {
        case "java_listening": return "Running · Java listener verified"
        case "java_not_listening": return "Running · Java listener unavailable"
        case "bot_rpc_unavailable": return "Running · bot interface unavailable"
        case "bot_disconnected": return "Running · disconnected from Minecraft"
        case "bot_quarantined": return "Running · bot action quarantined"
        case "agent_unavailable": return "Running · Pi agent unavailable"
        case "bot_ready": return "Running · connected, Pi agent available"
        default: return "Running · readiness unverified"
        }
    }

    private static func overallRow(_ summary: CachedSystemHealthSummary,
                                   validElapsed: Double?, now: Date) -> SystemHealthRow {
        func row(_ state: SystemHealthState, _ detail: String) -> SystemHealthRow {
            .init(id: "backendHealth", title: "Backend health summary", state: state, detail: detail, ageSeconds: nil)
        }
        guard validElapsed != nil, summary.scope == "cached_status_health",
              let component = summary.components?["overall"] else {
            return row(.unknown, "Backend health summary unverified")
        }
        switch component.state {
        case "unavailable", "degraded":
            return row(.issue, "Cached backend summary reports an issue")
        case "healthy":
            guard component.reason == "current",
                  let source = component.sourceObservedAt.flatMap(SystemHistoryDates.parse), source <= now,
                  let expiry = component.validUntil.flatMap(SystemHistoryDates.parse), expiry >= source, now <= expiry else {
                return row(.unknown, "Backend health evidence expired or incomplete")
            }
            return row(.healthy, "Backend cached checks current")
        case "inactive" where component.reason == "optional_inactive" || component.reason == "monitoring_disabled":
            return row(.inactive, "Backend checks inactive")
        default:
            return row(.unknown, "Backend health summary unverified")
        }
    }

    private static func sensorRow(_ summary: CachedSystemHealthSummary,
                                  validElapsed: Double?, now: Date) -> SystemHealthRow {
        func row(_ state: SystemHealthState, _ detail: String, age: Double? = nil) -> SystemHealthRow {
            .init(id: "security", title: "Sensor status reads", state: state, detail: detail, ageSeconds: age)
        }
        guard validElapsed != nil, summary.scope == "cached_status_health",
              let component = summary.components?["security"] else {
            return row(.unknown, "Sensor read summary unavailable or unverified")
        }
        if component.state == "inactive", component.reason == "monitoring_disabled" {
            return row(.inactive, "Sensor monitoring disabled or unconfigured")
        }
        let source = component.sourceObservedAt.flatMap(SystemHistoryDates.parse)
        let age = source.flatMap { $0 <= now ? now.timeIntervalSince($0) : nil }
        guard let state = component.state, let reason = component.reason else {
            return row(.unknown, "Sensor read evidence is incomplete", age: age)
        }
        // Do not expose arbitrary server errors, aliases or sensor values.
        switch state {
        case "unavailable", "degraded":
            guard reason == "sensor_read_failed", source != nil, age != nil else {
                return row(.unknown, "Sensor read failure could not be verified", age: age)
            }
            return row(.issue, "Cached sensor status read failed; not proof of a physical outage", age: age)
        case "healthy":
            guard reason == "current", let source, age != nil,
                  let expiry = component.validUntil.flatMap(SystemHistoryDates.parse), expiry >= source else {
                return row(.unknown, "Sensor read freshness could not be verified", age: age)
            }
            guard now <= expiry else {
                return row(.unknown, "Sensor read evidence expired", age: age)
            }
            return row(.healthy, "Cached status reads available; radio freshness unverified", age: age)
        case "unknown":
            return row(.unknown, reason == "observation_expired" ? "Sensor read evidence expired"
                       : reason == "not_checked" ? "Sensor status reads not yet checked"
                       : "Sensor read evidence unverified", age: age)
        default:
            return row(.unknown, "Sensor read state unrecognized", age: age)
        }
    }
}
