import XCTest
@testable import JARVISKit

// Opt-in live integration tests. They never read the repository .env and do
// not silently hide a failure when explicitly enabled:
//
//   JARVIS_LIVE_TESTS=1 JARVISD_TEST_URL=http://127.0.0.1:8790 swift test
final class LiveIntegrationTests: XCTestCase {
    static func enabled() -> Bool {
        ProcessInfo.processInfo.environment["JARVIS_LIVE_TESTS"] == "1"
    }

    static func endpoint() throws -> JarvisEndpoint {
        let raw = ProcessInfo.processInfo.environment["JARVISD_TEST_URL"] ?? "http://127.0.0.1:8790"
        guard let url = URL(string: raw) else {
            throw XCTSkip("JARVISD_TEST_URL is not a valid URL")
        }
        return JarvisEndpoint(
            baseURL: url,
            token: ProcessInfo.processInfo.environment["JARVIS_API_TOKEN"] ?? ""
        )
    }

    private func requireEndpoint(_ client: JarvisClient) async throws -> JarvisEndpoint {
        try XCTSkipUnless(Self.enabled(), "Set JARVIS_LIVE_TESTS=1 to run live daemon tests")
        let endpoint = try Self.endpoint()
        do {
            _ = try await client.health(endpoint)
        } catch {
            throw XCTSkip("jarvisd not reachable at \(endpoint.baseURL): \(error)")
        }
        return endpoint
    }

    func testLiveHealthAndState() async throws {
        let client = JarvisClient()
        let endpoint = try await requireEndpoint(client)
        let health = try await client.health(endpoint)
        XCTAssertTrue(health.ok)
        XCTAssertFalse(health.version?.isEmpty ?? true)

        let state = try await client.state(endpoint)
        XCTAssertTrue(state.ok)
        XCTAssertNotNil(state.summary)
        XCTAssertNotNil(state.subsystems?.network?.macLanIp)
        XCTAssertNotNil(state.subsystems?.plugs)
    }

    func testLiveCommandPlugList() async throws {
        let client = JarvisClient()
        let endpoint = try await requireEndpoint(client)
        let result = try await client.command(endpoint, action: "plug-list")
        XCTAssertEqual(result.action, "plug-list")
        XCTAssertTrue(result.ok)
    }

    func testLiveCommandRejectsCast() async throws {
        let client = JarvisClient()
        let endpoint = try await requireEndpoint(client)
        do {
            _ = try await client.command(endpoint, action: "cast-status")
            XCTFail("expected cast-status to be rejected")
        } catch let JarvisError.http(status, body) {
            XCTAssertEqual(status, 400)
            XCTAssertTrue(body.contains("not allowlisted"), "body was: \(body)")
        }
    }
}
