import Foundation
import XCTest
@testable import JARVISKit

final class JarvisClientTests: XCTestCase {
    private var session: URLSession!
    private var client: JarvisClient!
    private let endpoint = JarvisEndpoint(baseURL: URL(string: "http://jarvis.test:8790")!, token: "secret")

    override func setUp() {
        super.setUp()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        session = URLSession(configuration: configuration)
        client = JarvisClient(session: session)
        MockURLProtocol.handler = nil
    }

    override func tearDown() {
        MockURLProtocol.handler = nil
        session.invalidateAndCancel()
        session = nil
        client = nil
        super.tearDown()
    }

    func testHealthRequestUsesTokenAndDecodes() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/health")
            XCTAssertEqual(request.value(forHTTPHeaderField: "x-jarvis-token"), "secret")
            return MockURLProtocol.response(
                request,
                status: 200,
                body: #"{"ok":true,"version":"test","uptimeSeconds":3.5}"#
            )
        }
        let result = try await client.health(endpoint)
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.version, "test")
    }

    func testCodexQuotaRefreshUsesAuthenticatedReadOnlyStateQuery() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/v1/state")
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
            XCTAssertEqual(query.first(where: { $0.name == "refresh" })?.value, "codexQuota")
            XCTAssertEqual(request.value(forHTTPHeaderField: "x-jarvis-token"), "secret")
            return MockURLProtocol.response(request, status: 200, body: #"{"ok":true}"#)
        }

        let result = try await client.stateRefreshingCodexQuota(endpoint)

        XCTAssertTrue(result.ok)
    }

    func testHTTPErrorPreservesStatusAndBoundedBody() async throws {
        MockURLProtocol.handler = { request in
            MockURLProtocol.response(request, status: 400, body: #"{"ok":false,"error":"not allowlisted"}"#)
        }
        do {
            _ = try await client.command(endpoint, action: "cast-status")
            XCTFail("expected HTTP error")
        } catch let JarvisError.http(status, body) {
            XCTAssertEqual(status, 400)
            XCTAssertTrue(body.contains("not allowlisted"))
        }
    }

    func testEventsClampLimitAndEncodeSince() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/events")
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
            XCTAssertEqual(query.first(where: { $0.name == "limit" })?.value, "500")
            XCTAssertEqual(query.first(where: { $0.name == "since" })?.value, "41")
            return MockURLProtocol.response(request, status: 200, body: #"{"ok":true,"count":0,"events":[]}"#)
        }
        let result = try await client.events(endpoint, since: 41, limit: 900)
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.count, 0)
    }

    func testScheduledJobsUsesDedicatedEndpointAndDecodesPublicFields() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/scheduled-jobs")
            return MockURLProtocol.response(
                request,
                status: 200,
                body: #"{"ok":true,"generatedAt":"2026-08-21T00:00:00Z","summary":{"total":1,"enabled":1,"running":0,"errors":0},"jobs":[{"id":"job_demo","name":"demo","kind":"interval","schedule":"5m","enabled":true,"nextRunAt":null,"lastRunAt":null,"lastStatus":"success","runCount":4,"description":null}]}"#
            )
        }

        let result = try await client.scheduledJobs(endpoint)

        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.summary.enabled, 1)
        XCTAssertEqual(result.jobs.first?.id, "job_demo")
        XCTAssertEqual(result.jobs.first?.runCount, 4)
    }

    func testServiceNameIsPathEncoded() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertTrue(request.url?.absoluteString.hasSuffix("/api/v1/services/room%20audio") == true)
            return MockURLProtocol.response(request, status: 200, body: #"{"ok":true,"service":"room audio","action":"status"}"#)
        }
        let result = try await client.serviceAction(endpoint, name: "room audio", action: "status")
        XCTAssertTrue(result.ok)
    }

    func testSigningRenewalUsesDedicatedBodylessAuthenticatedEndpoints() async throws {
        var requests: [URLRequest] = []
        MockURLProtocol.handler = { request in
            requests.append(request)
            return MockURLProtocol.response(
                request,
                status: request.httpMethod == "POST" ? 202 : 200,
                body: #"{"ok":true,"available":true,"phase":"queued","running":true,"message":"Started."}"#
            )
        }

        _ = try await client.signingRenewalStatus(endpoint)
        let started = try await client.startSigningRenewal(endpoint)

        XCTAssertEqual(requests.map { $0.url?.path }, ["/api/v1/signing/status", "/api/v1/signing/renew"])
        XCTAssertEqual(requests.map(\.httpMethod), ["GET", "POST"])
        XCTAssertNil(requests[1].httpBody)
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "x-jarvis-token"), "secret")
        XCTAssertTrue(started.running)
    }

    func testDiscoveryUsesEarlyLowerPrioritySuccessAfterHigherPriorityFails() async {
        let higher = URL(string: "http://higher.test:8790")!
        let lower = URL(string: "http://lower.test:8790")!
        let client = JarvisClient(session: session) { candidate, _ in
            if candidate == higher {
                try? await Task.sleep(for: .milliseconds(100))
                return false
            }
            try? await Task.sleep(for: .milliseconds(10))
            return true
        }

        let result = await client.discover([higher, lower], timeout: 1)

        XCTAssertEqual(result, lower)
    }

    func testDiscoveryPreservesPriorityWhenBothCandidatesSucceed() async {
        let higher = URL(string: "http://higher.test:8790")!
        let lower = URL(string: "http://lower.test:8790")!
        let client = JarvisClient(session: session) { candidate, _ in
            try? await Task.sleep(for: candidate == higher ? .milliseconds(80) : .milliseconds(5))
            return true
        }

        let result = await client.discover([higher, lower], timeout: 1)

        XCTAssertEqual(result, higher)
    }

    func testDiscoveryDoesNotWaitForLowerCandidatesAfterWinnerIsKnown() async {
        let higher = URL(string: "http://higher.test:8790")!
        let winner = URL(string: "http://winner.test:8790")!
        let slowLower = URL(string: "http://slow.test:8790")!
        let client = JarvisClient(session: session) { candidate, _ in
            if candidate == higher {
                try? await Task.sleep(for: .milliseconds(50))
                return false
            }
            if candidate == winner {
                try? await Task.sleep(for: .milliseconds(5))
                return true
            }
            try? await Task.sleep(for: .seconds(5))
            return !Task.isCancelled
        }
        let started = Date()

        let result = await client.discover([higher, winner, slowLower], timeout: 10)

        XCTAssertEqual(result, winner)
        XCTAssertLessThan(Date().timeIntervalSince(started), 1)
    }

    func testDiscoveryDeduplicatesAndHandlesCancellation() async throws {
        let candidate = URL(string: "http://duplicate.test:8790")!
        let counter = ProbeCounter()
        let client = JarvisClient(session: session) { _, _ in
            await counter.increment()
            try? await Task.sleep(for: .seconds(5))
            return !Task.isCancelled
        }

        let emptyResult = await client.discover([], timeout: 1)
        XCTAssertNil(emptyResult)
        let task = Task { await client.discover([candidate, candidate], timeout: 10) }
        for _ in 0..<20 {
            if await counter.value > 0 { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        task.cancel()

        let cancelledResult = await task.value
        let probeCount = await counter.value
        XCTAssertNil(cancelledResult)
        XCTAssertEqual(probeCount, 1)
    }
}

private actor ProbeCounter {
    private(set) var value = 0
    func increment() { value += 1 }
}

private final class MockURLProtocol: URLProtocol {
    static var handler: ((URLRequest) -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler, let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        let (response, data) = handler(request)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
        _ = url
    }

    override func stopLoading() {}

    static func response(_ request: URLRequest, status: Int, body: String) -> (HTTPURLResponse, Data) {
        (
            HTTPURLResponse(
                url: request.url!,
                statusCode: status,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!,
            Data(body.utf8)
        )
    }
}
