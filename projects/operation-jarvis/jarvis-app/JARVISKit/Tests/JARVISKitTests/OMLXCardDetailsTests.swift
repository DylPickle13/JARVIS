import Foundation
import XCTest
@testable import JARVISKit

final class OMLXCardDetailsTests: XCTestCase {
    private func server(_ models: String, extra: String = "") throws -> OMLXServerStatus {
        let json = """
        {"id":"mac-mini-64","ok":true,"stale":false,"ageSeconds":0,"models":[\(models)]\(extra)}
        """
        return try JSONDecoder().decode(OMLXServerStatus.self, from: Data(json.utf8))
    }
    private func model(_ id: String = "mlx-community/Qwen3.6-35B-A3B-4bit", active: Int = 0,
                       queued: Int = 0, loading: Bool = false, requests: String = "[]") -> String {
        """
        {"id":"\(id)","isLoading":\(loading),"activeRequests":\(active),"queuedRequests":\(queued),"requests":\(requests)}
        """
    }
    func testFullNamesAndEveryModelAreRetained() throws {
        let names = ["mlx-community/Qwen3.6-35B-A3B-4bit", "mlx-community/Another-complete-model-name-8bit"]
        let detail = OMLXCardDetails(server: try server(names.map { model($0) }.joined(separator: ",")))
        XCTAssertEqual(detail.modelNames, names.sorted())
        XCTAssertEqual(detail.modelName(at: 0), names.sorted()[0])
        XCTAssertEqual(detail.modelName(at: 1), names.sorted()[1])
        XCTAssertEqual(detail.modelName(at: 2), names.sorted()[0])
        for name in names { XCTAssertTrue(detail.accessibilityValue.contains(name)) }
    }
    func testSingleRequestUsesReportedValuesAndNeverInventsPrefill() throws {
        let request = #"[{"id":"r","phase":"generating","tokensPerSecond":32.4,"generatedTokens":846}]"#
        let detail = OMLXCardDetails(server: try server(model(active: 1, requests: request)))
        XCTAssertEqual(detail.speed, 32.4)
        XCTAssertEqual(detail.generatedTokens, 846)
        XCTAssertNil(detail.prefillFraction)
        XCTAssertEqual(detail.text(for: .tokens), "846 tokens")
        XCTAssertEqual(detail.text(for: .prefill), "—")
        XCTAssertTrue(detail.accessibilityValue.contains("846 generated tokens"))
    }
    func testConcurrentWorkDoesNotCombineRatesOrChooseOneRequest() throws {
        let request = #"[{"id":"a","phase":"generating","tokensPerSecond":10,"generatedTokens":100},{"id":"b","phase":"generating","tokensPerSecond":20,"generatedTokens":200}]"#
        let detail = OMLXCardDetails(server: try server(model(active: 2, queued: 3, requests: request)))
        XCTAssertNil(detail.speed)
        XCTAssertNil(detail.generatedTokens)
        XCTAssertEqual(detail.activeRequests, 2)
        XCTAssertEqual(detail.queuedRequests, 3)
        XCTAssertEqual(detail.text(for: .activity), "2 active requests")
    }
    func testPrefillIsOnlyReportedDuringPrefillAndInvalidCountersStayUnknown() throws {
        let request = #"[{"id":"r","phase":"prefill","processedTokens":42,"totalTokens":100}]"#
        let detail = OMLXCardDetails(server: try server(model(active: 1, requests: request)))
        XCTAssertEqual(detail.prefillFraction, 0.42)
        XCTAssertEqual(detail.text(for: .prefill), "42%")
        XCTAssertNil(detail.speed)
        let invalid = OMLXCardDetails(server: try server(model(active: -1, queued: -2)))
        XCTAssertNil(invalid.activeRequests)
        XCTAssertNil(invalid.queuedRequests)
        let overflow = OMLXCardDetails(server: try server([model("a", active: Int.max), model("b", active: Int.max)].joined(separator: ",")))
        XCTAssertEqual(overflow.activeRequests, Int.max)
    }
    func testMemoryIsReportedWithItsKindAndLoadingDoesNotCountAsLoaded() throws {
        let detail = OMLXCardDetails(server: try server([model("ready"), model("loading", loading: true)].joined(separator: ","),
            extra: #", "memoryUsedBytes":12884901888,"memoryLimitBytes":51539607552,"memoryKind":"process","memoryPressure":"soft""#))
        XCTAssertEqual(detail.loadedModels, 1)
        XCTAssertEqual(detail.modelNames.count, 2)
        XCTAssertEqual(detail.memoryUsed, 12 * 1_073_741_824)
        XCTAssertEqual(detail.pressure, "Soft")
        XCTAssertTrue(detail.accessibilityValue.contains("Process memory used"))
        let absent = OMLXCardDetails(server: try server("", extra: #", "memoryUsedBytes":-1,"memoryLimitBytes":0,"memoryPressure":"unsupported""#))
        XCTAssertNil(absent.memoryUsed)
        XCTAssertNil(absent.memoryLimit)
        XCTAssertEqual(absent.pressure, "—")
        XCTAssertEqual(absent.modelName(at: 0), "No models loaded")
    }
    func testStaleAndUnavailableSummaryNeverCarryDetailPayloads() throws {
        let now = Date(timeIntervalSince1970: 100)
        let value = try server(model())
        let live = OMLXServerSummary(id: value.id, server: value, now: now, requestStartedAt: now, available: true)
        XCTAssertNotNil(live.details)
        for (available, date) in [(false, now), (true, now.addingTimeInterval(7))] {
            let row = OMLXServerSummary(id: value.id, server: value, now: date, requestStartedAt: now, available: available)
            XCTAssertNil(row.details)
        }
    }
    func testNarrowPagesExposeAllStatisticsWithoutAdditionalRows() {
        let wide = OMLXDetailPage.sequence(modelCount: 2, narrow: false)
        XCTAssertEqual(wide, [.models(0), .models(1), .activity, .load, .memory])
        let narrow = OMLXDetailPage.sequence(modelCount: 1, narrow: true)
        XCTAssertEqual(narrow, [.models(0), .speed, .tokens, .prefill, .active, .queued, .loaded, .used, .limit, .pressure])
        XCTAssertEqual(OMLXDetailPage.sequence(modelCount: 0, narrow: false).first, .models(0))
    }
    func testOnlyOverflowingNamesMoveAndFinalTextHasAnEndHold() {
        XCTAssertEqual(OMLXMarqueeTiming.duration(content: 90, viewport: 100, speed: 18, reduceMotion: false), 7)
        XCTAssertEqual(OMLXMarqueeTiming.offset(elapsed: 100, content: 90, viewport: 100, speed: 18, reduceMotion: false), 0)
        let duration = OMLXMarqueeTiming.duration(content: 460, viewport: 100, speed: 18, reduceMotion: false)
        XCTAssertEqual(duration, 23.5)
        XCTAssertEqual(OMLXMarqueeTiming.offset(elapsed: 1, content: 460, viewport: 100, speed: 18, reduceMotion: false), 0)
        XCTAssertEqual(OMLXMarqueeTiming.offset(elapsed: duration - 2, content: 460, viewport: 100, speed: 18, reduceMotion: false), 360)
        XCTAssertEqual(OMLXMarqueeTiming.offset(elapsed: .nan, content: 460, viewport: 100, speed: 18, reduceMotion: false), 0)
    }
    func testReducedMotionUsesStaticOverlappingSegmentsInsteadOfSliding() {
        let duration = OMLXMarqueeTiming.duration(content: 460, viewport: 100, speed: 18, reduceMotion: true)
        XCTAssertEqual(duration, 42)
        XCTAssertEqual(OMLXMarqueeTiming.offset(elapsed: 6.9, content: 460, viewport: 100, speed: 18, reduceMotion: true), 0)
        XCTAssertEqual(OMLXMarqueeTiming.offset(elapsed: 7, content: 460, viewport: 100, speed: 18, reduceMotion: true), 88)
        XCTAssertEqual(OMLXMarqueeTiming.offset(elapsed: duration - 1, content: 460, viewport: 100, speed: 18, reduceMotion: true), 360)
    }
}
