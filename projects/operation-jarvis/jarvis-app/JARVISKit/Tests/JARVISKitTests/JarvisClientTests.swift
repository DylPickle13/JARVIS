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

    func testUnsupportedEndpointFailsBeforeTokenBearingTransport() async throws {
        MockURLProtocol.handler = { request in
            XCTFail("unsupported endpoint reached transport: \(request)")
            return MockURLProtocol.response(request, status: 500, body: #"{"ok":false}"#)
        }
        let unsupported = JarvisEndpoint(
            baseURL: URL(string: "ftp://untrusted.test:8790")!,
            token: "must-not-be-sent"
        )

        do {
            _ = try await client.health(unsupported)
            XCTFail("expected bad URL")
        } catch let JarvisError.badURL(value) {
            XCTAssertEqual(value, "ftp://untrusted.test:8790")
        }
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

    func testNotificationStatusUsesSanitizedReadOnlyEndpoint() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/v1/notification-status")
            XCTAssertEqual(request.value(forHTTPHeaderField: "x-jarvis-token"), "secret")
            return MockURLProtocol.response(
                request,
                status: 200,
                body: #"{"ok":true,"providerConfigured":false,"dispatchEnabled":false,"environment":null,"devices":{"iphone":{"registered":true,"registeredAt":"2026-09-01T00:00:00Z","lastAcceptedAt":null},"watch":{"registered":false,"registeredAt":null,"lastAcceptedAt":null}},"pendingCount":0,"failedCount":0,"ambiguousCount":0,"lastOutcome":null,"lastAttemptAt":null,"lastAcceptedAt":null,"error":null}"#
            )
        }

        let result = try await client.notificationStatus(endpoint)

        XCTAssertTrue(result.ok)
        XCTAssertTrue(result.devices.iphone.registered)
        XCTAssertFalse(result.devices.watch.registered)
        XCTAssertFalse(result.dispatchEnabled)
    }

    func testScheduledJobResultsEncodeBoundedCursorAndDecodeResult() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/scheduled-job-results")
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
            XCTAssertEqual(query.first(where: { $0.name == "after" })?.value, "8")
            XCTAssertEqual(query.first(where: { $0.name == "limit" })?.value, "100")
            XCTAssertEqual(query.first(where: { $0.name == "jobId" })?.value, "job demo")
            return MockURLProtocol.response(
                request,
                status: 200,
                body: #"{"ok":true,"generatedAt":"2026-08-30T00:00:00Z","results":[{"sequence":9,"id":"run_9","jobId":"job_demo","jobName":"demo","status":"success","outputKind":"direct","startedAt":"2026-08-30T00:00:00Z","finishedAt":"2026-08-30T00:00:01Z","durationSeconds":1.0,"exitCode":0,"title":"demo completed","summary":"Ready","output":"Ready","error":null,"truncated":false}],"hasMore":false,"nextAfter":9}"#
            )
        }

        let response = try await client.scheduledJobResults(endpoint, after: 8, limit: 500, jobId: "job demo")

        XCTAssertTrue(response.ok)
        XCTAssertEqual(response.nextAfter, 9)
        XCTAssertEqual(response.results.first?.sequence, 9)
        XCTAssertEqual(response.results.first?.output, "Ready")
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

    func testResolveStateUsesPreferredEndpointWithoutDiscovery() async throws {
        let preferred = URL(string: "http://preferred.test:8790")!
        let probes = ProbeCounter()
        let client = JarvisClient(session: session) { _, _ in
            await probes.increment()
            return true
        }
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.host, preferred.host)
            XCTAssertEqual(request.url?.path, "/api/v1/state")
            XCTAssertEqual(request.timeoutInterval, 1, accuracy: 0.01)
            XCTAssertEqual(request.value(forHTTPHeaderField: "x-jarvis-token"), "secret")
            return MockURLProtocol.response(request, status: 200, body: #"{"ok":true}"#)
        }

        let result = try await client.resolveState(
            preferredEndpoint: preferred,
            candidates: [preferred, URL(string: "http://fallback.test:8790")!],
            token: "secret",
            discoveryTimeout: 1
        )
        let probeCount = await probes.value

        XCTAssertEqual(result.endpointURL, preferred)
        XCTAssertFalse(result.usedDiscovery)
        XCTAssertTrue(result.state.ok)
        XCTAssertEqual(probeCount, 0)
    }

    func testResolveStateDiscoversOnlyAfterPreferredEndpointFails() async throws {
        let preferred = URL(string: "http://preferred.test:8790")!
        let fallback = URL(string: "http://fallback.test:8790")!
        let requests = RequestRecorder()
        let probes = ProbeRecorder()
        let client = JarvisClient(session: session) { candidate, _ in
            await probes.record(candidate)
            return candidate == fallback
        }
        MockURLProtocol.handler = { request in
            requests.record(request)
            XCTAssertEqual(request.url?.path, "/api/v1/state")
            if request.url?.host == preferred.host {
                return MockURLProtocol.response(request, status: 503, body: #"{"ok":false}"#)
            }
            return MockURLProtocol.response(request, status: 200, body: #"{"ok":true}"#)
        }

        let result = try await client.resolveState(
            preferredEndpoint: preferred,
            candidates: [preferred, fallback],
            token: "secret",
            discoveryTimeout: 1
        )
        let probedURLs = await probes.values

        XCTAssertEqual(result.endpointURL, fallback)
        XCTAssertTrue(result.usedDiscovery)
        XCTAssertEqual(requests.hosts, [preferred.host!, fallback.host!])
        XCTAssertEqual(probedURLs, [fallback])
    }

    func testResolveStatePreservesPreferredFailureWhenNoAlternateResponds() async throws {
        let preferred = URL(string: "http://preferred.test:8790")!
        let probes = ProbeCounter()
        let client = JarvisClient(session: session) { _, _ in
            await probes.increment()
            return false
        }
        MockURLProtocol.handler = { request in
            MockURLProtocol.response(request, status: 503, body: #"{"ok":false}"#)
        }

        do {
            _ = try await client.resolveState(
                preferredEndpoint: preferred,
                candidates: [preferred],
                token: "secret",
                discoveryTimeout: 1
            )
            XCTFail("expected preferred endpoint failure")
        } catch let JarvisError.http(status, _) {
            XCTAssertEqual(status, 503)
        }
        let probeCount = await probes.value
        XCTAssertEqual(probeCount, 0)
    }

    func testDiscoveryNeverProbesUnsupportedEndpoints() async {
        let unsupported = URL(string: "ftp://untrusted.test:8790")!
        let approved = URL(string: "http://approved.test:8790")!
        let probes = ProbeRecorder()
        let client = JarvisClient(session: session) { candidate, _ in
            await probes.record(candidate)
            return true
        }

        let result = await client.discover([unsupported, approved], timeout: 1)
        let probedURLs = await probes.values

        XCTAssertEqual(result, approved)
        XCTAssertEqual(probedURLs, [approved])
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

private actor ProbeRecorder {
    private(set) var values: [URL] = []
    func record(_ value: URL) { values.append(value) }
}

private final class RequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var requests: [URLRequest] = []

    var hosts: [String] {
        lock.withLock { requests.compactMap { $0.url?.host } }
    }

    func record(_ request: URLRequest) {
        lock.withLock { requests.append(request) }
    }
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
