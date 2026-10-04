import XCTest
@testable import JARVISKit
#if canImport(SwiftUI)
import SwiftUI
#endif

final class TerminalSessionStatusTests: XCTestCase {
    func testAllTenSlotsResolveByIDRatherThanArrayOrder() throws {
        let statuses: [PiSessionLifecycle] = [.running, .idle, .offline, .new, .compacting, .unknown, .idle, .running, .new, .compacting]
        let sessions = JARVISTerminalSlot.allCases.reversed().map {
            PiMobileSession(sessionID: $0.rawValue, lifecycle: statuses[$0.rawValue - 1])
        }
        let encoded = try JSONEncoder().encode(sessions)
        let json = "{\"mobileSessions\":\(String(decoding: encoded, as: UTF8.self))}"
        let pi = try JSONDecoder().decode(PiSubsystem.self, from: Data(json.utf8))
        for slot in JARVISTerminalSlot.allCases {
            XCTAssertEqual(slot.lifecycle(in: pi), statuses[slot.rawValue - 1])
        }
    }

    func testStaleMissingAndLegacyStatus() throws {
        let decoder = JSONDecoder()
        let stale = try decoder.decode(PiSubsystem.self, from: Data(#"{"stale":true,"mobileSessions":[{"sessionID":1,"lifecycle":"running"}]}"#.utf8))
        let legacy = try decoder.decode(PiSubsystem.self, from: Data(#"{"mobileSessions":[{"sessionID":1,"active":true},{"sessionID":10,"active":false}]}"#.utf8))
        XCTAssertEqual(JARVISTerminalSlot.one.lifecycle(in: stale), .unknown)
        XCTAssertEqual(JARVISTerminalSlot.one.lifecycle(in: nil), .unknown)
        XCTAssertEqual(JARVISTerminalSlot.two.lifecycle(in: legacy), .unknown)
        XCTAssertEqual(JARVISTerminalSlot.one.lifecycle(in: legacy), .running)
        XCTAssertEqual(JARVISTerminalSlot.roomAudio.lifecycle(in: legacy), .idle)
    }

    #if canImport(SwiftUI)
    func testRunningSweepsForwardAndWatchUsesSlowerCadence() {
        let start = PiSessionMotionGeometry.highlights(lifecycle: .running, time: 0, compact: false)[0]
        let later = PiSessionMotionGeometry.highlights(lifecycle: .running, time: 0.9, compact: false)[0]
        let watch = PiSessionMotionGeometry.highlights(lifecycle: .running, time: 0.9, compact: true)[0]
        XCTAssertLessThan(start, later)
        XCTAssertLessThan(watch, later)
        XCTAssertEqual(later, 0.5, accuracy: 0.001)
    }

    func testCompactingHighlightsConvergeSymmetrically() {
        let early = PiSessionMotionGeometry.highlights(lifecycle: .compacting, time: 0.5, compact: false)
        let late = PiSessionMotionGeometry.highlights(lifecycle: .compacting, time: 2, compact: false)
        XCTAssertEqual(late.count, 2)
        XCTAssertEqual(late[0] + late[1], 1, accuracy: 0.001)
        XCTAssertGreaterThan(late[0], early[0])
        XCTAssertLessThan(late[1], early[1])
    }

    func testNonBusyStatesAndInvalidTimeHaveNoTravellingHighlight() {
        for state in [PiSessionLifecycle.idle, .new, .offline, .unknown] {
            XCTAssertTrue(PiSessionMotionGeometry.highlights(lifecycle: state, time: 1, compact: false).isEmpty)
        }
        XCTAssertTrue(PiSessionMotionGeometry.highlights(lifecycle: .running, time: .infinity, compact: false).isEmpty)
        XCTAssertTrue(PiSessionMotionGeometry.highlights(lifecycle: .compacting, time: .nan, compact: true).isEmpty)
    }

    func testSharedStatusColorsMatchHomePalette() {
        XCTAssertEqual(PiSessionLifecycle.offline.statusColor, .gray)
        XCTAssertEqual(PiSessionLifecycle.idle.statusColor, .purple)
        XCTAssertEqual(PiSessionLifecycle.running.statusColor, .green)
        XCTAssertEqual(PiSessionLifecycle.new.statusColor, .cyan)
        XCTAssertEqual(PiSessionLifecycle.compacting.statusColor, Color(red: 1, green: 122.0 / 255, blue: 0))
        XCTAssertNotEqual(PiSessionLifecycle.compacting.statusColor, PiSessionLifecycle.new.statusColor)
        XCTAssertNotEqual(PiSessionLifecycle.compacting.statusColor, PiSessionLifecycle.unknown.statusColor)
        XCTAssertEqual(PiSessionLifecycle.unknown.statusColor, Color(red: 0.96, green: 0.58, blue: 0.16))
    }
    #endif
}
