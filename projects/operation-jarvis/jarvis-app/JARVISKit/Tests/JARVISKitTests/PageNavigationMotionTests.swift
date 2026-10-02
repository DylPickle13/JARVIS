import XCTest
@testable import JARVISKit

final class PageNavigationMotionTests: XCTestCase {
    func testDirectionFollowsPageOrderWithoutMotionForSamePage() {
        XCTAssertEqual(PageNavigationMotion.direction(from: 0, to: 1), .forward)
        XCTAssertEqual(PageNavigationMotion.direction(from: 4, to: 3), .backward)
        XCTAssertNil(PageNavigationMotion.direction(from: 2, to: 2))
        XCTAssertEqual(PageNavigationMotion.Direction.forward.sign, 1)
        XCTAssertEqual(PageNavigationMotion.Direction.backward.sign, -1)
    }

    func testPhoneAndWatchShareTimingAndProportionalTravel() {
        XCTAssertEqual(PageNavigationMotion.duration, 0.30)
        for extent in [176.0, 224, 320, 390, 844] {
            XCTAssertEqual(PageNavigationMotion.travel(extent: extent) / extent, 0.14, accuracy: 0.0001)
        }
    }

    func testInvalidAndEmptyViewportsHaveNoTravel() {
        for extent in [0.0, -1, .nan, .infinity, -.infinity] {
            XCTAssertEqual(PageNavigationMotion.travel(extent: extent), 0)
        }
    }

    func testReducedMotionBackgroundCoverageAndAlwaysOnDisableMotion() {
        XCTAssertTrue(PageNavigationMotion.allows(active: true, reduceMotion: false))
        XCTAssertFalse(PageNavigationMotion.allows(active: false, reduceMotion: false))
        XCTAssertFalse(PageNavigationMotion.allows(active: true, reduceMotion: true))
        XCTAssertFalse(PageNavigationMotion.allows(active: true, reduceMotion: false, covered: true))
        XCTAssertFalse(PageNavigationMotion.allows(active: true, reduceMotion: false, dimmed: true))
    }
}
