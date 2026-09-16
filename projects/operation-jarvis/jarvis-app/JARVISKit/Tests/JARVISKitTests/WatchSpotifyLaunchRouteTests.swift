import XCTest
@testable import JARVISKit

final class WatchSpotifyLaunchRouteTests: XCTestCase {
    func testOnlyExactLocalLauncherRouteIsAccepted() {
        XCTAssertTrue(JARVISWatchSpotifyRoute.accepts(JARVISWatchSpotifyRoute.widgetURL))
        for text in ["jarvis://talk", "jarvis://terminal", "https://spotify", "jarvis://spotify/", "jarvis://spotify?url=https://example.com", "jarvis://spotify#play", "jarvis://user@spotify", "jarvis://spotify:443", "jarvis://spotify/play"] {
            XCTAssertFalse(JARVISWatchSpotifyRoute.accepts(URL(string: text)!), text)
        }
    }

    func testDestinationIsFixedHomeUniversalLinkWithoutPlaybackOrPhoneParameters() {
        XCTAssertEqual(JARVISWatchSpotifyRoute.destination.absoluteString, "https://open.spotify.com/home")
        XCTAssertNil(JARVISWatchSpotifyRoute.destination.query)
        XCTAssertNil(JARVISWatchSpotifyRoute.destination.fragment)
    }
}
