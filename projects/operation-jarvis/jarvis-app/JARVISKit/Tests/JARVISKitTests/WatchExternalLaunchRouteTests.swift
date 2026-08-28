import Foundation
import XCTest
@testable import JARVISKit

final class WatchExternalLaunchRouteTests: XCTestCase {
    func testFixedExternalLaunchRoutesResolveWithoutCallerArguments() throws {
        XCTAssertEqual(
            JARVISWatchExternalLaunchRoute.destination(
                for: try XCTUnwrap(URL(string: "jarvis://launch-shortcuts"))
            )?.absoluteString,
            "shortcuts://"
        )
        XCTAssertEqual(
            JARVISWatchExternalLaunchRoute.destination(
                for: try XCTUnwrap(URL(string: "jarvis://launch-spotify"))
            )?.absoluteString,
            "https://open.spotify.com/"
        )
    }

    func testExternalLaunchRoutesRejectPathsQueriesFragmentsAndUnknownTargets() throws {
        let rejected = [
            "jarvis://launch-shortcuts/run",
            "jarvis://launch-shortcuts?name=unsafe",
            "jarvis://launch-spotify#unsafe",
            "https://launch-spotify",
            "jarvis://launch-other"
        ]

        for raw in rejected {
            XCTAssertNil(
                JARVISWatchExternalLaunchRoute.destination(
                    for: try XCTUnwrap(URL(string: raw))
                ),
                raw
            )
        }
    }
}
