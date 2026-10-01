import Foundation
import XCTest
@testable import JARVISKit

final class SensorSystemHealthTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1000)
    private func stamp(_ date: Date) -> String {
        date.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true))
    }
    private func evidence(state: String = "healthy", reason: String = "current",
                          source: Double = 990, expiry: Double? = 1110) -> [String: Any] {
        var value: [String: Any] = ["state": state, "reason": reason,
                                   "sourceObservedAt": stamp(Date(timeIntervalSince1970: source))]
        if let expiry { value["validUntil"] = stamp(Date(timeIntervalSince1970: expiry)) }
        return value
    }
    private func summary(sensor: Any, overall: Any? = nil) -> [String: Any] {
        ["scope": "cached_status_health", "healthy": true,
         "components": ["security": sensor, "overall": overall ?? evidence()]]
    }
    private func snapshot(health: Any? = nil) throws -> StateSnapshot {
        let keys = ["services", "pi", "plugs", "purifier", "network", "codexQuota"]
        var object: [String: Any] = ["ok": true, "generatedAt": stamp(now),
            "subsystemsMeta": Dictionary(uniqueKeysWithValues: keys.map {
                ($0, ["ok": true, "stale": false, "ageSeconds": 0] as [String: Any])
            }), "subsystems": [
                "services": ["ok": true, "services": ["runner": ["ok": true, "critical": true,
                    "configured": true, "executionMode": "periodic", "loaded": true,
                    "running": false, "lastExitCode": 0]]],
                "plugs": ["ok": true, "stale": false, "plugs": ["fixture": ["ok": true, "stale": false, "isOn": false]]],
                "purifier": ["ok": true, "stale": false]]]
        if let health { object["health"] = health }
        return try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
    }
    private func presentation(_ state: StateSnapshot, at date: Date? = nil, request: Date? = nil) -> SystemDashboardPresentation {
        .init(snapshot: state, requestStartedAt: request ?? now, now: date ?? now)
    }

    func testVisualGroupsKeepEveryCheckAndConservativeSensorStates() throws {
        for (state, expected) in [("healthy", SystemHealthState.healthy), ("unavailable", .issue), ("unknown", .unknown), ("inactive", .inactive)] {
            let reason = state == "unavailable" ? "sensor_read_failed" : state == "inactive" ? "monitoring_disabled" : state == "unknown" ? "not_checked" : "current"
            let dashboard = presentation(try snapshot(health: summary(sensor: evidence(state: state, reason: reason))))
            XCTAssertEqual(dashboard.visualGroups.count, 5)
            XCTAssertEqual(dashboard.visualGroups.last?.state, expected)
            let ids = Set(dashboard.visualGroups.flatMap(\.rows).map(\.id))
            XCTAssertTrue(Set(dashboard.subsystemRows.map(\.id)).isSubset(of: ids))
            XCTAssertTrue(Set(dashboard.services.map { $0.row.id }).isSubset(of: ids))
            let sensor = try XCTUnwrap(dashboard.subsystemRows.first { $0.id == "security" })
            XCTAssertTrue(dashboard.visualGroups.last!.accessibilityText.contains(sensor.ageText))
            XCTAssertTrue(dashboard.visualGroups.last!.accessibilityText.contains(sensor.detail))
            if state == "healthy" { XCTAssertNil(dashboard.visualException) }
            if state == "unavailable" { XCTAssertNotNil(dashboard.visualException) }
        }
        let absent = presentation(try snapshot())
        XCTAssertEqual(absent.visualGroups.last?.state, .unknown)
        XCTAssertTrue(absent.visualGroups.last!.accessibilityText.contains("No cached evidence"))
        let offline = SystemDashboardPresentation(snapshot: try snapshot(), requestStartedAt: now, isConnected: false, now: now)
        XCTAssertTrue(offline.visualGroups.allSatisfy { $0.state == .unknown })
        XCTAssertEqual(offline.visualException, "Offline · cached evidence")
    }

    func testVisualGroupDoesNotHideUnknownBehindHealthyOrFailureBehindUnknown() {
        func row(_ state: SystemHealthState) -> SystemHealthRow {
            .init(id: state.rawValue, title: state.rawValue, state: state, detail: "Fixture", ageSeconds: 1)
        }
        XCTAssertEqual(SystemVisualGroup(id: "test", title: "Test", rows: [row(.healthy), row(.unknown)]).state, .unknown)
        XCTAssertEqual(SystemVisualGroup(id: "test", title: "Test", rows: [row(.unknown), row(.issue)]).state, .issue)
        XCTAssertEqual(SystemVisualGroup(id: "test", title: "Test", rows: [row(.inactive)]).state, .inactive)
    }

    func testNewSummaryIncludesSeventhCheckAndRetainsSixWatchChips() throws {
        let dashboard = presentation(try snapshot(health: summary(sensor: evidence())))
        XCTAssertEqual(dashboard.state, .healthy)
        XCTAssertEqual(dashboard.health.rows.count, 7)
        XCTAssertEqual(dashboard.subsystemRows.count, 7)
        XCTAssertEqual(dashboard.compactSubsystemRows.count, 6)
        XCTAssertTrue(dashboard.compactSubsystemRows.contains { $0.id == "security" })
        XCTAssertFalse(dashboard.compactSubsystemRows.contains { $0.id == "services" })
        XCTAssertEqual(dashboard.services.first?.row.detail, "Scheduled · idle between checks")
        XCTAssertTrue(dashboard.subsystemRows.contains { $0.id == "services" })
        XCTAssertEqual(dashboard.health.rows.first { $0.id == "security" }?.ageText, "Last status read 10s ago")
        let state = try snapshot(health: summary(sensor: evidence(state: "unavailable", reason: "sensor_read_failed", expiry: nil)))
        var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(state)) as! [String: Any]
        var subsystems = object["subsystems"] as! [String: Any]
        subsystems["services"] = ["services": Dictionary(uniqueKeysWithValues: (0..<30).map {
            ("fixture\($0)", ["ok": true, "critical": true, "running": true, "executionMode": "continuous"] as [String: Any])
        })]
        object["subsystems"] = subsystems
        let large = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertTrue(presentation(large).health.rows.prefix(24).contains { $0.id == "security" },
            "A bounded ring must not silently drop the sensor check behind many services")
    }

    func testFailedSensorReadPreventsHealthyEvenWhenTopLevelBooleanSaysHealthy() throws {
        let dashboard = presentation(try snapshot(health: summary(sensor: evidence(state: "unavailable", reason: "sensor_read_failed", expiry: nil))))
        XCTAssertEqual(dashboard.state, .issue)
        XCTAssertEqual(dashboard.health.issueCount, 1)
        let row = try XCTUnwrap(dashboard.health.rows.first { $0.id == "security" })
        XCTAssertEqual(row.state, .issue)
        XCTAssertTrue(row.detail.contains("not proof of a physical outage"))
        XCTAssertEqual(row.ageText, "Last status read 10s ago", "A failed attempt is not a last-good observation")
    }

    func testExpiredUncheckedAndUnknownSensorReadsPreventHealthy() throws {
        for reason in ["observation_expired", "not_checked", "sensor_read_unknown"] {
            let dashboard = presentation(try snapshot(health: summary(sensor: evidence(state: "unknown", reason: reason, expiry: nil))))
            XCTAssertEqual(dashboard.state, .unknown, reason)
            XCTAssertEqual(dashboard.health.unknownCount, 1)
        }
        let unchecked = presentation(try snapshot(health: summary(sensor: ["state": "unknown", "reason": "not_checked"])))
        XCTAssertEqual(unchecked.state, .unknown)
    }

    func testDisabledMonitoringIsInactiveNotAFabricatedSensorSuccess() throws {
        let dashboard = presentation(try snapshot(health: summary(sensor: ["state": "inactive", "reason": "monitoring_disabled"])))
        XCTAssertEqual(dashboard.state, .healthy, "Inactive optional monitoring is not an outage")
        XCTAssertEqual(dashboard.health.rows.first { $0.id == "security" }?.state, .inactive)
        XCTAssertNil(dashboard.health.rows.first { $0.id == "security" }?.ageSeconds)
    }

    func testAbsoluteExpiryCannotBeRejuvenatedByNewReceiptOrGenerationTime() throws {
        let state = try snapshot(health: summary(sensor: evidence(expiry: 1001)))
        let later = now.addingTimeInterval(2)
        let dashboard = presentation(state, at: later, request: later)
        XCTAssertEqual(dashboard.state, .unknown)
        XCTAssertEqual(dashboard.health.rows.first { $0.id == "security" }?.state, .unknown)
        XCTAssertEqual(dashboard.health.rows.first { $0.id == "security" }?.ageSeconds, 12)
        var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(state)) as! [String: Any]
        object["generatedAt"] = stamp(later)
        let rewrapped = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertEqual(presentation(rewrapped, at: later, request: later).state, .unknown)
    }

    func testIncompleteFutureAndUnrecognizedEvidenceFailsClosedWithoutRawErrorDisplay() throws {
        var values: [[String: Any]] = [
            ["state": "healthy", "reason": "current"],
            evidence(state: "future-state"), evidence(reason: "private-error-fixture"),
            evidence(source: 1001), evidence(expiry: 989), evidence(expiry: 999),
            evidence(state: "inactive", reason: "current"),
            ["state": "healthy", "reason": "current", "sourceObservedAt": "1970-01-01T00:16:30", "validUntil": stamp(now.addingTimeInterval(100))]
        ]
        var invalidDate = evidence(); invalidDate["validUntil"] = "not-a-date"; values.append(invalidDate)
        for value in values {
            let dashboard = presentation(try snapshot(health: summary(sensor: value)))
            XCTAssertEqual(dashboard.state, .unknown, "\(value)")
            XCTAssertFalse(dashboard.health.rows.contains { $0.detail.contains("private-error-fixture") })
        }
    }

    func testMalformedHealthDoesNotBreakExistingControlDecodeButCannotBeGreen() throws {
        var wrongScope = summary(sensor: evidence()); wrongScope["scope"] = "physical_connectivity"
        var oversized = summary(sensor: evidence())
        oversized["components"] = Dictionary(uniqueKeysWithValues: (0..<33).map { ("fixture\($0)", evidence()) })
        let values: [Any] = [123, "malformed", ["scope": "cached_status_health"], wrongScope, oversized,
            ["scope": "cached_status_health", "components": 7],
            summary(sensor: false), summary(sensor: ["state": 1, "reason": true])]
        for value in values {
            let state = try snapshot(health: value)
            XCTAssertEqual(state.subsystems?.plugs?.plugs?["fixture"]?.isOn, false)
            XCTAssertNotNil(state.health)
            XCTAssertEqual(presentation(state).state, .unknown)
        }
    }

    func testLegacyAndNullHealthKeepOriginalScopeWithoutInventingSensorEvidence() throws {
        for value in [try snapshot(), try snapshot(health: NSNull())] {
            let dashboard = presentation(value)
            XCTAssertNil(value.health)
            XCTAssertEqual(dashboard.state, .healthy)
            XCTAssertEqual(dashboard.health.rows.count, 6)
            XCTAssertFalse(dashboard.health.rows.contains { $0.id == "security" })
        }
    }

    func testBackendOverallFailureUnknownAndExpiryCannotBeOverriddenByLocalGreen() throws {
        for state in ["unavailable", "degraded", "unknown", "future-state"] {
            let dashboard = presentation(try snapshot(health: summary(sensor: evidence(), overall: evidence(state: state, reason: "collector_failed", expiry: nil))))
            XCTAssertEqual(dashboard.state, ["unavailable", "degraded"].contains(state) ? .issue : .unknown)
            XCTAssertTrue(dashboard.health.rows.contains { $0.id == "backendHealth" })
            XCTAssertEqual(dashboard.compactSubsystemRows.count, 6)
        }
        let stale = presentation(try snapshot(health: summary(sensor: evidence(), overall: evidence(expiry: 999))))
        XCTAssertEqual(stale.state, .unknown)
        let missing = presentation(try snapshot(health: ["scope": "cached_status_health", "components": ["security": evidence()]]))
        XCTAssertEqual(missing.state, .unknown)
    }

    func testBackendOverallCannotHideLocalExpiryOrPeriodicServiceFailure() throws {
        let state = try snapshot(health: summary(sensor: evidence()))
        XCTAssertEqual(presentation(state, at: now.addingTimeInterval(31)).state, .issue)
        var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(state)) as! [String: Any]
        var subsystems = object["subsystems"] as! [String: Any]
        subsystems["services"] = ["ok": true, "services": ["runner": ["ok": true, "critical": true,
            "configured": true, "executionMode": "periodic", "loaded": true,
            "running": true, "lastExitCode": 2]]]
        object["subsystems"] = subsystems
        let failed = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertEqual(presentation(failed).state, .issue)
    }

    func testSummarySurvivesExistingStateRelayEncodingAndConfirmedPlugProjection() throws {
        var sensor = evidence(); sensor["contact"] = "private-fixture"; sensor["motion"] = true
        sensor["alias"] = "private-sensor-fixture"; sensor["error"] = "private-error-fixture"
        let state = try snapshot(health: summary(sensor: sensor))
        let data = try JSONEncoder().encode(state)
        let decoded = try JSONDecoder().decode(StateSnapshot.self, from: data)
        XCTAssertEqual(decoded, state)
        XCTAssertEqual(presentation(decoded).state, .healthy)
        let encoded = String(decoding: data, as: UTF8.self)
        XCTAssertFalse(encoded.contains("private-fixture"))
        XCTAssertFalse(encoded.contains("private-sensor-fixture"))
        XCTAssertFalse(encoded.contains("private-error-fixture"))
        let projected = state.applyingConfirmedPlugState(name: "fixture", isOn: true, at: now)
        XCTAssertEqual(projected.health, state.health)
        XCTAssertEqual(projected.subsystems?.plugs?.plugs?["fixture"]?.isOn, true)
        var untrusted = summary(sensor: ["state": "private-state-fixture", "reason": "private-reason-fixture",
            "sourceObservedAt": "private-source-fixture", "validUntil": "private-expiry-fixture"])
        var components = untrusted["components"] as! [String: Any]
        components["private-alias-fixture"] = evidence(); untrusted["components"] = components
        let sanitized = try snapshot(health: untrusted)
        let sanitizedJSON = String(decoding: try JSONEncoder().encode(sanitized), as: UTF8.self)
        XCTAssertFalse(sanitizedJSON.contains("private-"), "Unknown values cannot become a new raw-error/alias relay or cache")
        XCTAssertEqual(presentation(sanitized).state, .unknown)
    }

    func testOfflineAndUnverifiableWatchGenerationCannotShowSensorGreen() throws {
        let state = try snapshot(health: summary(sensor: evidence()))
        let offline = SystemDashboardPresentation(snapshot: state, requestStartedAt: now, isConnected: false, now: now)
        XCTAssertEqual(offline.state, .unknown)
        XCTAssertTrue(offline.subsystemRows.allSatisfy { $0.state == .unknown })
        for request in [nil, now.addingTimeInterval(1)] as [Date?] {
            let value = SystemDashboardPresentation(snapshot: state, requestStartedAt: request, now: now)
            XCTAssertEqual(value.health.rows.first { $0.id == "security" }?.state, .unknown)
        }
        let later = now.addingTimeInterval(121)
        let watch = SystemDashboardPresentation(snapshot: state,
            requestStartedAt: SystemDashboardPresentation.snapshotGeneratedAt(state), now: later)
        XCTAssertEqual(watch.health.rows.first { $0.id == "security" }?.state, .unknown)
    }

    func testSensorFailuresRecoverOnlyFromFreshReplacementEvidence() throws {
        let failed = try snapshot(health: summary(sensor: evidence(state: "unavailable", reason: "sensor_read_failed", expiry: nil)))
        XCTAssertEqual(presentation(failed).state, .issue)
        let recovered = try snapshot(health: summary(sensor: evidence()))
        XCTAssertEqual(presentation(recovered).state, .healthy)
    }
}
