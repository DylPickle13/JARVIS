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
        for (surface, interval) in [(OMLXRefreshSurface.iPhoneHome, 2.0), (.watchSystem, 5), (.watchDetails, 3)] {
            XCTAssertEqual(OMLXPollConfiguration(endpoint: endpoint, surface: surface, visible: true, interactive: true).interval, interval)
            for (visible, interactive, covered) in [(false, true, false), (true, false, false), (true, true, true)] {
                XCTAssertNil(OMLXPollConfiguration(endpoint: endpoint, surface: surface, visible: visible, interactive: interactive, covered: covered).endpoint)
            }
        }
        let a = OMLXPollConfiguration(endpoint: endpoint, surface: .watchSystem, visible: true, interactive: true)
        let b = OMLXPollConfiguration(endpoint: endpoint, surface: .watchDetails, visible: true, interactive: true)
        XCTAssertNotEqual(a, b)
        XCTAssertEqual(Set([a, a]).count, 1)
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
