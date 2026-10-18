import Foundation
import XCTest
@testable import JARVISKit

final class SystemTelemetryTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private func response(changes: [Int: SystemHistoryState] = [:], gaps: Set<Int> = [], mixed: Set<Int> = []) throws -> SystemHistoryResponse {
        var object = HistoryFixture.object(window: .hour, component: "overall", end: now)
        var series = object["series"] as! [[String: Any]]
        var buckets = series[0]["buckets"] as! [[String: Any]]
        for i in 0..<60 {
            let state = changes[i] ?? .healthy
            let gap = gaps.contains(i), mix = mixed.contains(i)
            buckets[i]["state"] = gap && state.priority < SystemHistoryState.unknown.priority ? "unknown" : state.rawValue
            buckets[i]["coverageSeconds"] = gap ? 30 : 60
            buckets[i]["missingSeconds"] = gap ? 30 : 0
            buckets[i]["stateSeconds"] = mix ? ["healthy": 30, "degraded": 30] : [state.rawValue: gap ? 30 : 60]
            buckets[i]["mixed"] = gap || mix
            if mix { buckets[i]["state"] = "degraded" }
        }
        series[0]["buckets"] = buckets; object["series"] = series
        return try HistoryFixture.decode(object).validated(window: .hour, component: "overall", now: now)
    }
    func testHealthyHidesResolvedIncidentsByChangingRangeNotRepainting() throws {
        let r = try response(changes: [20: .degraded, 45: .unavailable])
        let original = r
        let w = SystemTelemetryWindow(response: r, current: .healthy, trusted: true, now: now)
        XCTAssertEqual(w.title, "Since recovery")
        XCTAssertEqual(w.buckets.count, 14)
        XCTAssertEqual(w.start, r.series[0].buckets[46].start)
        XCTAssertTrue(w.buckets.allSatisfy(SystemTelemetryWindow.isHealthy))
        XCTAssertEqual(r, original)
    }
    func testAlreadyHealthyHistoryDoesNotInventARecoveryTime() throws {
        let w = SystemTelemetryWindow(response: try response(), current: .healthy, trusted: true, now: now)
        XCTAssertEqual(w.title, "Healthy observations")
        XCTAssertNil(w.recoveryCandidate)
        XCTAssertEqual(w.buckets.count, 60)
    }
    func testCurrentRecoveryBeforeHistoryShowsWaitingNotGreenBackfill() throws {
        for state in [SystemHistoryState.degraded, .unavailable, .unknown, .inactive] {
            let w = SystemTelemetryWindow(response: try response(changes: [59: state]), current: .healthy, trusted: true, now: now)
            XCTAssertTrue(w.buckets.isEmpty)
            XCTAssertEqual(w.notice, "Waiting for verified healthy history")
            XCTAssertNil(w.beaconSource)
        }
    }
    func testRecoveryDropsWholeMixedOrPartialBucketWithoutInventingOrder() throws {
        for r in [try response(gaps: [59]), try response(mixed: [59])] {
            let w = SystemTelemetryWindow(response: r, current: .healthy, trusted: true, now: now)
            XCTAssertTrue(w.buckets.isEmpty)
            XCTAssertEqual(w.recoveryCandidate, now)
        }
    }
    func testIncidentPreservesMixedPartialEvidenceAndOneHealthyContextBucket() throws {
        let r = try response(changes: [57: .degraded, 58: .unavailable, 59: .degraded], gaps: [58], mixed: [57])
        let w = SystemTelemetryWindow(response: r, current: .issue, trusted: true, now: now)
        XCTAssertEqual(w.title, "Current incident")
        XCTAssertEqual(w.buckets, Array(r.series[0].buckets[56...]))
        XCTAssertTrue(w.buckets[1].mixed)
        XCTAssertTrue(w.buckets[2].hasGap)
        XCTAssertNil(w.recoveryCandidate)
    }
    func testNewIssueCannotDisplayHealthyHistoryEndpointAsCurrent() throws {
        let w = SystemTelemetryWindow(response: try response(), current: .issue, trusted: true, now: now)
        XCTAssertTrue(w.buckets.isEmpty)
        XCTAssertEqual(w.notice, "Waiting for current history")
    }
    func testStaleOfflineOrPausedHistoryNeverConfirmsRecoveryOrPulses() throws {
        let r = try response(changes: [55: .degraded])
        for state in [SystemHealthState.healthy, .unknown, .issue, .checking] {
            let w = SystemTelemetryWindow(response: r, current: state, trusted: false, now: now)
            XCTAssertEqual(w.buckets.count, 60)
            XCTAssertTrue(w.muted)
            XCTAssertNil(w.recoveryCandidate)
            XCTAssertNil(w.beaconSource)
            XCTAssertEqual(w.title, "Cached trace")
        }
    }
    func testRecoveryFenceSurvivesUnknownWithoutResurrectingEarlierFailures() throws {
        let r = try response(changes: [40: .degraded])
        let healthy = SystemTelemetryWindow(response: r, current: .healthy, trusted: true, now: now)
        var session = SystemTelemetrySession()
        session.advance(to: try XCTUnwrap(healthy.recoveryCandidate))
        let offline = SystemTelemetryWindow(response: r, current: .unknown, trusted: false,
            floor: session.recoveryFloor, now: now)
        XCTAssertEqual(offline.buckets.count, 19)
        XCTAssertFalse(offline.buckets.contains { $0.state == .degraded })
    }
    func testFenceInsideBucketDoesNotClipEvidenceOrBackfillHealthyTime() throws {
        let floor = now.addingTimeInterval(-90)
        let w = SystemTelemetryWindow(response: try response(), current: .healthy, trusted: true, floor: floor, now: now)
        XCTAssertEqual(w.buckets.count, 1)
        XCTAssertEqual(w.start, now.addingTimeInterval(-60))
        XCTAssertEqual(w.end, now)
    }
    func testFreshObservationTransitionAdvancesFenceOnlyOnce() {
        var session = SystemTelemetrySession()
        session.observe(state: .issue, observedAt: now.addingTimeInterval(-10), trusted: true, now: now)
        session.observe(state: .healthy, observedAt: now, trusted: true, now: now)
        XCTAssertEqual(session.recoveryFloor, now)
        session.observe(state: .healthy, observedAt: now.addingTimeInterval(10), trusted: true, now: now.addingTimeInterval(10))
        XCTAssertEqual(session.recoveryFloor, now)
    }
    func testReconnectRepeatFutureAndOlderSnapshotsCannotResetGraph() {
        var session = SystemTelemetrySession()
        session.observe(state: .unknown, observedAt: now.addingTimeInterval(-10), trusted: false, now: now)
        session.observe(state: .healthy, observedAt: now, trusted: true, now: now)
        XCTAssertNil(session.recoveryFloor)
        session.observe(state: .issue, observedAt: now.addingTimeInterval(5), trusted: true, now: now.addingTimeInterval(5))
        session.observe(state: .healthy, observedAt: now.addingTimeInterval(5), trusted: true, now: now.addingTimeInterval(5))
        session.observe(state: .healthy, observedAt: now, trusted: true, now: now.addingTimeInterval(5))
        session.observe(state: .healthy, observedAt: now.addingTimeInterval(60), trusted: true, now: now)
        session.observe(state: .healthy, observedAt: nil, trusted: true, now: now)
        XCTAssertNil(session.recoveryFloor)
    }
    func testBeaconUsesSourceEvidenceNotRefreshTimeAndConsumesHiddenUpdates() {
        var beacon = SystemTelemetryBeacon()
        XCTAssertFalse(beacon.receive(now, allowed: true))
        XCTAssertFalse(beacon.receive(now, allowed: true))
        XCTAssertFalse(beacon.receive(now.addingTimeInterval(-5), allowed: true))
        XCTAssertTrue(beacon.receive(now.addingTimeInterval(10), allowed: true))
        XCTAssertFalse(beacon.receive(now.addingTimeInterval(20), allowed: false))
        XCTAssertFalse(beacon.receive(now.addingTimeInterval(20), allowed: true))
        XCTAssertFalse(beacon.receive(nil, allowed: true))
    }
    func testPartialMixedOrMissingTailNeverShowsSolidBeacon() throws {
        for r in [try response(changes: [59: .degraded], gaps: [59]), try response(mixed: [59])] {
            let w = SystemTelemetryWindow(response: r, current: .issue, trusted: true, now: now)
            XCTAssertNil(w.beaconSource)
        }
        let r = try response()
        let w = SystemTelemetryWindow(response: r, current: .healthy, trusted: true, now: now)
        XCTAssertEqual(w.beaconSource, r.series[0].buckets.last?.sourceObservedAt.flatMap(SystemHistoryDates.parse))
        XCTAssertNotEqual(w.beaconSource, now)
    }
    func testInspectionBoundsAndCoverageAccessibility() throws {
        let w = SystemTelemetryWindow(response: try response(changes: [59: .degraded], gaps: [59]), current: .issue, trusted: true, now: now)
        XCTAssertEqual(w.bucket(at: -1), w.buckets.first)
        XCTAssertEqual(w.bucket(at: 2), w.buckets.last)
        XCTAssertNil(w.bucket(at: .nan))
        let text = SystemTelemetryWindow.evidence(try XCTUnwrap(w.bucket(at: 1)))
        XCTAssertTrue(text.contains("30 seconds missing"))
        XCTAssertTrue(text.contains("event order and exact incident duration unknown"))
    }
    func testMissingAndFutureHistoryFailClosed() throws {
        let empty = SystemTelemetryWindow(response: nil, current: .healthy, trusted: true, now: now)
        XCTAssertTrue(empty.buckets.isEmpty)
        XCTAssertEqual(empty.notice, "History unavailable")
        let future = try response()
        let w = SystemTelemetryWindow(response: future, current: .healthy, trusted: false, now: now.addingTimeInterval(-3601))
        XCTAssertTrue(w.buckets.isEmpty)
    }
    @MainActor func testHistoryEndpointChangeResetsPresentationMemoryWithoutRequests() {
        let model = SystemHistoryModel(fetch: { _, _, _ in XCTFail("No requests allowed"); throw JarvisError.notConfigured })
        model.configure(.init(endpoint: .init(baseURL: URL(string: "http://first.invalid")!, token: "fixture"), surface: .phone, visible: false, interactive: false, connected: false))
        model.observeTelemetry(current: .issue, observedAt: now.addingTimeInterval(-10), currentTrusted: true, now: now)
        model.observeTelemetry(current: .healthy, observedAt: now, currentTrusted: true, now: now)
        XCTAssertEqual(model.telemetrySession.recoveryFloor, now)
        model.configure(.init(endpoint: .init(baseURL: URL(string: "http://second.invalid")!, token: "fixture"), surface: .phone, visible: false, interactive: false, connected: false))
        XCTAssertNil(model.telemetrySession.recoveryFloor)
        XCTAssertFalse(model.isPolling)
    }
}
