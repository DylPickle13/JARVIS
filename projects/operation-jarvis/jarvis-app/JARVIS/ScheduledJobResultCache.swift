import Foundation
import JARVISKit

private func writeProtectedJARVISData(_ data: Data, to fileURL: URL) throws {
    let directory = fileURL.deletingLastPathComponent()
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    try FileManager.default.setAttributes(
        [.posixPermissions: 0o700],
        ofItemAtPath: directory.path
    )
    var writingOptions: Data.WritingOptions = [.atomic]
    #if os(iOS) || os(watchOS)
    writingOptions.insert(.completeFileProtectionUntilFirstUserAuthentication)
    #endif
    try data.write(to: fileURL, options: writingOptions)
    var attributes: [FileAttributeKey: Any] = [.posixPermissions: 0o600]
    #if os(iOS) || os(watchOS)
    attributes[.protectionKey] = FileProtectionType.completeUntilFirstUserAuthentication
    #endif
    try FileManager.default.setAttributes(attributes, ofItemAtPath: fileURL.path)
}

struct ScheduledJobResultCache: Sendable {
    static let limit = 100

    private struct Payload: Codable {
        let version: Int
        let results: [ScheduledJobResult]
    }

    let fileURL: URL

    init(fileURL: URL? = nil) {
        if let fileURL {
            self.fileURL = fileURL
            return
        }
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        self.fileURL = base
            .appendingPathComponent("JARVIS", isDirectory: true)
            .appendingPathComponent("scheduled-job-results-v1.json", isDirectory: false)
    }

    func load() -> [ScheduledJobResult] {
        guard let data = try? Data(contentsOf: fileURL),
              let payload = try? JSONDecoder().decode(Payload.self, from: data),
              payload.version == 1 else { return [] }
        return Self.normalized(payload.results)
    }

    func save(_ results: [ScheduledJobResult]) {
        let normalized = Self.normalized(results)
        do {
            let data = try JSONEncoder().encode(Payload(version: 1, results: normalized))
            try writeProtectedJARVISData(data, to: fileURL)
        } catch {
            // The authenticated server remains authoritative. A cache failure
            // must never hide fresh in-memory results or interrupt polling.
        }
    }

    static func merging(
        cached: [ScheduledJobResult],
        incoming: [ScheduledJobResult]
    ) -> [ScheduledJobResult] {
        normalized(incoming + cached)
    }

    private static func normalized(_ values: [ScheduledJobResult]) -> [ScheduledJobResult] {
        var seen = Set<Int>()
        return values
            .sorted { lhs, rhs in lhs.sequence > rhs.sequence }
            .filter { seen.insert($0.sequence).inserted }
            .prefix(limit)
            .map { $0 }
    }
}

struct ScheduledJobReadState: Codable, Equatable, Sendable {
    var baselineEstablished: Bool
    var baselineSequence: Int
    var jobReadSequences: [String: Int]

    static let empty = ScheduledJobReadState(
        baselineEstablished: false,
        baselineSequence: 0,
        jobReadSequences: [:]
    )

    func readSequence(for jobID: String) -> Int {
        max(0, jobReadSequences[jobID] ?? (baselineEstablished ? baselineSequence : 0))
    }

    mutating func establishBaseline(_ sequence: Int) {
        guard !baselineEstablished else { return }
        baselineEstablished = true
        baselineSequence = max(baselineSequence, max(0, sequence))
    }

    mutating func markRead(jobID: String, through sequence: Int) {
        guard !jobID.isEmpty, sequence > readSequence(for: jobID) else { return }
        jobReadSequences[jobID] = sequence
    }

    mutating func normalize(limit: Int = 1_000) {
        baselineSequence = max(0, baselineSequence)
        jobReadSequences = Dictionary(
            uniqueKeysWithValues: jobReadSequences
                .filter { !$0.key.isEmpty && $0.value >= 0 }
                .sorted {
                    if $0.value != $1.value { return $0.value > $1.value }
                    return $0.key < $1.key
                }
                .prefix(max(0, limit))
                .map { ($0.key, $0.value) }
        )
    }
}

struct ScheduledJobReadStateStore: Sendable {
    private struct Payload: Codable {
        let version: Int
        let state: ScheduledJobReadState
    }

    let fileURL: URL

    init(fileURL: URL? = nil) {
        if let fileURL {
            self.fileURL = fileURL
            return
        }
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        self.fileURL = base
            .appendingPathComponent("JARVIS", isDirectory: true)
            .appendingPathComponent("scheduled-job-read-state-v2.json", isDirectory: false)
    }

    func load() -> ScheduledJobReadState? {
        guard let data = try? Data(contentsOf: fileURL),
              let payload = try? JSONDecoder().decode(Payload.self, from: data),
              payload.version == 2 else { return nil }
        var state = payload.state
        state.normalize()
        return state
    }

    func save(_ state: ScheduledJobReadState) {
        var normalized = state
        normalized.normalize()
        do {
            let data = try JSONEncoder().encode(Payload(version: 2, state: normalized))
            try writeProtectedJARVISData(data, to: fileURL)
        } catch {
            // Read markers are a local presentation aid. A write failure must
            // never hide or mutate the durable result history itself.
        }
    }
}
