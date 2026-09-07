import Foundation
import XCTest
@testable import JARVIS
import JARVISKit

@MainActor
final class WatchJobsModelTests: XCTestCase {
    func testFirstFullSyncBaselinesHistoryThenTracksPerJobUnreadState() async throws {
        let harness = try Harness()
        defer { harness.removeFiles() }
        let api = WatchJobsAPI(
            results: try (1...80).map {
                try Self.result(sequence: $0, jobID: $0.isMultiple(of: 2) ? "job_alpha" : "job_beta")
            }
        )
        let model = harness.model(api: api)

        await model.refresh()

        XCTAssertEqual(model.results.count, 80)
        XCTAssertEqual(model.unreadJobCount, 0, "retained Build 145 history must baseline as read")
        XCTAssertNil(model.selectedThread, "opening the Jobs root must not select or read a thread")

        api.results.append(try Self.result(sequence: 81, jobID: "job_alpha"))
        api.results.append(try Self.result(sequence: 82, jobID: "job_beta"))
        await model.refresh()

        XCTAssertEqual(model.unreadJobCount, 2)
        XCTAssertEqual(model.unreadResultCount(for: "job_alpha"), 1)
        XCTAssertEqual(model.unreadResultCount(for: "job_beta"), 1)

        model.openThread(jobID: "job_alpha")

        XCTAssertEqual(model.selectedThread?.id, "job_alpha")
        XCTAssertEqual(model.unreadResultCount(for: "job_alpha"), 0)
        XCTAssertEqual(model.unreadResultCount(for: "job_beta"), 1)
        XCTAssertEqual(model.unreadJobCount, 1)

        let restored = harness.model(api: WatchJobsAPI(results: []))
        XCTAssertEqual(Array(restored.results.map(\.sequence).prefix(2)), [82, 81])
        XCTAssertEqual(restored.unreadResultCount(for: "job_alpha"), 0)
        XCTAssertEqual(restored.unreadResultCount(for: "job_beta"), 1)

        let cacheAttributes = try FileManager.default.attributesOfItem(atPath: harness.cacheURL.path)
        let cacheMode = try XCTUnwrap(cacheAttributes[.posixPermissions] as? NSNumber).intValue
        XCTAssertEqual(cacheMode & 0o777, 0o600)
        let readAttributes = try FileManager.default.attributesOfItem(atPath: harness.readStateURL.path)
        let readMode = try XCTUnwrap(readAttributes[.posixPermissions] as? NSNumber).intValue
        XCTAssertEqual(readMode & 0o777, 0o600)
    }

    func testFocusedLookupDoesNotEstablishAnIncompleteMigrationBaseline() async throws {
        let harness = try Harness()
        defer { harness.removeFiles() }
        let api = WatchJobsAPI(
            results: try (70...80).map { try Self.result(sequence: $0, jobID: "job_alpha") }
        )
        let model = harness.model(api: api)
        let route = try XCTUnwrap(ScheduledJobNavigationRequest(resultSequence: 70))

        let resolved = await model.resolve(route)
        XCTAssertTrue(resolved)
        XCTAssertEqual(model.selectedThread?.id, "job_alpha")
        XCTAssertEqual(model.focusedResultSequence, 70)
        XCTAssertNil(model.pendingRoute)
        XCTAssertEqual(api.resultRequests.first, .init(after: 69, limit: 1, jobID: nil))

        // Even if the focused destination is closed or its read-state write is
        // unavailable across a process restart, the focused-only cache cannot
        // masquerade as a completed migration baseline.
        model.closeThread()
        try FileManager.default.removeItem(at: harness.readStateURL)
        let restored = harness.model(api: api)
        XCTAssertEqual(restored.unreadJobCount, 1)

        await restored.refresh()

        XCTAssertEqual(api.resultRequests.last, .init(after: nil, limit: 100, jobID: nil))
        XCTAssertEqual(restored.results.map(\.sequence), Array((70...80).reversed()))
        XCTAssertEqual(restored.unreadJobCount, 0, "the complete first sync, not an older focused lookup, owns the baseline")
    }

    func testMissingExactRouteStaysPendingForRetryAndNeverOpensAnotherResult() async throws {
        let harness = try Harness()
        defer { harness.removeFiles() }
        let api = WatchJobsAPI(results: [
            try Self.result(sequence: 91, jobID: "job_other"),
        ])
        let model = harness.model(api: api)
        let route = try XCTUnwrap(ScheduledJobNavigationRequest(resultSequence: 90))

        let firstAttempt = await model.resolve(route)
        XCTAssertFalse(firstAttempt)
        XCTAssertEqual(model.pendingRoute, route)
        XCTAssertNil(model.selectedThread)
        XCTAssertNil(model.focusedResultSequence)
        XCTAssertFalse(model.containsResult(sequence: 91), "a mismatched exact response must not mutate history")
        XCTAssertEqual(model.routeErrorMessage, "Result #90 is no longer retained.")

        api.results.append(try Self.result(sequence: 90, jobID: "job_target"))
        let retrySucceeded = await model.resolve(route)
        XCTAssertTrue(retrySucceeded)

        XCTAssertNil(model.pendingRoute)
        XCTAssertEqual(model.selectedThread?.id, "job_target")
        XCTAssertEqual(model.focusedResultSequence, 90)
        XCTAssertTrue(model.containsResult(sequence: 90))
    }

    func testExactOlderRouteRemainsAvailableInsideTheBoundedCache() async throws {
        let harness = try Harness()
        defer { harness.removeFiles() }
        let api = WatchJobsAPI(
            results: try (1...200).map { try Self.result(sequence: $0, jobID: "job_alpha") }
        )
        let model = harness.model(api: api)
        await model.refresh()

        XCTAssertEqual(model.results.count, 100)
        XCTAssertFalse(model.containsResult(sequence: 50))

        let route = try XCTUnwrap(ScheduledJobNavigationRequest(resultSequence: 50))
        let resolved = await model.resolve(route)
        XCTAssertTrue(resolved)
        XCTAssertEqual(model.results.count, 100)
        XCTAssertTrue(model.containsResult(sequence: 50))
        XCTAssertEqual(model.focusedResultSequence, 50)
        XCTAssertEqual(model.selectedThread?.id, "job_alpha")
    }

    func testFocusedLookupDoesNotAdvanceThePersistedGeneralHistoryCursor() async throws {
        let harness = try Harness()
        defer { harness.removeFiles() }
        let api = WatchJobsAPI(
            results: try (1...100).map { try Self.result(sequence: $0, jobID: "job_alpha") }
        )
        let model = harness.model(api: api)
        await model.refresh()

        api.results.append(contentsOf: try (101...250).map {
            try Self.result(sequence: $0, jobID: "job_alpha")
        })
        let route = try XCTUnwrap(ScheduledJobNavigationRequest(resultSequence: 250))
        let resolved = await model.resolve(route)
        XCTAssertTrue(resolved)
        XCTAssertEqual(api.resultRequests.last, .init(after: 249, limit: 1, jobID: nil))

        let restored = harness.model(api: api)
        await restored.refresh()
        XCTAssertEqual(Array(api.resultRequests.suffix(2)), [
            .init(after: 100, limit: 100, jobID: nil),
            .init(after: 200, limit: 100, jobID: nil),
        ])
        XCTAssertEqual(restored.results.first?.sequence, 250)
        XCTAssertEqual(restored.results.last?.sequence, 151)

        await restored.refresh()
        XCTAssertEqual(api.resultRequests.last, .init(after: 250, limit: 100, jobID: nil))
    }

    func testPollingRunsOnlyForVisibleInteractiveJobsAndStopsForAlwaysOn() async throws {
        let harness = try Harness()
        defer { harness.removeFiles() }
        let api = WatchJobsAPI(results: [try Self.result(sequence: 1, jobID: "job_alpha")])
        let model = harness.model(api: api, activeRefreshInterval: .milliseconds(30))

        model.sceneDidBecomeInteractive()
        try await Task.sleep(for: .milliseconds(90))
        XCTAssertEqual(api.jobsCalls, 0)
        XCTAssertEqual(api.resultRequests.count, 0)

        model.setPageVisible(true)
        for _ in 0..<20 where api.jobsCalls < 2 {
            try await Task.sleep(for: .milliseconds(15))
        }
        XCTAssertGreaterThanOrEqual(api.jobsCalls, 2)
        XCTAssertEqual(api.jobsCalls, api.resultRequests.count)

        model.sceneDidEnterAlwaysOn()
        try await Task.sleep(for: .milliseconds(20))
        let stoppedCounts = (api.jobsCalls, api.resultRequests.count)
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(api.jobsCalls, stoppedCounts.0)
        XCTAssertEqual(api.resultRequests.count, stoppedCounts.1)

        await model.refresh() // explicit pull/route refresh remains permitted
        XCTAssertEqual(api.jobsCalls, stoppedCounts.0 + 1)
        XCTAssertEqual(api.resultRequests.count, stoppedCounts.1 + 1)
    }

    private struct Harness {
        let suiteName: String
        let defaults: UserDefaults
        let store: EndpointStore
        let root: URL
        let cacheURL: URL
        let readStateURL: URL

        init() throws {
            suiteName = "jarvis.watch-jobs.\(UUID().uuidString)"
            defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
            store = EndpointStore(defaults: defaults)
            store.endpointURLString = "http://fixture.invalid:8790"
            root = FileManager.default.temporaryDirectory
                .appendingPathComponent("jarvis-watch-jobs-\(UUID().uuidString)", isDirectory: true)
            cacheURL = root.appendingPathComponent("scheduled-job-results-v1.json")
            readStateURL = root.appendingPathComponent("scheduled-job-read-state-v2.json")
        }

        @MainActor
        func model(
            api: WatchJobsAPI,
            activeRefreshInterval: Duration = .seconds(60)
        ) -> WatchJobsModel {
            WatchJobsModel(
                store: store,
                client: api,
                activeRefreshInterval: activeRefreshInterval,
                preferences: defaults,
                resultCacheURL: cacheURL,
                resultReadStateURL: readStateURL
            )
        }

        func removeFiles() {
            UserDefaults.standard.removePersistentDomain(forName: suiteName)
            defaults.removePersistentDomain(forName: suiteName)
            try? FileManager.default.removeItem(at: root)
        }
    }

    private static func result(sequence: Int, jobID: String) throws -> ScheduledJobResult {
        let object: [String: Any] = [
            "sequence": sequence,
            "id": "run_\(sequence)",
            "jobId": jobID,
            "jobName": jobID,
            "status": sequence.isMultiple(of: 11) ? "error" : "success",
            "outputKind": "scheduler",
            "startedAt": "2026-09-02T00:00:00Z",
            "finishedAt": "2026-09-02T00:00:01Z",
            "durationSeconds": 1.25,
            "exitCode": sequence.isMultiple(of: 11) ? 1 : 0,
            "title": "Fixture result",
            "summary": "Fixture summary",
            "output": "Full retained output for result \(sequence)",
            "error": sequence.isMultiple(of: 11) ? "Fixture failure" as Any : NSNull(),
            "truncated": false,
        ]
        return try decode(object)
    }

    private static func decode<Value: Decodable>(_ object: Any) throws -> Value {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return try JSONDecoder().decode(Value.self, from: data)
    }
}

private final class WatchJobsAPI: JarvisAPI, @unchecked Sendable {
    struct ResultRequest: Equatable {
        let after: Int?
        let limit: Int
        let jobID: String?
    }

    var results: [ScheduledJobResult]
    var jobsCalls = 0
    var resultRequests: [ResultRequest] = []

    init(results: [ScheduledJobResult]) {
        self.results = results
    }

    func scheduledJobs(_ endpoint: JarvisEndpoint) async throws -> ScheduledJobsResponse {
        jobsCalls += 1
        return try Self.decode([
            "ok": true,
            "summary": ["total": 4, "enabled": 3, "running": 0, "errors": 1],
            "jobs": [
                Self.job(id: "job_alpha", enabled: true),
                Self.job(id: "job_beta", enabled: true),
                Self.job(id: "job_target", enabled: true),
                Self.job(id: "job_other", enabled: false),
            ],
        ])
    }

    func scheduledJobResults(
        _ endpoint: JarvisEndpoint,
        after: Int?,
        limit: Int,
        jobId: String?
    ) async throws -> ScheduledJobResultsResponse {
        resultRequests.append(ResultRequest(after: after, limit: limit, jobID: jobId))
        var eligible = results.filter { jobId == nil || $0.jobId == jobId }
        if let after {
            eligible = eligible.filter { $0.sequence > after }.sorted { $0.sequence < $1.sequence }
        } else {
            eligible.sort { $0.sequence > $1.sequence }
        }
        let selected = Array(eligible.prefix(limit))
        let encodedResults = try JSONSerialization.jsonObject(with: JSONEncoder().encode(selected))
        return try Self.decode([
            "ok": true,
            "results": encodedResults,
            "hasMore": eligible.count > selected.count,
            "nextAfter": selected.map(\.sequence).max() ?? after ?? 0,
        ])
    }

    func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse { throw unused() }
    func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot { throw unused() }
    func command(_ endpoint: JarvisEndpoint, action: String, params: [String: JSONValue]?) async throws -> CommandResult { throw unused() }
    func events(_ endpoint: JarvisEndpoint, since: Int?, limit: Int) async throws -> EventsResponse { throw unused() }
    func services(_ endpoint: JarvisEndpoint) async throws -> ServicesListResponse { throw unused() }
    func serviceAction(_ endpoint: JarvisEndpoint, name: String, action: String) async throws -> ServiceActionResult { throw unused() }
    func signingRenewalStatus(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus { throw unused() }
    func startSigningRenewal(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus { throw unused() }
    func discover(_ candidates: [URL], timeout: TimeInterval) async -> URL? { candidates.first }

    private func unused() -> JarvisError {
        .transport("unused Watch Jobs test endpoint")
    }

    private static func job(id: String, enabled: Bool) -> [String: Any] {
        [
            "id": id,
            "name": id,
            "kind": "interval",
            "schedule": "5m",
            "enabled": enabled,
            "nextRunAt": NSNull(),
            "lastRunAt": NSNull(),
            "lastStatus": enabled ? "success" : "error",
            "runCount": 3,
            "description": "Fixture job",
            "lastSilentSuccessAt": NSNull(),
            "lastOutputAt": NSNull(),
            "lastErrorAt": NSNull(),
            "consecutiveErrors": enabled ? 0 : 1,
        ]
    }

    private static func decode<Value: Decodable>(_ object: Any) throws -> Value {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return try JSONDecoder().decode(Value.self, from: data)
    }
}
