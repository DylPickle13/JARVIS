import XCTest
@testable import JARVISKit

final class WatchDashboardPageTests: XCTestCase {
    func testJobsReturnsOnlyOnUpwardSwipe() {
        XCTAssertEqual(WatchDashboardPage.jobs.destination(verticalTranslation: -52, horizontalTranslation: 0), .system)
        XCTAssertNil(WatchDashboardPage.jobs.destination(verticalTranslation: 52, horizontalTranslation: 0))
        XCTAssertNil(WatchDashboardPage.jobs.destination(verticalTranslation: 200, horizontalTranslation: 0))
    }

    func testOtherPagesKeepTheirDirectionsAndTerminalOwnsItsGestures() {
        XCTAssertEqual(WatchDashboardPage.plugs.destination(verticalTranslation: -80, horizontalTranslation: 0), .system)
        XCTAssertEqual(WatchDashboardPage.plugs.destination(verticalTranslation: 80, horizontalTranslation: 0), .terminal)
        XCTAssertEqual(WatchDashboardPage.system.destination(verticalTranslation: -80, horizontalTranslation: 0), .jobs)
        XCTAssertEqual(WatchDashboardPage.system.destination(verticalTranslation: 80, horizontalTranslation: 0), .plugs)
        XCTAssertNil(WatchDashboardPage.terminal.destination(verticalTranslation: -80, horizontalTranslation: 0))
        XCTAssertNil(WatchDashboardPage.terminal.destination(verticalTranslation: 80, horizontalTranslation: 0))
    }

    func testShortHorizontalDiagonalAndInvalidDragsDoNotNavigate() {
        for page in WatchDashboardPage.allCases {
            for (vertical, horizontal) in [(-51.0, 0.0), (51, 0), (-80, 80), (80, -80), (-80, 100), (.nan, 0), (-Double.infinity, 0), (-80, .nan)] {
                XCTAssertNil(page.destination(verticalTranslation: vertical, horizontalTranslation: horizontal))
            }
        }
    }
}
