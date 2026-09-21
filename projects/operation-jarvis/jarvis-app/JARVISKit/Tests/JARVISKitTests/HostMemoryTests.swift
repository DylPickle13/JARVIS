import Foundation
import XCTest
@testable import JARVISKit

final class HostMemoryTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 100)
    private var sample: [String: Any] {
        ["ok": true, "stale": false, "ageSeconds": 10,
         "usedBytes": 38 * 1_073_741_824, "totalBytes": 64 * 1_073_741_824,
         "definition": "macos-nonpurgeable-anonymous-wired-compressed"]
    }
    private func server(_ memory: [String: Any]?, activityFresh: Bool = true) throws -> OMLXServerStatus {
        var json: [String: Any] = ["id": "mac-mini-64", "ok": activityFresh,
            "stale": !activityFresh, "ageSeconds": 0, "models": [],
            "memoryUsedBytes": 12 * 1_073_741_824, "memoryLimitBytes": 48 * 1_073_741_824]
        if let memory { json["hostMemory"] = memory }
        return try JSONDecoder().decode(OMLXServerStatus.self, from: JSONSerialization.data(withJSONObject: json))
    }
    private func row(_ server: OMLXServerStatus, elapsed: Double = 0, available: Bool = true) -> OMLXServerSummary {
        .init(id: server.id, server: server, now: now.addingTimeInterval(elapsed), requestStartedAt: now, available: available)
    }
    func testHostMemoryNotProcessMemoryIsDisplayedAndSpoken() throws {
        let value = row(try server(sample))
        XCTAssertEqual(value.hostMemoryText, "38G")
        XCTAssertEqual(value.compactServerLabel, "64G")
        XCTAssertTrue(value.cardAccessibilityValue.contains("Whole Mac memory used 38.0 of 64"))
        XCTAssertFalse(value.cardAccessibilityValue.contains("12.0"))
    }
    func testOldBackendNeverFallsBackToProcessMemory() throws {
        let value = row(try server(nil))
        XCTAssertEqual(value.hostMemoryText, "—")
        XCTAssertTrue(value.cardAccessibilityValue.contains("Mac memory unavailable"))
    }
    func testHostFreshnessIndependentFromInference() throws {
        let value = row(try server(sample, activityFresh: false))
        XCTAssertFalse(value.fresh)
        XCTAssertEqual(value.hostMemoryText, "38G")
        XCTAssertEqual(value.speedText, "—")
    }
    func testAgeIncludesElapsedClientTimeAndTransportAvailability() throws {
        let value = try server(sample)
        XCTAssertEqual(row(value, elapsed: 20).hostMemoryText, "38G")
        XCTAssertEqual(row(value, elapsed: 20.01).hostMemoryText, "—")
        XCTAssertEqual(row(value, available: false).hostMemoryText, "—")
        XCTAssertFalse(value.hostMemory!.isFresh(requestStartedAt: nil, now: now))
    }
    func testFailedStaleMissingAndInvalidFieldsStayUnknown() throws {
        let bad: [(String, Any)] = [("ok", false), ("stale", true), ("ageSeconds", -1),
            ("ageSeconds", 31), ("usedBytes", -1), ("usedBytes", 65 * 1_073_741_824),
            ("totalBytes", 0), ("definition", "process")]
        for (key, value) in bad {
            var memory = sample
            memory[key] = value
            XCTAssertEqual(row(try server(memory)).hostMemoryText, "—", key)
        }
        for key in sample.keys {
            var memory = sample
            memory.removeValue(forKey: key)
            XCTAssertEqual(row(try server(memory)).hostMemoryText, "—", key)
        }
    }
}
