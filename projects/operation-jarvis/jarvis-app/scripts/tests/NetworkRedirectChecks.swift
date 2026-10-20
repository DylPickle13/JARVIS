import Foundation
import XCTest
import JARVISKit

final class NetworkRedirectChecks: XCTestCase {
    struct Route: Decodable { let status: Int; let http: String; let https: String }
    private var routes: [Route] {
        try! JSONDecoder().decode([Route].self, from: Data(ProcessInfo.processInfo.environment["JARVIS_TEST_ROUTES"]!.utf8))
    }
    private var pin: String { ProcessInfo.processInfo.environment["JARVIS_TEST_PIN"]! }

    func testDashboardRefusesEveryRedirectWithoutForwardingToken() async {
        for route in routes {
            let endpoint = JarvisEndpoint(baseURL: URL(string: route.http)!, token: "synthetic-api-token")
            do { _ = try await JarvisClient().state(endpoint); XCTFail("Redirect must fail") }
            catch let JarvisError.http(status, _) { XCTAssertEqual(status, route.status) }
            catch { XCTFail("Unexpected error: \(error)") }
        }
    }

    func testDiscoveryDoesNotPromoteRedirectingEndpoint() async {
        for route in routes {
            let discovered = await JarvisClient().discover([URL(string: route.http)!], timeout: 1)
            XCTAssertNil(discovered)
        }
    }

    func testReadRecoveryUsesApprovedCandidateNotRedirectTarget() async throws {
        let approved = URL(string: ProcessInfo.processInfo.environment["JARVIS_TEST_APPROVED"]!)!
        let resolved = try await JarvisClient().resolveState(preferredEndpoint: URL(string: routes[0].http)!,
            candidates: [approved], token: "synthetic-api-token", discoveryTimeout: 1)
        XCTAssertEqual(resolved.endpointURL, approved)
        XCTAssertTrue(resolved.usedDiscovery)
        XCTAssertTrue(resolved.state.ok)
    }

    func testPinnedTerminalInputNeverReplaysAcrossRedirect() async {
        for route in routes {
            let config = WatchTerminalConfiguration(endpoint: route.https,
                token: String(repeating: "x", count: 32), certificateSHA256: pin)
            let client = WatchTerminalClient(configuration: config, preferredBaseURL: URL(string: route.https)!)
            defer { client.close() }
            do {
                try await client.send(.init(session: .one, data: Data("fixture only".utf8), appendReturn: false))
                XCTFail("Redirect must not acknowledge input")
            } catch WatchTerminalClientError.submissionUnconfirmed {} catch { XCTFail("Unexpected error: \(error)") }
        }
    }

    func testNewSessionPOSTNeverReplaysAcrossRedirect() async {
        for route in routes {
            let config = WatchTerminalConfiguration(endpoint: route.https,
                token: String(repeating: "x", count: 32), certificateSHA256: pin)
            let client = WatchTerminalClient(configuration: config, preferredBaseURL: URL(string: route.https)!)
            defer { client.close() }
            do { _ = try await client.sendToNewSession("fixture only"); XCTFail("Redirect must fail") }
            catch WatchTerminalClientError.submissionUnconfirmed {} catch { XCTFail("Unexpected error: \(error)") }
        }
    }

    func testWrongCertificateStillCannotReceiveInput() async {
        let route = routes[0]
        let config = WatchTerminalConfiguration(endpoint: route.https,
            token: String(repeating: "x", count: 32), certificateSHA256: String(repeating: "0", count: 64))
        let client = WatchTerminalClient(configuration: config, preferredBaseURL: URL(string: route.https)!)
        defer { client.close() }
        do { try await client.send(.init(session: .one, data: Data("fixture only".utf8), appendReturn: false)); XCTFail("Pin must fail") }
        catch WatchTerminalClientError.certificateRejected {} catch { XCTFail("Unexpected error: \(error)") }
    }
}
