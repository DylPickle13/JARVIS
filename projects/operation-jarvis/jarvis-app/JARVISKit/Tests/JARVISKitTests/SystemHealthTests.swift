import Foundation
import XCTest
@testable import JARVISKit

final class SystemHealthTests: XCTestCase {
    let now = Date(timeIntervalSince1970: 1000)
    let required: [String: Any] = ["ok": true, "running": true, "critical": true,
                                  "configured": true, "executionMode": "continuous"]

    var periodic: [String: Any] {
        ["ok": true, "running": false, "loaded": true, "critical": true,
         "configured": true, "executionMode": "periodic", "lastExitCode": 0]
    }

    func snapshot(overrides: [String: [String: Any]] = [:], services: [String: Any]? = nil,
                  omitMetadata: Bool = false, omitServiceMap: Bool = false,
                  plugs: [String: Any] = [:]) throws -> StateSnapshot {
        let keys = ["services", "pi", "plugs", "purifier", "network", "codexQuota"]
        var meta: [String: Any] = [:]
        for key in keys {
            var value: [String: Any] = ["ok": true, "stale": false, "refreshing": false, "ageSeconds": 0]
            for (field, replacement) in overrides[key] ?? [:] { value[field] = replacement }
            meta[key] = value
        }
        let data: [String: Any] = ["ok": true, "stale": false,
            "subsystemsMeta": omitMetadata ? [:] : meta,
            "subsystems": [
                "services": omitServiceMap ? ["ok": true] : ["ok": true, "services": services ?? ["scheduler": required]],
                "plugs": ["ok": true, "stale": false, "plugs": plugs],
                "purifier": ["ok": true, "stale": false],
                "pi": ["ok": true, "active": 0], "network": ["ok": true], "codexQuota": ["ok": true],
            ]]
        return try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: data))
    }

    func health(_ snapshot: StateSnapshot, elapsed: Double = 0) -> SystemHealthPresentation {
        .init(snapshot: snapshot, requestStartedAt: now, now: now.addingTimeInterval(elapsed))
    }

    func testCurrentCachedSnapshotAndNestedServicesRoundTrip() throws {
        let value = try snapshot()
        XCTAssertEqual(value.subsystems?.services?.services?["scheduler"]?.running, true)
        XCTAssertEqual(try JSONDecoder().decode(StateSnapshot.self, from: JSONEncoder().encode(value)), value)
        XCTAssertEqual(health(value).summary, "Healthy")
        XCTAssertEqual(health(value).rows.count, 6)
        XCTAssertEqual(health(value).issueCount, 0, "Idle Pi sessions are not service failures")
    }

    func testRequiredStoppedServiceFailsButOptionalStoppedDoesNot() throws {
        var stopped = required; stopped["running"] = false
        let optional: [String: Any] = ["ok": true, "running": false, "critical": false]
        let value = health(try snapshot(services: ["scheduler": stopped, "room-audio": optional]))
        XCTAssertEqual(value.issueCount, 1)
        XCTAssertEqual(value.rows.first { $0.id == "service:room-audio" }?.state, .inactive)
        XCTAssertEqual(value.rows.first { $0.id == "service:scheduler" }?.state, .issue)
        XCTAssertEqual(health(try snapshot(services: ["optional": optional])).state, .healthy)
    }

    func testNewSnapshotsBetweenTimelineTicksDoNotReplaceServiceIssueWithUnknown() throws {
        var stopped = required; stopped["running"] = false
        let snapshot = try snapshot(services: ["scheduler": stopped])
        for second in 0..<20 {
            let request = now.addingTimeInterval(Double(second))
            let render = request.addingTimeInterval(0.1)
            let previousTick = now.addingTimeInterval(Double((second / 5) * 5))
            let oldPresentation = SystemHealthPresentation(snapshot: snapshot,
                requestStartedAt: request, now: previousTick)
            if second % 5 != 0 {
                // Reproduces the original false Unknown between five-second ticks.
                XCTAssertEqual(oldPresentation.state, .unknown)
            }
            let current = SystemHealthPresentation(snapshot: snapshot,
                requestStartedAt: request, now: render)
            XCTAssertEqual(current.summary, "1 issue")
            XCTAssertEqual(current.unknownCount, 0)
        }
    }

    func testDefaultEvaluationClockHandlesSnapshotNewerThanLastTimelineTick() throws {
        var stopped = required; stopped["running"] = false
        let snapshot = try snapshot(services: ["scheduler": stopped])
        let request = Date().addingTimeInterval(-0.1)
        let previousTick = request.addingTimeInterval(-3)
        XCTAssertEqual(SystemHealthPresentation(snapshot: snapshot,
            requestStartedAt: request, now: previousTick).summary, "Status unknown")
        // This is the exact initializer used by SystemHealthCard on each render.
        XCTAssertEqual(SystemHealthPresentation(snapshot: snapshot,
            requestStartedAt: request).summary, "1 issue")
    }

    func testRenderClockStillExpiresUnchangedSnapshotAndAllowsRealRecovery() throws {
        let current = try snapshot()
        XCTAssertEqual(health(current).state, .healthy)
        XCTAssertEqual(health(current, elapsed: 31).rows.first { $0.id == "plugs" }?.state, .issue)
        var stopped = required; stopped["running"] = false
        XCTAssertEqual(health(try snapshot(services: ["scheduler": stopped])).summary, "1 issue")
        XCTAssertEqual(health(current).summary, "Healthy", "Do not latch old issues to suppress real changes")
    }

    func testRequiredConfigurationAndStatusReadFailuresStayVisible() throws {
        var missing = required; missing["configured"] = false; missing["running"] = false
        let failure: [String: Any] = ["ok": false, "critical": false, "error": "read failed"]
        let value = health(try snapshot(services: ["required": missing, "optional": failure]))
        XCTAssertEqual(value.issueCount, 2)
        XCTAssertEqual(value.summary, "2 issues")
        XCTAssertEqual(value.rows.first { $0.id == "service:required" }?.detail, "Required service is not configured")
        XCTAssertEqual(value.rows.first { $0.id == "service:optional" }?.detail, "Service status read failed")
    }

    func testPeriodicSchedulerIsHealthyBetweenSuccessfulChecks() throws {
        let snapshot = try snapshot(services: ["scheduler": periodic])
        let value = health(snapshot)
        XCTAssertEqual(value.summary, "Healthy")
        XCTAssertEqual(value.rows.first { $0.id == "service:scheduler" }?.detail, "Scheduled · idle between checks")
        let decoded = try JSONDecoder().decode(StateSnapshot.self, from: JSONEncoder().encode(snapshot))
        XCTAssertEqual(decoded.subsystems?.services?.services?["scheduler"]?.executionMode, "periodic")
        XCTAssertEqual(decoded.subsystems?.services?.services?["scheduler"]?.lastExitCode, 0)
        XCTAssertEqual(health(decoded), value)
    }

    func testPeriodicFailedCompletionRemainsAnIssueEvenWhileNextRunIsActive() throws {
        for running in [false, true] {
            for code in [-9, 1, 2, 255] {
                var service = periodic; service["running"] = running; service["lastExitCode"] = code
                let value = health(try snapshot(services: ["scheduler": service]))
                XCTAssertEqual(value.issueCount, 1)
                XCTAssertEqual(value.rows.first { $0.id == "service:scheduler" }?.detail,
                               "Last scheduled check failed (exit \(code))")
            }
            var signalled = periodic; signalled["running"] = running; signalled["lastExitSignal"] = 9
            let value = health(try snapshot(services: ["scheduler": signalled]))
            XCTAssertEqual(value.issueCount, 1)
            XCTAssertEqual(value.rows.first { $0.id == "service:scheduler" }?.detail,
                           "Last scheduled check ended with signal 9")
        }
    }

    func testPeriodicUnloadedMissingConfigurationAndStatusFailuresAreNotHealthy() throws {
        for field in ["loaded", "configured", "ok"] {
            var service = periodic; service[field] = false
            XCTAssertEqual(health(try snapshot(services: ["scheduler": service])).issueCount, 1, field)
        }
        for field in ["loaded", "lastExitCode", "running"] {
            var service = periodic; service.removeValue(forKey: field)
            XCTAssertEqual(health(try snapshot(services: ["scheduler": service])).state, .unknown, field)
        }
    }

    func testPeriodicRunningCheckAndRecoveryFromFailure() throws {
        var service = periodic; service["running"] = true; service.removeValue(forKey: "lastExitCode")
        let running = health(try snapshot(services: ["scheduler": service]))
        XCTAssertEqual(running.state, .healthy)
        XCTAssertEqual(running.rows.first { $0.id == "service:scheduler" }?.detail, "Running scheduled check")
        service["lastExitCode"] = 2
        XCTAssertEqual(health(try snapshot(services: ["scheduler": service])).state, .issue)
        XCTAssertEqual(health(try snapshot(services: ["scheduler": periodic])).state, .healthy)
    }

    func testPeriodicSuccessDoesNotOverrideStaleMetadataOrLegacyUnknownMode() throws {
        let stale = health(try snapshot(overrides: ["services": ["stale": true]], services: ["scheduler": periodic]))
        XCTAssertEqual(stale.state, .issue)
        XCTAssertFalse(stale.rows.contains { $0.id == "service:scheduler" })
        for mode in [NSNull(), "future-mode"] as [Any] {
            var legacy = periodic; legacy["executionMode"] = mode
            XCTAssertEqual(health(try snapshot(services: ["scheduler": legacy])).state, .unknown)
        }
    }

    func testContinuousRequiredServiceDoesNotBecomeHealthyFromAnOldSuccessfulExit() throws {
        var service = required; service["running"] = false; service["loaded"] = true; service["lastExitCode"] = 0
        let value = health(try snapshot(services: ["daemon": service]))
        XCTAssertEqual(value.issueCount, 1)
        XCTAssertEqual(value.rows.first { $0.id == "service:daemon" }?.detail, "Required service is stopped")
    }

    func testMissingServiceRequirementsAndMapsStayUnknown() throws {
        let stopped: [String: Any] = ["ok": true, "running": false]
        XCTAssertEqual(health(try snapshot(services: ["legacy": stopped])).state, .unknown)
        XCTAssertEqual(health(try snapshot(omitServiceMap: true)).state, .unknown)
        XCTAssertEqual(health(try snapshot(omitMetadata: true)).state, .unknown)
        XCTAssertEqual(health(try snapshot(services: [:])).state, .healthy)
    }

    func testNewBackendExpiryCapsAndLocalElapsedTimeOverrideOldHealthyFlags() throws {
        for (key, cap) in [("pi", 180.0), ("services", 660), ("network", 1260),
                           ("plugs", 30), ("purifier", 90), ("codexQuota", 900)] {
            let value = try snapshot(overrides: [key: ["ageSeconds": cap]])
            XCTAssertEqual(health(value).issueCount, 0)
            let expired = health(value, elapsed: 1)
            XCTAssertEqual(expired.rows.first { $0.id == key }?.state, .issue, key)
            XCTAssertEqual(expired.issueCount, 1)
        }
    }

    func testStaleServiceCacheDoesNotAssertServiceIsCurrentlyStopped() throws {
        var stopped = required; stopped["running"] = false
        let value = health(try snapshot(overrides: ["services": ["stale": true]], services: ["scheduler": stopped]))
        XCTAssertEqual(value.issueCount, 1)
        XCTAssertEqual(value.rows.first { $0.id == "services" }?.detail, "Stale observation")
        XCTAssertFalse(value.rows.contains { $0.id == "service:scheduler" })
    }

    func testPartialPlugAndPurifierFailuresCannotLookHealthy() throws {
        let value = health(try snapshot(plugs: [
            "good": ["ok": true, "stale": false, "isOn": false],
            "bad": ["ok": false, "stale": true],
        ]))
        XCTAssertEqual(value.rows.first { $0.id == "plugs" }?.state, .issue)
        var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(try snapshot())) as! [String: Any]
        var subsystems = object["subsystems"] as! [String: Any]
        subsystems["purifier"] = ["ok": true, "stale": false, "devices": [
            "default": ["ok": true, "stale": false], "other": ["ok": false, "stale": true],
        ]]
        object["subsystems"] = subsystems
        let decoded = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertEqual(health(decoded).rows.first { $0.id == "purifier" }?.state, .issue)
    }

    func testCheckingUnknownFailureAndRefreshAreDistinct() throws {
        XCTAssertEqual(SystemHealthPresentation(snapshot: nil, requestStartedAt: nil, now: now).state, .checking)
        let current = try snapshot()
        XCTAssertEqual(SystemHealthPresentation(snapshot: current, requestStartedAt: nil, now: now).state, .unknown)
        XCTAssertEqual(health(current, elapsed: -1).state, .unknown)
        XCTAssertEqual(health(try snapshot(overrides: ["pi": ["refreshing": true]])).state, .healthy)
        XCTAssertEqual(health(try snapshot(overrides: ["pi": ["ok": false, "refreshing": true,
            "ageSeconds": NSNull(), "error": "loading"]])).state, .checking)
        XCTAssertEqual(health(try snapshot(overrides: ["pi": ["ok": false, "error": "read failed"]])).state, .issue)
        XCTAssertEqual(health(try snapshot(overrides: ["pi": ["ageSeconds": -1]])).state, .unknown)
    }
}
