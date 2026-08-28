import Foundation
import XCTest
@testable import JARVISKit

final class WatchWidgetRouteTests: XCTestCase {
    func testCompositeWidgetRoutesResolveToFixedDestinations() throws {
        XCTAssertEqual(
            JARVISWatchWidgetRoute.destination(
                for: try XCTUnwrap(URL(string: "jarvis://quick-actions"))
            ),
            .quickActions
        )
        XCTAssertEqual(
            JARVISWatchWidgetRoute.destination(
                for: try XCTUnwrap(URL(string: "jarvis://now-playing"))
            ),
            .nowPlaying
        )
    }

    func testCompositeWidgetRoutesRejectArgumentsAndUnknownTargets() throws {
        let rejected = [
            "jarvis://quick-actions/run",
            "jarvis://quick-actions?name=unsafe",
            "jarvis://now-playing#unsafe",
            "https://now-playing",
            "jarvis://unknown"
        ]

        for raw in rejected {
            XCTAssertNil(
                JARVISWatchWidgetRoute.destination(
                    for: try XCTUnwrap(URL(string: raw))
                ),
                raw
            )
        }
    }
}
