import XCTest
@testable import JARVISKit

final class PiSessionNameTests: XCTestCase {
    func testExplicitUnicodeNamesTrimWhitespaceWithoutInventingTopics() {
        XCTAssertEqual(PiSessionName.validated("  Dashboard names 🎛️  "), "Dashboard names 🎛️")
        XCTAssertEqual(PiSessionName.validated("日本語のセッション"), "日本語のセッション")
        XCTAssertEqual(PiSessionName.validated("Family 👨‍👩‍👧‍👦"), "Family 👨‍👩‍👧‍👦")
        XCTAssertNil(PiSessionName.validated(nil))
        XCTAssertNil(PiSessionName.validated("   "))
    }

    func testControlsBidiAndOversizedNamesAreNotRendered() {
        for value in ["a\nb", "a\rb", "a\tb", "a\u{0}b", "\u{1B}[31mname", "a\u{2028}b", "a\u{202E}b", "a\u{2066}b", String(repeating: "x", count: 257)] {
            XCTAssertNil(PiSessionName.validated(value))
        }
        XCTAssertNotNil(PiSessionName.validated(String(repeating: "x", count: 256)))
        // Bound Unicode scalars like the backend, not multi-scalar emoji clusters.
        XCTAssertNil(PiSessionName.validated(String(repeating: "👨‍👩‍👧‍👦", count: 40)))
    }

    func testNamesAreIndependentOfLifecycleAndFallbackNeverCallsBusySessionsNew() {
        for state in [PiSessionLifecycle.running, .idle, .compacting, .new, .offline, .unknown] {
            XCTAssertEqual(PiSessionName.cardTitle(name: "Actual Pi name", lifecycle: state), "Actual Pi name")
            XCTAssertEqual(PiSessionName.cardTitle(name: nil, lifecycle: state), state == .new ? "New session" : "Unnamed session")
        }
    }

    func testOldNullAndMalformedOptionalNamesDoNotInvalidateLifecycle() throws {
        for extra in ["", ",\"name\":null", ",\"name\":123", ",\"name\":true", ",\"name\":{}", ",\"name\":\"a\\nb\""] {
            let json = "{\"sessionID\":3,\"lifecycle\":\"running\",\"active\":true\(extra)}"
            let row = try JSONDecoder().decode(PiMobileSession.self, from: Data(json.utf8))
            XCTAssertNil(row.name)
            XCTAssertEqual(row.sessionID, 3)
            XCTAssertEqual(row.resolvedLifecycle, .running)
        }
        let legacy = try JSONDecoder().decode(PiMobileSession.self, from: Data(#"{"sessionID":1,"active":false}"#.utf8))
        XCTAssertEqual(legacy.resolvedLifecycle, .idle)
    }

    func testNamedSessionsRoundTripAndStayBoundToTheirIDsInAnyOrder() throws {
        let json = #"{"mobileSessions":[{"sessionID":9,"lifecycle":"idle","name":"Native app"},{"sessionID":1,"lifecycle":"compacting","name":"Pi Desk"},{"sessionID":10,"lifecycle":"running","name":"Room session"}]}"#
        let pi = try JSONDecoder().decode(PiSubsystem.self, from: Data(json.utf8))
        let rows = try XCTUnwrap(pi.mobileSessions)
        XCTAssertEqual(rows.first(where: { $0.sessionID == 1 })?.name, "Pi Desk")
        XCTAssertEqual(rows.first(where: { $0.sessionID == 9 })?.name, "Native app")
        XCTAssertEqual(JARVISTerminalSlot.one.lifecycle(in: pi), .compacting)
        XCTAssertEqual(JARVISTerminalSlot.roomAudio.lifecycle(in: pi), .running)
        let roundTrip = try JSONDecoder().decode([PiMobileSession].self, from: JSONEncoder().encode(rows))
        XCTAssertEqual(rows, roundTrip)
    }
}
