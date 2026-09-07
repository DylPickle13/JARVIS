import Foundation

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

/// Bounded, target-local cache for retained scheduled-job results.
///
/// The payload version, default path, ordering, and 100-result bound are kept
/// compatible with the Build 145 iPhone cache. iOS and watchOS use separate app
/// containers even though they intentionally use the same relative filename.
public struct ScheduledJobResultCache: Sendable {
    public static let limit = 100
    /// The server retains at most 500 results. Catch-up stays bounded even if a
    /// future server advertises additional continuation pages.
    public static let maximumCatchUpPages = 5

    private struct Payload: Codable {
        let version: Int
        let results: [ScheduledJobResult]
    }

    public let fileURL: URL

    public init(fileURL: URL? = nil) {
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

    public func load() -> [ScheduledJobResult] {
        guard let data = try? Data(contentsOf: fileURL),
              let payload = try? JSONDecoder().decode(Payload.self, from: data),
              payload.version == 1 else { return [] }
        return Self.normalized(payload.results)
    }

    @discardableResult
    public func save(_ results: [ScheduledJobResult]) -> Bool {
        let normalized = Self.normalized(results)
        do {
            let data = try JSONEncoder().encode(Payload(version: 1, results: normalized))
            try writeProtectedJARVISData(data, to: fileURL)
            return true
        } catch {
            // The authenticated server remains authoritative. A cache failure
            // must never hide fresh in-memory results or interrupt polling.
            return false
        }
    }

    public static func merging(
        cached: [ScheduledJobResult],
        incoming: [ScheduledJobResult]
    ) -> [ScheduledJobResult] {
        normalized(incoming + cached)
    }

    /// Keeps an exact, server-verified notification destination available even
    /// when it is older than the ordinary newest-100 cache window. The next
    /// general history sync may replace the pin; ordering, payload format, and
    /// the hard 100-result bound remain unchanged.
    public static func merging(
        cached: [ScheduledJobResult],
        incoming: [ScheduledJobResult],
        preserving sequence: Int
    ) -> [ScheduledJobResult] {
        let merged = normalized(incoming + cached)
        guard sequence > 0,
              !merged.contains(where: { $0.sequence == sequence }),
              let focused = (incoming + cached).first(where: { $0.sequence == sequence }) else {
            return merged
        }
        return normalized([focused] + Array(merged.prefix(max(0, limit - 1))))
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

public struct ScheduledJobReadState: Codable, Equatable, Sendable {
    public var baselineEstablished: Bool
    public var baselineSequence: Int
    public var jobReadSequences: [String: Int]

    public init(
        baselineEstablished: Bool,
        baselineSequence: Int,
        jobReadSequences: [String: Int]
    ) {
        self.baselineEstablished = baselineEstablished
        self.baselineSequence = baselineSequence
        self.jobReadSequences = jobReadSequences
    }

    public static let empty = ScheduledJobReadState(
        baselineEstablished: false,
        baselineSequence: 0,
        jobReadSequences: [:]
    )

    public func readSequence(for jobID: String) -> Int {
        let migrationFloor = baselineEstablished ? baselineSequence : 0
        return max(0, migrationFloor, jobReadSequences[jobID] ?? 0)
    }

    public mutating func establishBaseline(_ sequence: Int) {
        guard !baselineEstablished else { return }
        baselineEstablished = true
        baselineSequence = max(baselineSequence, max(0, sequence))
    }

    public mutating func markRead(jobID: String, through sequence: Int) {
        guard !jobID.isEmpty, sequence > readSequence(for: jobID) else { return }
        jobReadSequences[jobID] = sequence
    }

    public mutating func normalize(limit: Int = 1_000) {
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

public struct ScheduledJobReadStateStore: Sendable {
    private struct Payload: Codable {
        let version: Int
        let state: ScheduledJobReadState
    }

    public let fileURL: URL

    public init(fileURL: URL? = nil) {
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

    public func load() -> ScheduledJobReadState? {
        guard let data = try? Data(contentsOf: fileURL),
              let payload = try? JSONDecoder().decode(Payload.self, from: data),
              payload.version == 2 else { return nil }
        var state = payload.state
        state.normalize()
        return state
    }

    public func save(_ state: ScheduledJobReadState) {
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
