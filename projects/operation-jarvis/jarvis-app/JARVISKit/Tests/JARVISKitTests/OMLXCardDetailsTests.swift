import Foundation
import XCTest
@testable import JARVISKit

final class OMLXCardDetailsTests: XCTestCase {
    private func server(_ models: String) throws -> OMLXServerStatus {
        let json = """
        {"id":"mac-mini-64","ok":true,"stale":false,"ageSeconds":0,"models":[\(models)]}
        """
        return try JSONDecoder().decode(OMLXServerStatus.self, from: Data(json.utf8))
    }
    private func model(_ id: String = "mlx-community/Qwen3.6-35B-A3B-4bit", active: Int = 0,
                       queued: Int = 0, loading: Bool = false, requests: String = "[]") -> String {
        """
        {"id":"\(id)","isLoading":\(loading),"activeRequests":\(active),"queuedRequests":\(queued),"requests":\(requests)}
        """
    }
    func testCompactNameRetainsFamilyVersionAndSize() {
        XCTAssertEqual(OMLXCardDetails.shortName("mlx-community/Qwen3.6-35B-A3B-4bit"), "Q3.6-35B")
        XCTAssertEqual(OMLXCardDetails.shortName("mlx-community/Qwen3.5-9B-4bit"), "Q3.5-9B")
        XCTAssertEqual(OMLXCardDetails.shortName("org/Llama-3.3-70B-Instruct-4bit"), "Llama-3.3-70B")
        XCTAssertEqual(OMLXCardDetails.shortName("org/Unknown-model-name"), "Unknown-model-name")
    }
    func testFullNamesRemainAccessibleAndIdleSelectionIsDeterministic() throws {
        let names = ["mlx-community/Qwen3.6-35B-A3B-4bit", "mlx-community/Another-complete-model-name-8bit"]
        let a = OMLXCardDetails(server: try server(names.map { model($0) }.joined(separator: ",")))
        let b = OMLXCardDetails(server: try server(names.reversed().map { model($0) }.joined(separator: ",")))
        XCTAssertEqual(a.modelNames, names.sorted())
        XCTAssertEqual(a.modelLabel, b.modelLabel)
        XCTAssertTrue(a.modelLabel.hasSuffix(" +1"))
        for name in names { XCTAssertTrue(a.accessibilityValue.contains(name)) }
    }
    func testActiveModelWinsOverIdleModelAndHasExtraCount() throws {
        let detail = OMLXCardDetails(server: try server([model("a-idle"), model(active: 1)].joined(separator: ",")))
        XCTAssertEqual(detail.modelLabel, "Q3.6-35B +1")
    }
    func testSingleRequestUsesReportedGenerationSpeed() throws {
        let request = #"[{"id":"r","phase":"generating","tokensPerSecond":32.4,"generatedTokens":846}]"#
        let detail = OMLXCardDetails(server: try server(model(active: 1, requests: request)))
        XCTAssertEqual(detail.speed, 32.4)
        XCTAssertEqual(detail.speedText, "32")
        XCTAssertTrue(detail.accessibilityValue.contains("32.4"))
    }
    func testConcurrentWorkDoesNotCombineRatesOrChooseOneRequest() throws {
        let request = #"[{"id":"a","phase":"generating","tokensPerSecond":10},{"id":"b","phase":"generating","tokensPerSecond":20}]"#
        let detail = OMLXCardDetails(server: try server(model(active: 2, queued: 3, requests: request)))
        XCTAssertNil(detail.speed)
        XCTAssertEqual(detail.speedText, "—")
        XCTAssertEqual(detail.modelLabel, "Multi")
        XCTAssertEqual(detail.activeRequests, 2)
        XCTAssertEqual(detail.queuedRequests, 3)
    }
    func testConcurrentModelsDisplayMulti() throws {
        let detail = OMLXCardDetails(server: try server([model("a", active: 1), model("b", active: 1)].joined(separator: ",")))
        XCTAssertEqual(detail.modelLabel, "Multi")
        XCTAssertNil(detail.speed)
    }
    func testIdlePrefillAndInvalidSpeedStayUnknown() throws {
        XCTAssertEqual(OMLXCardDetails(server: try server(model())).speedText, "—")
        for phase in ["prefill", "processing", "queued"] {
            let request = """
            [{"id":"r","phase":"\(phase)","tokensPerSecond":42}]
            """
            XCTAssertNil(OMLXCardDetails(server: try server(model(active: 1, requests: request))).speed)
        }
        for rate in [-1, 0] {
            let request = """
            [{"id":"r","phase":"generating","tokensPerSecond":\(rate)}]
            """
            XCTAssertNil(OMLXCardDetails(server: try server(model(active: 1, requests: request))).speed)
        }
    }
    func testEmptyAndInvalidCounts() throws {
        XCTAssertEqual(OMLXCardDetails(server: try server("")).modelLabel, "No models")
        let invalid = OMLXCardDetails(server: try server(model(active: -1, queued: -2)))
        XCTAssertNil(invalid.activeRequests)
        XCTAssertNil(invalid.queuedRequests)
        let overflow = OMLXCardDetails(server: try server([model("a", active: Int.max), model("b", active: Int.max)].joined(separator: ",")))
        XCTAssertEqual(overflow.activeRequests, Int.max)
    }
    func testStaleAndUnavailableSummaryNeverCarryModelOrSpeed() throws {
        let now = Date(timeIntervalSince1970: 100)
        let value = try server(model())
        let live = OMLXServerSummary(id: value.id, server: value, now: now, requestStartedAt: now, available: true)
        XCTAssertNotNil(live.details)
        for (available, date) in [(false, now), (true, now.addingTimeInterval(7))] {
            let row = OMLXServerSummary(id: value.id, server: value, now: date, requestStartedAt: now, available: available)
            XCTAssertNil(row.details)
            XCTAssertEqual(row.speedText, "—")
            XCTAssertFalse(row.modelLabel.contains("Q3.6"))
        }
    }
}
