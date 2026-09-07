import Foundation
import XCTest
@testable import JARVISKit

final class ScheduledJobsTests: XCTestCase {
    func testNavigationRequestRequiresPositiveSequenceAndKeepsActionIdentity() throws {
        XCTAssertNil(ScheduledJobNavigationRequest(resultSequence: 0))
        XCTAssertNil(ScheduledJobNavigationRequest(resultSequence: -1))

        let id = UUID()
        let request = try XCTUnwrap(ScheduledJobNavigationRequest(id: id, resultSequence: 41))
        XCTAssertEqual(request.id, id)
        XCTAssertEqual(request.resultSequence, 41)
    }

    func testResultCacheDeduplicatesNewestFirstAndBoundsOneHundred() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("jarvis-kit-jobs-\(UUID().uuidString)", isDirectory: true)
        let url = root.appendingPathComponent("scheduled-job-results-v1.json")
        defer { try? FileManager.default.removeItem(at: root) }
        let cache = ScheduledJobResultCache(fileURL: url)
        var values = try (1...105).map { try result(sequence: $0, jobID: "job_alpha") }
        values.append(try result(sequence: 105, jobID: "job_duplicate"))

        cache.save(values)
        let loaded = cache.load()

        XCTAssertEqual(loaded.count, ScheduledJobResultCache.limit)
        XCTAssertEqual(loaded.first?.sequence, 105)
        XCTAssertEqual(loaded.last?.sequence, 6)
        XCTAssertEqual(loaded.filter { $0.sequence == 105 }.count, 1)
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let permissions = try XCTUnwrap(attributes[.posixPermissions] as? NSNumber).intValue
        XCTAssertEqual(permissions & 0o777, 0o600)
        let directoryAttributes = try FileManager.default.attributesOfItem(atPath: root.path)
        let directoryPermissions = try XCTUnwrap(directoryAttributes[.posixPermissions] as? NSNumber).intValue
        XCTAssertEqual(directoryPermissions & 0o777, 0o700)
    }

    func testFocusedMergeRetainsAnExactOlderResultWithoutBreakingTheCacheBound() throws {
        let cached = try (101...200).map { try result(sequence: $0, jobID: "job_alpha") }
        let focused = try result(sequence: 50, jobID: "job_archived")

        let ordinary = ScheduledJobResultCache.merging(cached: cached, incoming: [focused])
        XCTAssertFalse(ordinary.contains { $0.sequence == 50 })

        let preserved = ScheduledJobResultCache.merging(
            cached: cached,
            incoming: [focused],
            preserving: 50
        )
        XCTAssertEqual(preserved.count, ScheduledJobResultCache.limit)
        XCTAssertEqual(preserved.first?.sequence, 200)
        XCTAssertEqual(preserved.last?.sequence, 50)
        XCTAssertTrue(preserved.contains { $0.sequence == 50 })
        XCTAssertEqual(preserved, preserved.sorted { $0.sequence > $1.sequence })
    }

    func testReadStateUsesGlobalMigrationBaselineThenIndependentJobWatermarks() throws {
        var state = ScheduledJobReadState.empty
        state.jobReadSequences["job_alpha"] = 70
        state.establishBaseline(80)
        XCTAssertEqual(state.readSequence(for: "job_alpha"), 80, "a pre-baseline focused lookup must not lower the migration floor")
        XCTAssertEqual(state.readSequence(for: "job_beta"), 80)

        state.markRead(jobID: "job_alpha", through: 83)
        XCTAssertEqual(state.readSequence(for: "job_alpha"), 83)
        XCTAssertEqual(state.readSequence(for: "job_beta"), 80)
        state.establishBaseline(100)
        XCTAssertEqual(state.baselineSequence, 80, "migration baseline is first-success only")

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("jarvis-kit-read-\(UUID().uuidString)", isDirectory: true)
        let url = root.appendingPathComponent("scheduled-job-read-state-v2.json")
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ScheduledJobReadStateStore(fileURL: url)
        store.save(state)
        XCTAssertEqual(store.load(), state)
    }

    func testVisibleThreadsExcludeDisabledAndArchivedWithoutDeletingHistory() throws {
        let jobs = [try job(id: "enabled", enabled: true), try job(id: "disabled", enabled: false)]
        let results = [try result(sequence: 1, jobID: "enabled"),
                       try result(sequence: 2, jobID: "disabled"),
                       try result(sequence: 3, jobID: "removed")]
        let visible = JobsPresentation.visibleThreads(jobs: jobs, results: results)
        XCTAssertEqual(visible.scheduled.map(\.id), ["enabled"])
        XCTAssertTrue(visible.archived.isEmpty)
        XCTAssertEqual(results.count, 3)
        XCTAssertTrue(JobsPresentation.visibleThreads(jobs: [], results: results).scheduled.isEmpty)
    }

    func testSharedPresentationKeepsRowsPreviewFreeAndArchivesRemovedJobs() throws {
        let scheduled = try job(id: "job_alpha", enabled: true)
        let results = [
            try result(sequence: 3, jobID: "job_alpha"),
            try result(sequence: 2, jobID: "job_archived"),
        ]

        let sections = JobsPresentation.threads(jobs: [scheduled], results: results)

        XCTAssertEqual(sections.scheduled.map(\.id), ["job_alpha"])
        XCTAssertEqual(sections.scheduled.first?.messages.map(\.sequence), [3])
        XCTAssertEqual(sections.archived.map(\.id), ["job_archived"])
        XCTAssertEqual(JobsPresentation.cadence(kind: "interval", schedule: "5m"), "Every 5 minutes")
    }

    func testRichTextPermitsOnlyBoundedCredentialFreeHTTPLinks() {
        let attributed = JobResultRichText.attributedString(
            "[good](https://example.com/a) [bad](ftp://example.com/a) "
                + "[credentials](https://owner:secret@example.com/private)"
        )

        XCTAssertEqual(JobResultRichText.links(in: attributed).map(\.absoluteString), ["https://example.com/a"])
        XCTAssertEqual(String(attributed.characters), "good bad credentials")
    }

    private func job(id: String, enabled: Bool) throws -> ScheduledJob {
        try decode([
            "id": id,
            "name": id,
            "kind": "interval",
            "schedule": "5m",
            "enabled": enabled,
            "nextRunAt": NSNull(),
            "lastRunAt": NSNull(),
            "lastStatus": "success",
            "runCount": 1,
            "description": NSNull(),
            "lastSilentSuccessAt": NSNull(),
            "lastOutputAt": NSNull(),
            "lastErrorAt": NSNull(),
            "consecutiveErrors": 0,
        ])
    }

    private func result(sequence: Int, jobID: String) throws -> ScheduledJobResult {
        try decode([
            "sequence": sequence,
            "id": "run_\(sequence)",
            "jobId": jobID,
            "jobName": jobID,
            "status": "success",
            "outputKind": "scheduler",
            "startedAt": "2026-09-02T00:00:00Z",
            "finishedAt": "2026-09-02T00:00:01Z",
            "durationSeconds": 1.0,
            "exitCode": 0,
            "title": "Fixture",
            "summary": "Fixture",
            "output": "Private full output",
            "error": NSNull(),
            "truncated": false,
        ])
    }

    private func decode<Value: Decodable>(_ object: Any) throws -> Value {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return try JSONDecoder().decode(Value.self, from: data)
    }
}
