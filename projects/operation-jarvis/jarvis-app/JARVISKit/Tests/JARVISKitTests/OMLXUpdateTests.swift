import Foundation
import XCTest
@testable import JARVISKit

final class OMLXUpdateTests: XCTestCase {
    let now = Date(timeIntervalSince1970: 100)

    func row(update: String? = nil, stale: Bool = false, available: Bool = true) throws -> OMLXServerSummary {
        let field = update.map { ",\"update\":\($0)" } ?? ""
        let json = """
        {"id":"mac-mini-64","ok":true,"stale":\(stale),"ageSeconds":0,"models":[]\(field)}
        """
        let server = try JSONDecoder().decode(OMLXServerStatus.self, from: Data(json.utf8))
        return .init(id: server.id, server: server, now: now, requestStartedAt: now, available: available)
    }

    let confirmed = """
    {"ok":true,"available":true,"latestVersion":"0.3.5","stale":false,"ageSeconds":10}
    """

    func testConfirmedUpdateAndOlderBackendCompatibility() throws {
        XCTAssertTrue(try row(update: confirmed).updateAvailable)
        XCTAssertFalse(try row().updateAvailable)
        XCTAssertFalse(try row(update: "null").updateAvailable)
        XCTAssertFalse(try row(update: "{}").updateAvailable)
    }

    func testUnknownFailedStaleAndUnavailableNeverShowIndicator() throws {
        XCTAssertFalse(try row(update: confirmed, stale: true).updateAvailable)
        XCTAssertFalse(try row(update: confirmed, available: false).updateAvailable)
        for (old, new) in [
            ("\"ok\":true", "\"ok\":false"),
            ("\"available\":true", "\"available\":false"),
            ("\"stale\":false", "\"stale\":true"),
            ("\"ageSeconds\":10", "\"ageSeconds\":7201"),
            ("\"ageSeconds\":10", "\"ageSeconds\":-1"),
            ("\"ageSeconds\":10", "\"ageSeconds\":null"),
            ("\"latestVersion\":\"0.3.5\"", "\"latestVersion\":null")
        ] {
            XCTAssertFalse(try row(update: confirmed.replacingOccurrences(of: old, with: new)).updateAvailable)
        }
    }

    func testUpdateAgeIncludesElapsedTimeSinceRequest() throws {
        let update = try JSONDecoder().decode(OMLXUpdateStatus.self, from: Data(confirmed.utf8))
        XCTAssertTrue(update.isAvailable(requestStartedAt: now, now: now.addingTimeInterval(7190)))
        XCTAssertFalse(update.isAvailable(requestStartedAt: now, now: now.addingTimeInterval(7191)))
        XCTAssertFalse(update.isAvailable(requestStartedAt: nil, now: now))
    }
}
