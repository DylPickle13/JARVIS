import XCTest
@testable import JARVISKit

final class SessionPresentationTests: XCTestCase {
    func testCameraSpeakerTitlePreservesWireIdentity() throws {
        XCTAssertEqual(RoomAudioSpeaker.pi.title, "Camera speaker")
        XCTAssertEqual(RoomAudioSpeaker.mac.title, "Mac speaker")
        XCTAssertEqual(RoomAudioSpeaker.pi.rawValue, "pi")
        XCTAssertEqual(try JSONDecoder().decode(RoomAudioSpeaker.self, from: Data("\"pi\"".utf8)), .pi)
        XCTAssertEqual(String(data: try JSONEncoder().encode(RoomAudioSpeaker.pi), encoding: .utf8), "\"pi\"")
    }

    func testPhoneAndWatchIndicatorGroupsAreThreeThreeThreeOne() {
        let slots = JARVISTerminalSlot.allCases
        XCTAssertEqual(slots.filter(\.hasLeadingIndicatorGap).map(\.rawValue), [4, 7, 10])
        var groups: [[Int]] = [[]]
        for slot in slots {
            if slot.hasLeadingIndicatorGap { groups.append([]) }
            groups[groups.count - 1].append(slot.rawValue)
        }
        XCTAssertEqual(groups, [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]])
        XCTAssertEqual(groups.map(\.count), [3, 3, 3, 1])
    }

    func testRoomAudioGapDoesNotChangeNavigationOrSessionIdentity() {
        XCTAssertEqual(JARVISTerminalSlot.roomAudio.rawValue, 10)
        XCTAssertEqual(JARVISTerminalSlot.nine.next, .roomAudio)
        XCTAssertEqual(JARVISTerminalSlot.roomAudio.previous, .nine)
        XCTAssertNil(JARVISTerminalSlot.roomAudio.next)
        XCTAssertEqual(JARVISTerminalSlot.allCases.count, 10)
    }
}
