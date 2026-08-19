import XCTest
@testable import JARVISKit

// Live integration tests against a running jarvisd (default 127.0.0.1:8790).
// These skip gracefully when the daemon isn't reachable (e.g. in CI), so they
// never break a plain `swift test` run. Run locally with the daemon up to
// exercise the real client → daemon → decode path end to end.
final class LiveIntegrationTests: XCTestCase {
    static let endpointURL = URL(string: "http://127.0.0.1:8790")!
    static let envPath = "/Users/dylanrapanan/JARVIS/.env"

    static func token() -> String {
        if let t = ProcessInfo.processInfo.environment["JARVIS_API_TOKEN"], !t.isEmpty { return t }
        guard let content = try? String(contentsOfFile: envPath, encoding: .utf8) else { return "" }
        for line in content.split(separator: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("JARVIS_API_TOKEN=") {
                return String(trimmed.dropFirst("JARVIS_API_TOKEN=".count)).trimmingCharacters(in: .whitespaces)
            }
        }
        return ""
    }

    private func skipIfDown(_ client: JarvisClient, _ endpoint: JarvisEndpoint) async throws {
        do {
            _ = try await client.health(endpoint)
        } catch {
            throw XCTSkip("jarvisd not reachable at \(endpoint.baseURL) — skipping live test")
        }
    }

    func testLiveHealthAndState() async throws {
        let client = JarvisClient()
        let token = Self.token()
        let endpoint = JarvisEndpoint(baseURL: Self.endpointURL, token: token)
        try await skipIfDown(client, endpoint)

        let health = try await client.health(endpoint)
        XCTAssertTrue(health.ok)
        XCTAssertEqual(health.version, "0.1.0")

        let state = try await client.state(endpoint)
        XCTAssertTrue(state.ok)
        XCTAssertNotNil(state.summary)
        XCTAssertNotNil(state.subsystems?.network?.macLanIp)
        // Plugs should be present with 4 entries on this install.
        XCTAssertEqual(state.subsystems?.plugs?.count, 4)
        print("LIVE state summary: \(String(describing: state.summary))")
        print("LIVE network: lan=\(state.subsystems?.network?.macLanIp ?? "nil") ts=\(state.subsystems?.network?.tailscaleIp ?? "nil")")
    }

    func testLiveCommandPlugList() async throws {
        let client = JarvisClient()
        let endpoint = JarvisEndpoint(baseURL: Self.endpointURL, token: Self.token())
        try await skipIfDown(client, endpoint)

        let result = try await client.command(endpoint, action: "plug-list")
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.action, "plug-list")
    }

    func testLiveCommandRejectsCast() async throws {
        let client = JarvisClient()
        let endpoint = JarvisEndpoint(baseURL: Self.endpointURL, token: Self.token())
        try await skipIfDown(client, endpoint)

        do {
            _ = try await client.command(endpoint, action: "cast-status")
            XCTFail("expected cast-status to be rejected")
        } catch let JarvisError.http(status, body) {
            XCTAssertEqual(status, 400)
            XCTAssertTrue(body.contains("not allowlisted"), "body was: \(body)")
        }
    }
}
