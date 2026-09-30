import Foundation
import XCTest
@testable import JARVISKit

enum HistoryFixture {
    static func object(window: SystemHistoryWindow = .day, component: String? = nil, end: Date = Date(), partial: Bool = false) -> [String: Any] {
        let start = end.addingTimeInterval(-window.seconds)
        func stamp(_ d: Date) -> String { d.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true)) }
        let ids = component.map { [$0] } ?? ["services", "pi", "network", "devices", "overall"]
        return ["ok": true, "schemaVersion": 1, "scope": "cached_status_health", "window": window.rawValue,
            "from": stamp(start), "to": stamp(end), "sampleIntervalSeconds": 60,
            "resolutionSeconds": Int(window.resolution), "coverageLeaseSeconds": 90, "retentionSeconds": 604800,
            "earliestSampleAt": stamp(start), "latestSampleAt": stamp(end.addingTimeInterval(-5)),
            "series": ids.map { id in ["id": id, "buckets": (0..<window.bucketCount).map { i -> [String: Any] in
                let lo = start.addingTimeInterval(Double(i)*window.resolution)
                return ["from": stamp(lo), "to": stamp(lo.addingTimeInterval(window.resolution)),
                    "state": partial ? "unknown" : "healthy", "reasonCodes": ["current"],
                    "coverageSeconds": partial ? window.resolution/2 : window.resolution,
                    "missingSeconds": partial ? window.resolution/2 : 0,
                    "stateSeconds": ["healthy": partial ? window.resolution/2 : window.resolution],
                    "mixed": partial, "sourceObservedAt": stamp(lo)]
            }] }]
    }
    static func decode(_ object: [String: Any]) throws -> SystemHistoryResponse {
        try JSONDecoder().decode(SystemHistoryResponse.self, from: JSONSerialization.data(withJSONObject: object))
    }
    static func response(window: SystemHistoryWindow = .day, component: String? = nil, end: Date = Date(), partial: Bool = false) throws -> SystemHistoryResponse {
        try decode(object(window: window, component: component, end: end, partial: partial))
    }
}

private actor HistoryDriver {
    let response: SystemHistoryResponse
    var calls = 0
    var sleepValues: [TimeInterval] = []
    var error: JarvisError?
    var hold = false
    var pending: [Int: CheckedContinuation<SystemHistoryResponse, Error>] = [:]
    init(response: SystemHistoryResponse) { self.response = response }
    func setError(_ error: JarvisError?) { self.error = error }
    func setHold() { hold = true }
    func fetch() async throws -> SystemHistoryResponse {
        calls += 1
        if let error { throw error }
        if hold {
            let index = calls
            return try await withCheckedThrowingContinuation { pending[index] = $0 }
        }
        return response
    }
    func complete(_ index: Int, response: SystemHistoryResponse) { pending.removeValue(forKey: index)?.resume(returning: response) }
    func sleep(_ seconds: TimeInterval) async throws {
        sleepValues.append(seconds)
        try await Task.sleep(for: .seconds(3600))
    }
}

@MainActor
final class SystemHistoryTests: XCTestCase {
    let endpoint = JarvisEndpoint(baseURL: URL(string: "http://fixture.invalid:8790")!, token: "fixture-only")
    func configuration(visible: Bool = true, interactive: Bool = true, connected: Bool = true,
                       surface: SystemHistoryConfiguration.Surface = .phone, endpoint: JarvisEndpoint? = nil) -> SystemHistoryConfiguration {
        .init(endpoint: endpoint ?? self.endpoint, surface: surface, visible: visible, interactive: interactive, connected: connected)
    }
    func wait(_ predicate: () async -> Bool) async {
        for _ in 0..<500 {
            if await predicate() { return }
            try? await Task.sleep(for: .milliseconds(2))
        }
        XCTFail("Bounded history fixture wait expired")
    }
    private func model(_ driver: HistoryDriver) -> SystemHistoryModel {
        .init(fetch: { _, _, _ in try await driver.fetch() }, sleep: { try await driver.sleep($0) })
    }

    func testCanonicalWindowsAndSingleWatchSeriesAreValidated() throws {
        for window in [SystemHistoryWindow.hour, .day, .week] {
            let r = try HistoryFixture.response(window: window)
            XCTAssertNoThrow(try r.validated(window: window))
            XCTAssertEqual(r.series[0].buckets.count, window.bucketCount)
        }
        let r = try HistoryFixture.response(window: .hour, component: "overall")
        XCTAssertNoThrow(try r.validated(window: .hour, component: "overall"))
        XCTAssertThrowsError(try r.validated(window: .day))
        XCTAssertThrowsError(try r.validated(window: .hour))
    }

    func testPartialHealthyEvidenceRemainsUnknownWithExplicitGap() throws {
        let r = try HistoryFixture.response(window: .hour, partial: true)
        XCTAssertNoThrow(try r.validated(window: .hour))
        let b = r.series[0].buckets[0]
        XCTAssertEqual(b.state, .unknown)
        XCTAssertEqual(b.observedState, .healthy)
        XCTAssertTrue(b.hasGap)
        XCTAssertEqual(b.coverageSeconds, 30)
        XCTAssertEqual(b.missingSeconds, 30)
    }

    func testOneMillisecondGapCannotBecomeSolidGreen() throws {
        var o = HistoryFixture.object(window: .hour)
        var s = o["series"] as! [[String: Any]]
        var b = s[0]["buckets"] as! [[String: Any]]
        b[0]["coverageSeconds"] = 59.999; b[0]["missingSeconds"] = 0.001
        b[0]["stateSeconds"] = ["healthy": 59.999]; b[0]["state"] = "unknown"; b[0]["mixed"] = true
        s[0]["buckets"] = b; o["series"] = s
        let r = try HistoryFixture.decode(o)
        XCTAssertNoThrow(try r.validated(window: .hour))
        XCTAssertTrue(r.series[0].buckets[0].hasGap)
    }

    func testFutureNaiveDatesUnknownSchemaAndWrongScopeFailClosed() throws {
        for (key, value) in [("schemaVersion", 2 as Any), ("scope", "physical_uptime" as Any), ("from", "2026-09-29T12:00:00" as Any), ("ok", false as Any)] {
            var o = HistoryFixture.object(); o[key] = value
            XCTAssertThrowsError(try HistoryFixture.decode(o).validated(window: .day))
        }
        XCTAssertThrowsError(try HistoryFixture.response(end: Date().addingTimeInterval(60)).validated(window: .day))
        XCTAssertNil(SystemHistoryDates.parse("2026-09-29T12:00:00"))
    }

    func testMalformedCoverageAndInventedHealthyPartialBucketsAreRejected() throws {
        for delta: [String: Any] in [["coverageSeconds": -1], ["missingSeconds": 1], ["stateSeconds": ["healthy": 1]],
            ["mixed": true], ["reasonCodes": ["private-token-error"]], ["sourceObservedAt": "2099-01-01T00:00:00Z"]] {
            var o = HistoryFixture.object(window: .hour)
            var s = o["series"] as! [[String: Any]]; var b = s[0]["buckets"] as! [[String: Any]]
            b[0].merge(delta) { _, new in new };s[0]["buckets"] = b;o["series"] = s
            XCTAssertThrowsError(try HistoryFixture.decode(o).validated(window: .hour))
        }
        var o = HistoryFixture.object(window: .hour, partial: true)
        var s = o["series"] as! [[String: Any]];var b = s[0]["buckets"] as! [[String: Any]]
        b[0]["state"] = "healthy";s[0]["buckets"] = b;o["series"] = s
        XCTAssertThrowsError(try HistoryFixture.decode(o).validated(window: .hour))
    }

    func testLastSampleLeaseCannotBeRejuvenatedByRecentQueryTimestamp() throws {
        let now = Date()
        var o = HistoryFixture.object(window: .hour, end: now)
        o["latestSampleAt"] = now.addingTimeInterval(-180).formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true))
        XCTAssertThrowsError(try HistoryFixture.decode(o).validated(window: .hour),
            "A recent query date cannot justify green evidence beyond the last recording lease")
    }

    func testExistingTrustedNetworkEndpointPollsWithoutAdditionalTokenOnPhoneAndWatch() async throws {
        for surface in [SystemHistoryConfiguration.Surface.phone, .watch] {
            let response = try HistoryFixture.response(window: surface == .phone ? .day : .hour,
                component: surface == .watch ? "overall" : nil)
            let driver = HistoryDriver(response: response)
            let m = model(driver)
            m.configure(configuration(surface: surface, endpoint: .init(baseURL: endpoint.baseURL, token: "")))
            await wait { m.snapshot != nil }
            let calls = await driver.calls
            XCTAssertEqual(calls, 1); XCTAssertNil(m.notice); XCTAssertTrue(m.isPolling)
            m.configure(configuration(visible: false, surface: surface, endpoint: .init(baseURL: endpoint.baseURL, token: "")))
            XCTAssertFalse(m.isPolling)
        }
    }

    func testBackendAuthenticationDenialIsReportedWithoutFallback() async throws {
        for status in [401, 403] {
            let driver = HistoryDriver(response: try HistoryFixture.response())
            await driver.setError(.http(status: status, body: "private error"))
            let m = model(driver)
            m.configure(configuration(endpoint: .init(baseURL: endpoint.baseURL, token: "")))
            await wait { m.notice != nil && !m.isLoading }
            XCTAssertEqual(m.notice, "History access denied by backend")
            let calls = await driver.calls; XCTAssertEqual(calls, 1)
            m.configure(configuration(visible: false))
        }
    }

    func testBucketBoundsDuplicateSeriesAndMissingSamplesFailClosed() throws {
        var o = HistoryFixture.object(window: .hour)
        var s = o["series"] as! [[String: Any]];s[0]["id"] = s[1]["id"];o["series"] = s
        XCTAssertThrowsError(try HistoryFixture.decode(o).validated(window: .hour))
        o = HistoryFixture.object(window: .hour);s = o["series"] as! [[String: Any]]
        var b = s[0]["buckets"] as! [[String: Any]];b.removeLast();s[0]["buckets"] = b;o["series"] = s
        XCTAssertThrowsError(try HistoryFixture.decode(o).validated(window: .hour))
        o = HistoryFixture.object(window: .hour);o["latestSampleAt"] = NSNull()
        XCTAssertThrowsError(try HistoryFixture.decode(o).validated(window: .hour))
    }

    func testShortObservedFailureSurvivesAggregationWithoutInventingItsDuration() throws {
        var o = HistoryFixture.object(window: .hour)
        var s = o["series"] as! [[String: Any]];var b = s[0]["buckets"] as! [[String: Any]]
        b[0]["state"] = "unavailable";b[0]["stateSeconds"] = ["healthy": 50, "unavailable": 10]
        b[0]["mixed"] = true;b[0]["reasonCodes"] = ["current", "collector_failed"]
        s[0]["buckets"] = b;o["series"] = s
        let r = try HistoryFixture.decode(o).validated(window: .hour)
        XCTAssertEqual(r.series[0].buckets[0].state, .unavailable)
        XCTAssertEqual(r.series[0].buckets[0].stateSeconds["unavailable"], 10)
        XCTAssertTrue(r.series[0].buckets[0].mixed)
    }

    func testOnlyVisibleInteractiveConnectedEndpointContextsPoll() {
        XCTAssertTrue(configuration().shouldPoll)
        XCTAssertFalse(configuration(visible: false).shouldPoll)
        XCTAssertFalse(configuration(interactive: false).shouldPoll)
        XCTAssertFalse(configuration(connected: false).shouldPoll)
        XCTAssertTrue(configuration(endpoint: .init(baseURL: endpoint.baseURL, token: "")).shouldPoll)
        XCTAssertFalse(SystemHistoryConfiguration(endpoint: nil, surface: .phone, visible: true, interactive: true, connected: true).shouldPoll)
        let watch = configuration(surface: .watch)
        XCTAssertEqual(watch.window, .hour);XCTAssertEqual(watch.component, "overall")
        XCTAssertEqual(configuration().window, .day);XCTAssertNil(configuration().component)
    }

    func testHiddenAndAlwaysOnContextsNeverFetchAndIdenticalConfigurationDeduplicates() async throws {
        let driver = HistoryDriver(response: try HistoryFixture.response())
        let m = model(driver)
        m.configure(configuration(visible: false));m.configure(configuration(interactive: false));await Task.yield()
        let before = await driver.calls;XCTAssertEqual(before, 0)
        m.configure(configuration());m.configure(configuration())
        await wait { m.snapshot != nil }
        await wait { await driver.sleepValues == [60] }
        let count = await driver.calls;XCTAssertEqual(count, 1)
        m.configure(configuration(visible: false));XCTAssertFalse(m.isPolling);XCTAssertFalse(m.isLoading)
        XCTAssertNotNil(m.snapshot, "Pausing preserves absolute-time historical evidence")
    }

    func testFailurePreservesHistoryAndDoesNotExposeRawErrorsOrChangeCadence() async throws {
        let driver = HistoryDriver(response: try HistoryFixture.response())
        let m = model(driver);m.configure(configuration());await wait { m.snapshot != nil }
        let old = m.snapshot
        await driver.setError(.http(status: 503, body: "private-token=fixture-only"))
        m.refresh();await wait { m.notice != nil && !m.isLoading }
        XCTAssertEqual(m.snapshot, old);XCTAssertEqual(m.notice, "History temporarily unavailable")
        XCTAssertFalse(m.notice?.contains("private-token") ?? true)
        m.configure(configuration(visible: false))
    }

    func testExplicitRefreshCannotDuplicateInFlightRequest() async throws {
        let driver = HistoryDriver(response: try HistoryFixture.response());await driver.setHold()
        let m = model(driver);m.configure(configuration());await wait { m.isLoading }
        m.refresh();m.refresh();await Task.yield()
        let count = await driver.calls;XCTAssertEqual(count, 1)
        await driver.complete(1, response: try HistoryFixture.response());await wait { m.snapshot != nil }
        m.configure(configuration(visible: false))
    }

    func testEndpointChangeClearsSynchronouslyAndRejectsLateOldReply() async throws {
        let driver = HistoryDriver(response: try HistoryFixture.response());await driver.setHold()
        let m = model(driver);m.configure(configuration());await wait { await driver.calls == 1 }
        let other = JarvisEndpoint(baseURL: URL(string: "http://other.invalid:8790")!, token: "other-fixture")
        m.configure(configuration(endpoint: other));XCTAssertNil(m.snapshot)
        await wait { await driver.calls == 2 }
        let fresh = try HistoryFixture.response(end: Date().addingTimeInterval(-10))
        await driver.complete(2, response: fresh);await wait { m.snapshot != nil }
        await driver.complete(1, response: try HistoryFixture.response(end: Date().addingTimeInterval(-100)))
        await Task.yield();XCTAssertEqual(m.snapshot, fresh)
        m.configure(configuration(visible: false, endpoint: other))
    }

    func testBackgroundCancellationRejectsLateReply() async throws {
        let driver = HistoryDriver(response: try HistoryFixture.response());await driver.setHold()
        let m = model(driver);m.configure(configuration());await wait { await driver.calls == 1 }
        m.configure(configuration(interactive: false))
        await driver.complete(1, response: try HistoryFixture.response());await Task.yield()
        XCTAssertNil(m.snapshot);XCTAssertFalse(m.isLoading);XCTAssertFalse(m.isPolling)
    }

    func testOldResponseAndRecorderGapCannotBeRejuvenatedByReceipt() async throws {
        let r = try HistoryFixture.response(end: Date().addingTimeInterval(-200))
        let driver = HistoryDriver(response: r);let m = model(driver)
        m.configure(configuration());await wait { m.snapshot != nil }
        XCTAssertTrue(m.isStale())
        XCTAssertFalse(m.isStale(now: r.end!))
        m.configure(configuration(visible: false))
    }
}
