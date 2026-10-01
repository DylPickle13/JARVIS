import XCTest
@testable import JARVISKit

final class DeviceHealthTests: XCTestCase {
    private func decode(state: String = "available", coverage: String = "background", at: String = "2026-10-01T01:00:00Z") throws -> StateSnapshot {
        let value: [String: Any] = ["ok": true, "deviceHealth": ["version": 1, "scope": "device_check_coverage", "devices": [[
            "id": "speaker", "name": "Speaker", "scope": "tcp_reachability", "expectation": "always",
            "coverage": coverage, "state": state, "reason": "current", "ageSeconds": 1,
            "lastAttemptAt": at, "lastSuccessAt": at, "consecutiveFailures": 0,
            "freshnessLimitSeconds": 150, "dependsOn": [], "blockedBy": [], "incidentOpen": false
        ]]]]
        return try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: value))
    }

    func testOlderBackendStillDecodes() throws {
        let state = try JSONDecoder().decode(StateSnapshot.self, from: Data("{\"ok\":true}".utf8))
        XCTAssertNil(state.deviceHealth)
    }

    func testCoverageAndReachabilityScope() throws {
        let coverage = try XCTUnwrap(decode().deviceHealth)
        XCTAssertTrue(coverage.supported)
        XCTAssertEqual(coverage.coverageText, "1/1 background checks · 0 unmonitored · 0 on demand")
        XCTAssertEqual(coverage.devices[0].scopeLabel, "TCP reachability only")
    }

    func testFrozenStateExpiresAndFutureEvidenceIsUnknown() throws {
        let check = try XCTUnwrap(decode().deviceHealth?.devices.first)
        let at = try XCTUnwrap(SystemHistoryDates.parse("2026-10-01T01:00:00Z"))
        XCTAssertEqual(check.effectiveState(now: at.addingTimeInterval(10)), "available")
        XCTAssertEqual(check.effectiveState(now: at.addingTimeInterval(151)), "unknown")
        XCTAssertEqual(check.effectiveState(now: at.addingTimeInterval(-1)), "unknown")
        XCTAssertEqual(check.detail(now: at.addingTimeInterval(151)), "Evidence expired or incomplete")
    }

    func testUnmonitoredNeverGreenAndInvalidDateUnknown() throws {
        let check = try XCTUnwrap(decode(coverage: "unmonitored").deviceHealth?.devices.first)
        XCTAssertEqual(check.effectiveState(), "unmonitored")
        let invalid = try XCTUnwrap(decode(at: "bad").deviceHealth?.devices.first)
        XCTAssertEqual(invalid.effectiveState(), "unknown")
    }

    func testRoundTripPreservesCoverage() throws {
        let state = try decode()
        XCTAssertEqual(try JSONDecoder().decode(StateSnapshot.self, from: JSONEncoder().encode(state)), state)
    }
}
