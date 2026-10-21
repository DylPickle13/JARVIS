import Foundation
import XCTest
@testable import JARVISKit

/// An inactive Codex/Claude subscription is current state, never a health issue.
final class SubscriptionInactiveTests: XCTestCase {
    let now = Date(timeIntervalSince1970: 1000)

    let inactive: [String: Any] = [
        "ok": true, "available": false, "subscription": "inactive", "stale": false,
        "checkedAt": "2026-10-20T20:00:00Z", "planType": "free",
        "weekly": NSNull(), "fiveHour": NSNull(), "error": NSNull(),
    ]

    func snapshot(codex: [String: Any], claude: [String: Any],
                  meta overrides: [String: [String: Any]] = [:]) throws -> StateSnapshot {
        var meta: [String: Any] = [:]
        for key in ["services", "pi", "plugs", "purifier", "network", "codexQuota", "claudeQuota"] {
            var value: [String: Any] = ["ok": true, "stale": false, "refreshing": false, "ageSeconds": 0]
            for (field, replacement) in overrides[key] ?? [:] { value[field] = replacement }
            meta[key] = value
        }
        let data: [String: Any] = ["ok": true, "stale": false, "subsystemsMeta": meta, "subsystems": [
            "services": ["ok": true, "services": ["scheduler": [
                "ok": true, "running": true, "critical": true, "configured": true, "executionMode": "continuous"]]],
            "plugs": ["ok": true, "stale": false, "plugs": [:]],
            "purifier": ["ok": true, "stale": false],
            "pi": ["ok": true], "network": ["ok": true],
            "codexQuota": codex, "claudeQuota": claude,
        ]]
        return try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: data))
    }

    func testInactiveDecodesAsStateNotFailure() throws {
        let state = try snapshot(codex: inactive, claude: inactive)
        let codex = try XCTUnwrap(state.subsystems?.codexQuota)
        XCTAssertTrue(codex.isSubscriptionInactive)
        XCTAssertEqual(codex.subscription, "inactive")
        XCTAssertEqual(codex.planType, "free")
        XCTAssertNil(codex.weekly)
        XCTAssertNil(codex.error)
    }

    func testInactiveSubscriptionsAreInactiveRowsAndOverallHealthy() throws {
        let health = SystemHealthPresentation(snapshot: try snapshot(codex: inactive, claude: inactive),
                                              requestStartedAt: now, now: now)
        for id in ["codexQuota", "claudeQuota"] {
            let row = try XCTUnwrap(health.rows.first { $0.id == id })
            XCTAssertEqual(row.state, .inactive)
            XCTAssertEqual(row.detail, "Subscription inactive")
        }
        XCTAssertEqual(health.state, .healthy)
        XCTAssertEqual(health.issueCount, 0)
    }

    func testActiveAndLegacyQuotasAreUnchanged() throws {
        let active: [String: Any] = ["ok": true, "available": true, "subscription": "active",
                                     "weekly": ["remainingPercent": 50]]
        let legacy: [String: Any] = ["ok": true, "available": true, "weekly": ["remainingPercent": 50]]
        let state = try snapshot(codex: active, claude: legacy)
        XCTAssertFalse(try XCTUnwrap(state.subsystems?.codexQuota).isSubscriptionInactive)
        XCTAssertFalse(try XCTUnwrap(state.subsystems?.claudeQuota).isSubscriptionInactive)
        let health = SystemHealthPresentation(snapshot: state, requestStartedAt: now, now: now)
        XCTAssertEqual(health.rows.first { $0.id == "codexQuota" }?.state, .healthy)
        XCTAssertEqual(health.rows.first { $0.id == "claudeQuota" }?.state, .healthy)
    }

    func testCollectorFailureStillWinsOverInactiveMarker() throws {
        let state = try snapshot(codex: inactive, claude: inactive,
                                 meta: ["codexQuota": ["ok": false, "error": "Codex quota unavailable"]])
        let health = SystemHealthPresentation(snapshot: state, requestStartedAt: now, now: now)
        XCTAssertEqual(health.rows.first { $0.id == "codexQuota" }?.state, .issue)
        XCTAssertEqual(health.rows.first { $0.id == "claudeQuota" }?.state, .inactive)
        var errored = inactive
        errored["lastError"] = "Codex quota unavailable"
        XCTAssertFalse(try XCTUnwrap(try snapshot(codex: errored, claude: inactive)
            .subsystems?.codexQuota).isSubscriptionInactive)
    }
    func testSignedOutIsInactiveRowWithItsOwnText() throws {
        var signedOut = inactive
        signedOut["subscription"] = "signed_out"
        let state = try snapshot(codex: signedOut, claude: inactive)
        let codex = try XCTUnwrap(state.subsystems?.codexQuota)
        XCTAssertTrue(codex.isSubscriptionInactive)
        XCTAssertTrue(codex.isSignedOut)
        XCTAssertEqual(codex.subscriptionStateText, "Not signed in")
        let health = SystemHealthPresentation(snapshot: state, requestStartedAt: now, now: now)
        XCTAssertEqual(health.rows.first { $0.id == "codexQuota" }?.detail, "Not signed in")
        XCTAssertEqual(health.rows.first { $0.id == "claudeQuota" }?.detail, "Subscription inactive")
        XCTAssertEqual(health.state, .healthy)
    }

    func testMonthlyMainWindowAndNoFiveHourLimit() throws {
        let monthly: [String: Any] = ["ok": true, "available": true, "subscription": "active", "planType": "free",
            "weekly": NSNull(), "fiveHour": NSNull(), "fiveHourStatus": "none", "mainWindowLabel": "monthly",
            "mainWindow": ["remainingPercent": 100, "resetAt": "2026-11-20T01:05:54Z"]]
        let quota = try XCTUnwrap(try snapshot(codex: monthly, claude: inactive).subsystems?.codexQuota)
        XCTAssertEqual(quota.primaryWindow?.remainingPercent, 100)
        XCTAssertEqual(quota.primaryWindowTitle, "Monthly remaining")
        XCTAssertTrue(quota.hasNoFiveHourLimit)
        let legacy: [String: Any] = ["ok": true, "available": true, "weekly": ["remainingPercent": 40]]
        let old = try XCTUnwrap(try snapshot(codex: legacy, claude: inactive).subsystems?.codexQuota)
        XCTAssertEqual(old.primaryWindow?.remainingPercent, 40)
        XCTAssertEqual(old.primaryWindowTitle, "Weekly remaining")
        XCTAssertFalse(old.hasNoFiveHourLimit)
        var odd = monthly
        odd["mainWindowLabel"] = "#{evil}"
        XCTAssertEqual(try XCTUnwrap(try snapshot(codex: odd, claude: inactive).subsystems?.codexQuota).primaryWindowTitle, "Remaining")
        odd["mainWindowLabel"] = "30d"
        XCTAssertEqual(try XCTUnwrap(try snapshot(codex: odd, claude: inactive).subsystems?.codexQuota).primaryWindowTitle, "30d remaining")
    }

    func testFreshRateLimitedQuotaIsNotAnIssue() throws {
        let active: [String: Any] = ["ok": true, "available": true, "weekly": ["remainingPercent": 97]]
        let limited = try snapshot(codex: active, claude: active, meta: ["claudeQuota": [
            "error": "Claude usage rate limited; waiting before another check.", "rateLimited": true]])
        var health = SystemHealthPresentation(snapshot: limited, requestStartedAt: now, now: now)
        XCTAssertEqual(health.rows.first { $0.id == "claudeQuota" }?.state, .healthy)
        let expired = try snapshot(codex: active, claude: active, meta: ["claudeQuota": [
            "error": "rate limited", "rateLimited": true, "ageSeconds": 901]])
        health = SystemHealthPresentation(snapshot: expired, requestStartedAt: now, now: now)
        XCTAssertEqual(health.rows.first { $0.id == "claudeQuota" }?.state, .issue)
        let failed = try snapshot(codex: active, claude: active, meta: ["claudeQuota": ["error": "Claude usage failed"]])
        health = SystemHealthPresentation(snapshot: failed, requestStartedAt: now, now: now)
        XCTAssertEqual(health.rows.first { $0.id == "claudeQuota" }?.state, .issue)
    }
}
