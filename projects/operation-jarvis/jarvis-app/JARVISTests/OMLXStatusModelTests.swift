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
        for (name, size, available) in [("normal", DynamicTypeSize.large, true),
            ("accessibility", .accessibility3, true), ("partial-outage", .large, false)] {
            let content = MinimalCard {
                VStack(alignment: .leading, spacing: 12) {
                    Label("oMLX", systemImage: "cpu").font(.subheadline.weight(.semibold))
                    OMLXServerContent(id: busy.id, server: busy, now: now, requestStartedAt: now,
                        available: true, checking: false, expanded: false)
                    Divider()
                    OMLXServerContent(id: ready.id, server: ready, now: now, requestStartedAt: now,
                        available: available, checking: false, expanded: false)
                }
            }
            .padding(16).frame(width: 390)
            .background(JarvisBackdrop())
            .environment(\.colorScheme, .dark).environment(\.dynamicTypeSize, size)
            let renderer = ImageRenderer(content: content)
            renderer.scale = 2
            let image = try XCTUnwrap(renderer.uiImage)
            XCTAssertEqual(image.size.width, 390)
            XCTAssertGreaterThan(image.size.height, 100)
            if size == .large { XCTAssertLessThan(image.size.height, 500) }
            let attachment = XCTAttachment(image: image)
            attachment.name = "omlx-card-\(name)"
            attachment.lifetime = .keepAlways
            add(attachment)
        }
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
