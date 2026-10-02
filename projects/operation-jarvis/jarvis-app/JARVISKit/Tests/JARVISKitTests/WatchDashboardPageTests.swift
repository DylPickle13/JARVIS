import XCTest
@testable import JARVISKit

final class WatchDashboardPageTests: XCTestCase {
    func testWatchRestoresDedicatedPagesWithHomeAboveTerminal() {
        XCTAssertEqual(WatchDashboardPage.allCases, [.home, .terminal, .plugs, .jarvis, .jobs])
        XCTAssertEqual(WatchDashboardPage.terminal.destination(verticalTranslation: 80, horizontalTranslation: 0), .home)
        XCTAssertEqual(WatchDashboardPage.home.destination(verticalTranslation: -80, horizontalTranslation: 0), .terminal)
        XCTAssertEqual(WatchDashboardPage.terminal.destination(verticalTranslation: -80, horizontalTranslation: 0), .plugs)
    }

    func testForwardAndReverseRoutesAgreeForEveryAdjacentPage() {
        let pages = WatchDashboardPage.allCases
        for index in 0..<(pages.count - 1) {
            XCTAssertEqual(pages[index].destination(verticalTranslation: -80, horizontalTranslation: 0), pages[index + 1])
            XCTAssertEqual(pages[index + 1].destination(verticalTranslation: 80, horizontalTranslation: 0), pages[index])
        }
    }

    func testNeitherEndWraps() {
        for distance in [52.0, 200] {
            XCTAssertNil(WatchDashboardPage.home.destination(verticalTranslation: distance, horizontalTranslation: 0))
            XCTAssertNil(WatchDashboardPage.jobs.destination(verticalTranslation: -distance, horizontalTranslation: 0))
        }
    }

    func testShortHorizontalDiagonalAndInvalidDragsDoNotNavigate() {
        for page in WatchDashboardPage.allCases {
            for (vertical, horizontal) in [(-51.0, 0.0), (51, 0), (-80, 80), (80, -80), (-80, 100), (.nan, 0), (-Double.infinity, 0), (-80, .nan)] {
                XCTAssertNil(page.destination(verticalTranslation: vertical, horizontalTranslation: horizontal))
            }
        }
    }
}
