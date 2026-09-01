import Foundation
import XCTest
@testable import JARVIS
import JARVISKit

final class JobsPresentationTests: XCTestCase {
    func testThreadsGroupMessagesUnderScheduledJobsAndRetainArchivedHistory() throws {
        let alpha = try job(id: "job_alpha", name: "alpha", schedule: "30m", kind: "interval")
        let beta = try job(id: "job_beta", name: "beta", schedule: "0 9 * * *", kind: "cron")
        let values = [
            try result(sequence: 2, jobID: "job_archived", jobName: "old-job"),
            try result(sequence: 1, jobID: "job_alpha", jobName: "alpha"),
            try result(sequence: 3, jobID: "job_alpha", jobName: "alpha"),
        ]

        let sections = JobsPresentation.threads(jobs: [alpha, beta], results: values)

        XCTAssertEqual(sections.scheduled.map(\.id), ["job_alpha", "job_beta"])
        XCTAssertEqual(sections.scheduled[0].messages.map(\.sequence), [3, 1])
        XCTAssertTrue(sections.scheduled[1].messages.isEmpty)
        XCTAssertEqual(sections.archived.map(\.id), ["job_archived"])
        XCTAssertEqual(sections.archived[0].name, "old-job")
        XCTAssertEqual(sections.archived[0].messages.map(\.sequence), [2])

        let retainedSequences = (sections.scheduled + sections.archived)
            .flatMap(\.messages)
            .map(\.sequence)
            .sorted()
        XCTAssertEqual(retainedSequences, [1, 2, 3])
    }

    func testRecoveredSilentJobDoesNotInheritIssueFromRetainedFailure() throws {
        let recovered = try job(
            id: "job_recovered",
            name: "recovered",
            schedule: "1m",
            kind: "interval",
            lastStatus: "success",
            consecutiveErrors: 0
        )
        let retainedFailure = try result(
            sequence: 9,
            jobID: recovered.id,
            jobName: recovered.name,
            status: "error"
        )
        let thread = try XCTUnwrap(
            JobsPresentation.threads(jobs: [recovered], results: [retainedFailure]).scheduled.first
        )

        XCTAssertEqual(thread.latestMessage?.status, "error")
        XCTAssertFalse(JobsPresentation.hasCurrentIssue(thread.job))

        let failing = try job(
            id: "job_failing",
            name: "failing",
            schedule: "1d",
            kind: "interval",
            lastStatus: "error",
            consecutiveErrors: 1
        )
        XCTAssertTrue(JobsPresentation.hasCurrentIssue(failing))
    }

    func testCadenceUsesFriendlyIntervalAndDailyDescriptions() {
        XCTAssertEqual(JobsPresentation.cadence(kind: "interval", schedule: "1m"), "Every minute")
        XCTAssertEqual(JobsPresentation.cadence(kind: "interval", schedule: "30m"), "Every 30 minutes")
        XCTAssertEqual(JobsPresentation.cadence(kind: "once", schedule: "2026-09-01T12:00:00Z"), "Runs once")
        XCTAssertTrue(JobsPresentation.cadence(kind: "cron", schedule: "0 9 * * *").hasPrefix("Daily at "))
        XCTAssertEqual(JobsPresentation.cadence(kind: "cron", schedule: "*/5 * * * *"), "Custom schedule")
    }

    func testRichTextEmbedsMarkdownLabelsAndBareURLsInPlace() {
        let attributed = JobResultRichText.attributedString(
            "Open [this listing](https://example.com/listing) or https://example.org/details."
        )

        XCTAssertEqual(
            String(attributed.characters),
            "Open this listing or https://example.org/details."
        )
        XCTAssertEqual(
            JobResultRichText.plainText("Open [this listing](https://example.com/listing)"),
            "Open this listing"
        )
        XCTAssertEqual(
            JobResultRichText.links(in: attributed).map(\.absoluteString),
            ["https://example.com/listing", "https://example.org/details"]
        )
    }

    func testRichTextLeavesUnsafeLinksAsPlainText() {
        let attributed = JobResultRichText.attributedString(
            "Bad [FTP](ftp://example.com/file) and https://user:password@example.com/private"
        )

        XCTAssertEqual(String(attributed.characters), "Bad FTP and https://user:password@example.com/private")
        XCTAssertTrue(JobResultRichText.links(in: attributed).isEmpty)
    }

    func testRichTextBoundsLinkCountAndPreservesLineBreaks() {
        let body = (0..<25)
            .map { "https://example.com/item/\($0)" }
            .joined(separator: "\n")
        let attributed = JobResultRichText.attributedString(body)

        XCTAssertEqual(JobResultRichText.links(in: attributed).count, JobResultRichText.maximumLinks)
        XCTAssertEqual(String(attributed.characters).filter { $0 == "\n" }.count, 24)
    }

    private func job(
        id: String,
        name: String,
        schedule: String,
        kind: String,
        lastStatus: String = "success",
        consecutiveErrors: Int = 0
    ) throws -> ScheduledJob {
        try decode([
            "id": id,
            "name": name,
            "kind": kind,
            "schedule": schedule,
            "enabled": true,
            "nextRunAt": "2026-09-01T12:00:00Z",
            "lastRunAt": "2026-09-01T11:30:00Z",
            "lastStatus": lastStatus,
            "runCount": 4,
            "description": "Fixture job",
            "lastSilentSuccessAt": "2026-09-01T11:30:00Z",
            "lastOutputAt": NSNull(),
            "lastErrorAt": NSNull(),
            "consecutiveErrors": consecutiveErrors,
        ])
    }

    private func result(
        sequence: Int,
        jobID: String,
        jobName: String,
        status: String = "success"
    ) throws -> ScheduledJobResult {
        try decode([
            "sequence": sequence,
            "id": "run_\(sequence)",
            "jobId": jobID,
            "jobName": jobName,
            "status": status,
            "outputKind": "scheduler",
            "startedAt": "2026-09-01T11:29:59Z",
            "finishedAt": "2026-09-01T11:30:00Z",
            "durationSeconds": 1.0,
            "exitCode": 0,
            "title": "Fixture result",
            "summary": "Fixture summary",
            "output": "Fixture output",
            "error": status == "error" ? "Fixture failure" as Any : NSNull(),
            "truncated": false,
        ])
    }

    private func decode<Value: Decodable>(_ object: [String: Any]) throws -> Value {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return try JSONDecoder().decode(Value.self, from: data)
    }
}
