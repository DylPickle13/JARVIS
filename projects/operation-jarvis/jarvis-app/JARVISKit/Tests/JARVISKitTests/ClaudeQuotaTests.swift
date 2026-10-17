import Foundation
import XCTest
@testable import JARVISKit

final class ClaudeQuotaTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_792_267_200)

    private func snapshot(claude: [String: Any]?, codex: [String: Any]? = nil) throws -> StateSnapshot {
        var subsystems: [String: Any] = [:]
        subsystems["claudeQuota"] = claude
        subsystems["codexQuota"] = codex
        return try JSONDecoder().decode(StateSnapshot.self,
            from: JSONSerialization.data(withJSONObject: ["ok": true, "subsystems": subsystems]))
    }

    private func quota(weekly: Double = 98, fiveHour: Double = 80, stale: Bool = false) -> [String: Any] {
        ["ok": true, "available": true, "stale": stale,
         "checkedAt": ISO8601DateFormatter().string(from: now),
         "weekly": ["remainingPercent": weekly, "resetAt": "2026-10-19T16:00:00Z"],
         "fiveHour": ["remainingPercent": fiveHour, "resetAt": "2026-10-17T23:00:00.204Z"],
         "fiveHourEnforced": true]
    }

    func testDecodeAndRoundTripBothIndependentProviders() throws {
        let state = try snapshot(claude: quota(), codex: quota(weekly: 12))
        XCTAssertEqual(state.subsystems?.claudeQuota?.weekly?.remainingPercent, 98)
        XCTAssertEqual(state.subsystems?.claudeQuota?.fiveHour?.remainingPercent, 80)
        XCTAssertEqual(state.subsystems?.codexQuota?.weekly?.remainingPercent, 12)
        let decoded = try JSONDecoder().decode(StateSnapshot.self, from: JSONEncoder().encode(state))
        XCTAssertEqual(decoded.subsystems, state.subsystems)
        XCTAssertNil(try snapshot(claude: nil).subsystems?.claudeQuota, "Older daemons remain decodable")
    }

    func testPartialWindowsRemainAvailableToProviderCards() throws {
        var partial = quota()
        partial.removeValue(forKey: "weekly")
        let state = try snapshot(claude: partial, codex: quota(weekly: 12))
        XCTAssertNil(state.subsystems?.claudeQuota?.weekly)
        XCTAssertEqual(state.subsystems?.claudeQuota?.fiveHour?.remainingPercent, 80)
        XCTAssertEqual(state.subsystems?.codexQuota?.weekly?.remainingPercent, 12)
    }

    func testNeuralCoreIgnoresClaudeWhileProviderModelRetainsIt() throws {
        let baseline = try snapshot(claude: nil, codex: quota(weekly: 12))
        let original = JARVISNeuralCoreTelemetry(
            cached: .init(state: baseline, savedAt: now), now: now)
        for remaining in [0.0, 20.0, 98.0, 100.0] {
            let state = try snapshot(claude: quota(weekly: remaining), codex: quota(weekly: 12))
            let telemetry = JARVISNeuralCoreTelemetry(
                cached: .init(state: state, savedAt: now), now: now)
            XCTAssertEqual(telemetry, original, "Claude must not alter Neural Core")
            XCTAssertEqual(state.subsystems?.claudeQuota?.weekly?.remainingPercent, remaining)
            XCTAssertEqual(telemetry.codexRemainingPercent, 12)
            XCTAssertTrue(telemetry.codexIsCritical)
        }
    }

    func testClaudeFailuresDoNotChangeLegacyWidgetTelemetry() throws {
        let baseline = try snapshot(claude: nil, codex: quota(weekly: 68))
        let original = JARVISNeuralCoreTelemetry(
            cached: .init(state: baseline, savedAt: now), now: now)
        for claude in [quota(stale: true), ["ok": false, "available": false]] {
            let state = try snapshot(claude: claude, codex: quota(weekly: 68))
            let telemetry = JARVISNeuralCoreTelemetry(
                cached: .init(state: state, savedAt: now), now: now)
            XCTAssertEqual(telemetry, original)
            XCTAssertEqual(telemetry.codexRemainingPercent, 68)
        }
    }

    func testLegacyNeuralCorePlaceholderAndMissingState() {
        let placeholder = JARVISNeuralCoreTelemetry(cached: nil, placeholder: true)
        XCTAssertEqual(placeholder.codexRemainingPercent, 82)
        XCTAssertFalse(placeholder.codexIsCritical)
        let absent = JARVISNeuralCoreTelemetry(cached: nil)
        XCTAssertNil(absent.codexRemainingPercent)
        XCTAssertTrue(absent.signalLost)
    }
}
