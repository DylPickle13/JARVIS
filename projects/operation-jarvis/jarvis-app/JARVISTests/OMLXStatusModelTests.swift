import XCTest
import SwiftUI
import UIKit
import JARVISKit
@testable import JARVIS

private actor OMLXFetchGate {
    private var pending: [CheckedContinuation<OMLXSnapshot, Error>] = []
    var count = 0
    func fetch() async throws -> OMLXSnapshot {
        count += 1
        return try await withCheckedThrowingContinuation { pending.append($0) }
    }
    func succeed(_ snapshot: OMLXSnapshot) { pending.removeFirst().resume(returning: snapshot) }
}

private actor OMLXSequence {
    var count = 0
    func fetch(_ snapshot: OMLXSnapshot) throws -> OMLXSnapshot {
        count += 1
        if count == 1 { return snapshot }
        throw JarvisError.transport("private error must not reach UI")
    }
}

@MainActor
final class OMLXStatusModelTests: XCTestCase {
    private let endpoint = JarvisEndpoint(baseURL: URL(string: "http://jarvis.test:8790")!, token: "test")
    private func snapshot(_ name: String = "loaded") throws -> OMLXSnapshot {
        let json = """
        {"ok":true,"version":1,"servers":[
        {"id":"mac-mini-64","ok":true,"stale":false,"ageSeconds":0,"models":[
        {"id":"\(name)","isLoading":false,"activeRequests":0,"queuedRequests":0,"requests":[]}]},
        {"id":"mac-mini-16","ok":true,"stale":false,"ageSeconds":0,"models":[]}]}
        """
        return try JSONDecoder().decode(OMLXSnapshot.self, from: Data(json.utf8))
    }
    private func waitFor(_ condition: () async -> Bool) async {
        for _ in 0..<200 {
            if await condition() { return }
            try? await Task.sleep(for: .milliseconds(5))
        }
        XCTFail("condition did not become true")
    }

    func testCardRenderingNormalAccessibilityAndPartialOutage() throws {
        let now = Date(timeIntervalSince1970: 100)
        let json = #"{"id":"mac-mini-64","ok":true,"stale":false,"ageSeconds":0,"models":[{"id":"Qwen3.6-35B-A3B-4bit","isLoading":false,"activeRequests":1,"queuedRequests":0,"requests":[{"id":"r","phase":"generating","generatedTokens":846,"tokensPerSecond":32.4,"elapsedSeconds":26}]}],"memoryUsedBytes":26628797235,"memoryLimitBytes":51539607552,"memoryKind":"process","memoryPressure":"ok"}"#
        let busy = try JSONDecoder().decode(OMLXServerStatus.self, from: Data(json.utf8))
        let ready = try snapshot().servers[1]
        var mixedJSON = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any])
        var models = try XCTUnwrap(mixedJSON["models"] as? [[String: Any]])
        var second = models[0]
        second["id"] = "second-model"
        second["requests"] = [["id": "p", "phase": "prefill", "processedTokens": 42, "totalTokens": 100]]
        models.append(second)
        mixedJSON["models"] = models
        let mixed = try JSONDecoder().decode(OMLXServerStatus.self, from: JSONSerialization.data(withJSONObject: mixedJSON))
        var smallWatchHeight: CGFloat?
        for (name, size, available, compact, width) in [
            ("phone-minimal", DynamicTypeSize.large, true, false, 358.0),
            ("phone-accessibility", .accessibility3, true, false, 358),
            ("phone-outage", .large, false, false, 358),
            ("watch-minimal", .large, true, true, 160),
            ("watch-mixed", .large, true, true, 160),
            ("watch-accessibility", .accessibility3, true, true, 188)
        ] {
            let primary = name == "watch-mixed" ? mixed : busy
            let rows = [
                OMLXServerSummary(id: primary.id, server: primary, now: now, requestStartedAt: now, available: true),
                OMLXServerSummary(id: ready.id, server: ready, now: now, requestStartedAt: now, available: available)
            ]
            let content: AnyView
            if compact {
                content = AnyView(OMLXSummaryContent(rows: rows, compact: true)
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .frame(minHeight: 44)
                    .background(Color(white: 0.1), in: RoundedRectangle(cornerRadius: 13)))
            } else {
                content = AnyView(MinimalCard(padding: 11) { OMLXSummaryContent(rows: rows) })
            }
            let renderer = ImageRenderer(content: content.frame(width: width)
                .environment(\.colorScheme, .dark).environment(\.dynamicTypeSize, size))
            renderer.scale = 2
            let image = try XCTUnwrap(renderer.uiImage)
            XCTAssertEqual(image.size.width, width)
            if size == .large {
                XCTAssertGreaterThanOrEqual(image.size.height, compact ? 44 : 75)
                XCTAssertLessThanOrEqual(image.size.height, compact ? 70 : 100)
            }
            if name == "watch-minimal" { smallWatchHeight = image.size.height }
            if name == "watch-mixed" {
                XCTAssertEqual(image.size.height, try XCTUnwrap(smallWatchHeight), accuracy: 0.5,
                    "concurrent activity must not grow the normal-size card")
            }
            let attachment = XCTAttachment(image: image)
            attachment.name = "omlx-\(name)"
            attachment.lifetime = .keepAlways
            add(attachment)
        }
    }

    func testWatchConfiguredOwnerDeduplicatesStateRefreshAndStopsForDimmedCoveredOrOffPage() async throws {
        let gate = OMLXFetchGate()
        let model = OMLXStatusModel(fetch: { _ in try await gate.fetch() })
        let active = OMLXPollConfiguration(endpoint: endpoint, surface: .watchSystem, visible: true, interactive: true)
        model.configure(active)
        await waitFor { await gate.count == 1 }
        let good = try snapshot()
        await gate.succeed(good)
        await waitFor { model.snapshot != nil }
        for _ in 0..<10 { model.configure(active) }
        let count = await gate.count
        XCTAssertEqual(count, 1, "ordinary Watch state publication must not restart the oMLX task")
        for (visible, interactive, covered) in [(true, false, false), (true, true, true), (false, true, false)] {
            model.configure(.init(endpoint: endpoint, surface: .watchSystem,
                visible: visible, interactive: interactive, covered: covered))
            XCTAssertFalse(model.isPolling)
            XCTAssertTrue(model.unavailable)
            XCTAssertEqual(model.snapshot, good, "retain last-good data only as stale")
        }
        try await Task.sleep(for: .milliseconds(30))
        let after = await gate.count
        XCTAssertEqual(after, 1)
    }

    func testWatchSheetHasOneOwnerAndLateCoveredRequestCannotPublish() async throws {
        let gate = OMLXFetchGate()
        let model = OMLXStatusModel(fetch: { _ in try await gate.fetch() })
        let summary = OMLXPollConfiguration(endpoint: endpoint, surface: .watchSystem, visible: true, interactive: true)
        let detail = OMLXPollConfiguration(endpoint: endpoint, surface: .watchDetails, visible: true, interactive: true)
        model.configure(summary)
        await waitFor { await gate.count == 1 }
        model.configure(detail)
        await waitFor { await gate.count == 2 }
        await gate.succeed(try snapshot("obsolete summary"))
        await gate.succeed(try snapshot("detail"))
        await waitFor { model.snapshot != nil }
        XCTAssertEqual(model.snapshot?.servers[0].models?[0].id, "detail")
        model.configure(.init(endpoint: endpoint, surface: .watchDetails, visible: true, interactive: false))
        XCTAssertTrue(model.unavailable)
        XCTAssertFalse(model.isPolling)
    }

    func testConfiguredWatchStopsAnUncooperativePendingReadSynchronously() async throws {
        let gate = OMLXFetchGate()
        let model = OMLXStatusModel(fetch: { _ in try await gate.fetch() })
        model.configure(.init(endpoint: endpoint, surface: .watchDetails, visible: true, interactive: true))
        await waitFor { await gate.count == 1 }
        model.configure(.init(endpoint: endpoint, surface: .watchDetails, visible: false, interactive: true))
        XCTAssertFalse(model.isPolling)
        await gate.succeed(try snapshot("late"))
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertNil(model.snapshot)
    }

    func testInactiveHomeDoesNotRequestAnything() async {
        let gate = OMLXFetchGate()
        let model = OMLXStatusModel(fetch: { _ in try await gate.fetch() })
        await model.run(endpoint: nil)
        let count = await gate.count
        XCTAssertEqual(count, 0)
        XCTAssertFalse(model.isPolling)
        XCTAssertNil(model.snapshot)
    }

    func testCancelledFetchCannotPublishLateResults() async throws {
        let gate = OMLXFetchGate()
        let model = OMLXStatusModel(fetch: { _ in try await gate.fetch() })
        let task = Task { await model.run(endpoint: endpoint) }
        await waitFor { await gate.count == 1 }
        task.cancel()
        await gate.succeed(try snapshot())
        await task.value
        XCTAssertNil(model.snapshot)
        XCTAssertTrue(model.unavailable)
        XCTAssertFalse(model.isPolling)
    }

    func testEndpointGenerationRejectsObsoleteCompletionAndDoesNotStopNewPoller() async throws {
        let gate = OMLXFetchGate()
        let model = OMLXStatusModel(fetch: { _ in try await gate.fetch() })
        let old = Task { await model.run(endpoint: endpoint) }
        await waitFor { await gate.count == 1 }
        let second = JarvisEndpoint(baseURL: URL(string: "http://other.test:8790")!, token: "other")
        let current = Task { await model.run(endpoint: second) }
        await waitFor { await gate.count == 2 }
        await gate.succeed(try snapshot("old"))
        await old.value
        XCTAssertNil(model.snapshot)
        XCTAssertTrue(model.isPolling)
        await gate.succeed(try snapshot("new"))
        await waitFor { model.snapshot != nil }
        XCTAssertEqual(model.snapshot?.servers[0].models?[0].id, "new")
        XCTAssertFalse(model.unavailable)
        current.cancel()
        await current.value
        XCTAssertTrue(model.unavailable)
    }

    func testLeavingHomeInvalidatesOutstandingRequestEvenIfTransportIgnoresCancellation() async throws {
        let gate = OMLXFetchGate()
        let model = OMLXStatusModel(fetch: { _ in try await gate.fetch() })
        let task = Task { await model.run(endpoint: endpoint) }
        await waitFor { await gate.count == 1 }
        await model.run(endpoint: nil)
        await gate.succeed(try snapshot())
        await task.value
        XCTAssertNil(model.snapshot)
        XCTAssertFalse(model.isPolling)
    }

    func testFailureKeepsLastGoodButImmediatelyMarksItUnavailable() async throws {
        let sequence = OMLXSequence()
        let good = try snapshot()
        let model = OMLXStatusModel(fetch: { _ in try await sequence.fetch(good) },
            sleep: { _ in try await Task.sleep(for: .milliseconds(20)) })
        let task = Task { await model.run(endpoint: endpoint) }
        await waitFor { model.snapshot != nil && model.unavailable }
        XCTAssertEqual(model.snapshot, good)
        XCTAssertNotNil(model.requestStartedAt)
        XCTAssertTrue(model.isPolling)
        task.cancel()
        await task.value
        let count = await sequence.count
        try await Task.sleep(for: .milliseconds(50))
        let later = await sequence.count
        XCTAssertEqual(later, count, "no polling after Home task cancellation")
    }

    func testMetricsLabelGenerationAverageAndNeverShowCompletionPercent() throws {
        let json = #"{"id":"r","phase":"generating","generatedTokens":846,"tokensPerSecond":32.4,"elapsedSeconds":26}"#
        let request = try JSONDecoder().decode(OMLXRequestStatus.self, from: Data(json.utf8))
        let text = OMLXFormat.metrics(request)
        XCTAssertTrue(text.contains("846"))
        XCTAssertTrue(text.contains("tok/s avg"))
        XCTAssertTrue(text.contains("26s"))
        XCTAssertFalse(text.contains("%"))
        XCTAssertNil(request.prefillFraction)
    }

    func testMissingMetricsAndInvalidDurationsAreNotInvented() throws {
        let request = try JSONDecoder().decode(OMLXRequestStatus.self, from: Data(#"{"id":"r","phase":"generating"}"#.utf8))
        XCTAssertEqual(OMLXFormat.metrics(request), "Metrics unavailable")
        XCTAssertEqual(OMLXFormat.duration(.infinity), "—")
        XCTAssertEqual(OMLXFormat.duration(-1), "—")
        XCTAssertEqual(OMLXFormat.duration(Double.greatestFiniteMagnitude), "—")
        XCTAssertEqual(OMLXFormat.duration(61), "1m 1s")
    }
}
