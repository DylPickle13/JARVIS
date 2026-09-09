import Foundation
import XCTest
@testable import JARVISKit

final class OMLXSummaryTests: XCTestCase {
    let now = Date(timeIntervalSince1970: 100)
    func model(_ id: String = "m", active: Int = 0, queued: Int = 0, loading: Bool = false, requests: String = "[]") -> String {
        "{\"id\":\"\(id)\",\"isLoading\":\(loading),\"activeRequests\":\(active),\"queuedRequests\":\(queued),\"requests\":\(requests)}"
    }
    func server(_ models: [String], age: Double = 0, stale: Bool = false) throws -> OMLXServerStatus {
        let json = "{\"id\":\"mac-mini-64\",\"ok\":true,\"stale\":\(stale),\"ageSeconds\":\(age),\"lastSuccessAt\":\"2026-09-09T00:00:00Z\",\"models\":[\(models.joined(separator: ","))]}"
        return try JSONDecoder().decode(OMLXServerStatus.self, from: Data(json.utf8))
    }
    func summary(_ server: OMLXServerStatus, available: Bool = true, now: Date? = nil) -> OMLXServerSummary {
        .init(id: server.id, server: server, now: now ?? self.now, requestStartedAt: self.now, available: available)
    }

    func testTravellingEdgeWrapsWithoutBecomingAFullOutline() {
        for time in [-10.2, 0, 0.5, 4.9, 5, 5000] {
            let ranges = ActivityEdgeGeometry.ranges(time: time)
            XCTAssertTrue((1...2).contains(ranges.count))
            XCTAssertEqual(ranges.reduce(0) { $0 + $1.upperBound - $1.lowerBound }, 0.13, accuracy: 0.000001)
            for range in ranges {
                XCTAssertGreaterThanOrEqual(range.lowerBound, 0)
                XCTAssertLessThanOrEqual(range.upperBound, 1)
            }
        }
        for (time, period) in [(Double.nan, 5.0), (.infinity, 5), (1, 0), (1, -1), (Double.greatestFiniteMagnitude, Double.leastNonzeroMagnitude)] {
            XCTAssertTrue(ActivityEdgeGeometry.ranges(time: time, period: period).isEmpty)
        }
        XCTAssertEqual(ActivityEdgeGeometry.fadeDuration, 0.45)
    }

    func testOMLXEdgeCompletionRequiresKnownFreshIdleAndLoadingOnlyBreathes() throws {
        let idle = summary(try server([model()]))
        let busy = summary(try server([model(active: 1, requests: "[{\"id\":\"r\",\"phase\":\"generating\"}]")]))
        let stale = summary(try server([model()], stale: true))
        let loading = summary(try server([model(loading: true)]))
        XCTAssertTrue(busy.hasActiveWork)
        XCTAssertTrue(busy.breathesStatus)
        XCTAssertTrue(loading.breathesStatus)
        XCTAssertFalse(loading.hasActiveWork)
        XCTAssertFalse(idle.breathesStatus)
        XCTAssertFalse(stale.breathesStatus)
        XCTAssertTrue(OMLXServerSummary.allowsEdge([busy, stale]))
        XCTAssertTrue(OMLXServerSummary.allowsEdge([idle, idle]))
        XCTAssertFalse(OMLXServerSummary.allowsEdge([idle, stale]))
        XCTAssertFalse(OMLXServerSummary.allowsEdge([loading]))
        XCTAssertFalse(OMLXServerSummary.allowsEdge([]))
    }

    func testRoomAudioPulseRequiresActiveFreshOnlineStatus() {
        for phase in ["processing", "speaking", "idle", "cancelling", "unknown"] {
            for online in [false, true] {
                let status = RoomAudioStatus(ok: true, clientOnline: online, phase: phase,
                    turnID: nil, canStop: false, ageSeconds: 1)
                XCTAssertEqual(ActivityMotionGate.roomAudioActive(status, receivedAt: now, now: now),
                    online && ["processing", "speaking"].contains(phase))
            }
        }
        XCTAssertFalse(ActivityMotionGate.roomAudioActive(nil, receivedAt: now, now: now))
        let failed = RoomAudioStatus(ok: false, clientOnline: true, phase: "speaking",
            turnID: nil, canStop: false, ageSeconds: 0)
        XCTAssertFalse(ActivityMotionGate.roomAudioActive(failed, receivedAt: now, now: now))
    }

    func testRoomAudioPulseExpiresUsingSourceAndReceiptAge() {
        for age in [Double.nan, .infinity, -1, 7] {
            let status = RoomAudioStatus(ok: true, clientOnline: true, phase: "speaking",
                turnID: nil, canStop: false, ageSeconds: age)
            XCTAssertFalse(ActivityMotionGate.roomAudioActive(status, receivedAt: now, now: now))
        }
        let status = RoomAudioStatus(ok: true, clientOnline: true, phase: "speaking",
            turnID: nil, canStop: false, ageSeconds: 5)
        XCTAssertTrue(ActivityMotionGate.roomAudioActive(status, receivedAt: now, now: now.addingTimeInterval(1)))
        XCTAssertFalse(ActivityMotionGate.roomAudioActive(status, receivedAt: now, now: now.addingTimeInterval(1.1)))
        XCTAssertFalse(ActivityMotionGate.roomAudioActive(status, receivedAt: nil, now: now))
        XCTAssertFalse(ActivityMotionGate.roomAudioActive(status, receivedAt: now.addingTimeInterval(1), now: now))
    }

    func testDecorativeMotionRequiresLiveGenerationAndEveryLifecycleGate() throws {
        let generating = summary(try server([model(active: 1,
            requests: "[{\"id\":\"r\",\"phase\":\"generating\",\"tokensPerSecond\":32}]")]))
        let ready = summary(try server([model()]))
        let stale = summary(try server([model()], stale: true))
        for (active, sceneActive, reduced, dimmed) in [
            (false, true, false, false), (true, false, false, false),
            (true, true, true, false), (true, true, false, true)
        ] {
            let policy = OMLXMotionPolicy(rows: [generating], active: active,
                sceneActive: sceneActive, reduceMotion: reduced, luminanceReduced: dimmed)
            XCTAssertFalse(policy.pulsesCPU)
            XCTAssertFalse(policy.transitionsMetric(for: generating))
        }
        let live = OMLXMotionPolicy(rows: [generating, stale], active: true,
            sceneActive: true, reduceMotion: false, luminanceReduced: false)
        XCTAssertTrue(live.pulsesCPU)
        XCTAssertTrue(live.transitionsMetric(for: generating))
        XCTAssertFalse(live.transitionsMetric(for: stale))
        for rows in [[], [ready], [stale], [summary(try server([model(loading: true)]))]] {
            XCTAssertFalse(OMLXMotionPolicy(rows: rows, active: true,
                sceneActive: true, reduceMotion: false, luminanceReduced: false).pulsesCPU)
        }
    }

    func testOneFixedSummaryRowEvenWhenManyModelsAreLoaded() throws {
        let value = summary(try server((0..<20).map { model("private-long-model-\($0)") }))
        XCTAssertEqual(value.serverLabel, "64 GB")
        XCTAssertEqual(value.status, "Ready")
        XCTAssertEqual(value.metric, "20 loaded")
        XCTAssertFalse(value.accessibilityValue.contains("private-long-model"))
    }

    func testSingleGenerationUsesOneRateLabelledAsAverageForAccessibility() throws {
        let value = summary(try server([model(active: 1, requests: #"[{"id":"r","phase":"generating","tokensPerSecond":32.4,"generatedTokens":846,"elapsedSeconds":26}]"#)]))
        XCTAssertEqual(value.status, "Generating")
        XCTAssertEqual(value.metric, "32 t/s")
        XCTAssertTrue(value.accessibilityValue.contains("Average generation speed"))
        XCTAssertFalse(value.accessibilityValue.contains("846"))
        XCTAssertFalse(value.metric?.contains("%") ?? true)
    }

    func testConcurrentRatesAreNeverSummedAveragedOrArbitrarilySelected() throws {
        let requests = #"[{"id":"a","phase":"generating","tokensPerSecond":10},{"id":"b","phase":"generating","tokensPerSecond":20}]"#
        XCTAssertEqual(summary(try server([model(active: 2, requests: requests)])).metric, "2 active")
        XCTAssertEqual(summary(try server([model("a", active: 1, requests: requests), model("b", active: 1)])).metric, "2 models")
    }

    func testPrefillUsesRealPercentageButLoadingHasNoInventedProgress() throws {
        let prefill = #"[{"id":"p","phase":"prefill","processedTokens":42,"totalTokens":100}]"#
        let value = summary(try server([model(active: 1, requests: prefill)]))
        XCTAssertEqual(value.status, "Prefill")
        XCTAssertEqual(value.metric, "42%")
        XCTAssertNil(summary(try server([model(loading: true)])).metric)
        XCTAssertNil(summary(try server([model(active: 1, requests: #"[{"id":"p","phase":"prefill"}]"#)])).metric)
    }

    func testQueueCountTakesPrecedenceWithoutAddingRows() throws {
        let value = summary(try server([model(active: 2, queued: 3)]))
        XCTAssertEqual(value.status, "Processing")
        XCTAssertEqual(value.metric, "3 queued")
    }

    func testStaleInactiveAndFailedSurfacesNeverExposeLiveMetrics() throws {
        let current = try server([model(active: 1, requests: #"[{"id":"r","phase":"generating","tokensPerSecond":30}]"#)])
        for value in [summary(current, available: false), summary(current, now: now.addingTimeInterval(7)),
                      summary(try server([model()], stale: true))] {
            XCTAssertFalse(value.fresh)
            XCTAssertEqual(value.status, "Stale")
            XCTAssertNil(value.metric)
        }
        let missing = OMLXServerSummary(id: "mac-mini-16", server: nil, now: now, requestStartedAt: nil, available: false)
        XCTAssertEqual(missing.status, "Unavailable")
        XCTAssertEqual(missing.serverLabel, "16 GB")
    }

    func testCounterOverflowDoesNotCrashPresentation() throws {
        let value = summary(try server([model("a", queued: Int.max), model("b", queued: Int.max)]))
        XCTAssertEqual(value.metric, "\(Int.max) queued")
    }

    func testVisibleInteractiveWatchSurfaceCadenceAndModalCoverage() {
        let endpoint = JarvisEndpoint(baseURL: URL(string: "http://jarvis.test:8790")!, token: "test")
        for (surface, interval) in [(OMLXRefreshSurface.iPhoneHome, 2.0), (.watchSystem, 5)] {
            XCTAssertEqual(OMLXPollConfiguration(endpoint: endpoint, surface: surface, visible: true, interactive: true).interval, interval)
            for (visible, interactive, covered) in [(false, true, false), (true, false, false), (true, true, true)] {
                XCTAssertNil(OMLXPollConfiguration(endpoint: endpoint, surface: surface, visible: visible, interactive: interactive, covered: covered).endpoint)
            }
        }
        let a = OMLXPollConfiguration(endpoint: endpoint, surface: .watchSystem, visible: true, interactive: true)
        let b = OMLXPollConfiguration(endpoint: endpoint, surface: .iPhoneHome, visible: true, interactive: true)
        XCTAssertNotEqual(a, b)
        XCTAssertEqual(Set([a, a]).count, 1)
    }

    func testMeasuredBottomClearanceLeavesLastCardAboveViewportEdge() {
        for viewport in [190.0, 224, 260] {
            for content in [180.0, 340, 600] {
                let clearance = 18.0
                let measured = content + clearance
                let end = CrownViewportBounds.maximum(content: measured, viewport: viewport)
                let cardBottom = content - end
                XCTAssertLessThanOrEqual(cardBottom, viewport - clearance)
            }
        }
    }

    func testCrownBoundsClampAtBothEndsAndAfterContentOrViewportChanges() {
        XCTAssertEqual(CrownViewportBounds.offset(-20, content: 330, viewport: 240), 0)
        XCTAssertEqual(CrownViewportBounds.offset(200, content: 330, viewport: 240), 90)
        XCTAssertEqual(CrownViewportBounds.offset(100, content: 250.5, viewport: 240), 10.5)
        XCTAssertEqual(CrownViewportBounds.offset(90, content: 220, viewport: 240), 0)
        XCTAssertEqual(CrownViewportBounds.offset(90, content: 330, viewport: 300), 30)
        XCTAssertEqual(CrownViewportBounds.offset(.nan, content: 330, viewport: 240), 0)
        XCTAssertEqual(CrownViewportBounds.maximum(content: .infinity, viewport: 240), 0)
    }

    func testCrownScrollDoesNotChangeTheFourPageDirectionPolicy() {
        XCTAssertEqual(WatchDashboardPage.allCases, [.terminal, .plugs, .system, .jobs])
        XCTAssertEqual(WatchDashboardPage.system.destination(verticalTranslation: -60, horizontalTranslation: 0), .jobs)
        XCTAssertEqual(WatchDashboardPage.system.destination(verticalTranslation: 60, horizontalTranslation: 0), .plugs)
        XCTAssertNil(WatchDashboardPage.jobs.destination(verticalTranslation: -60, horizontalTranslation: 0))
    }
}
