import Foundation
import JARVISKit

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
            let directory = fileURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let data = try JSONEncoder().encode(Payload(version: 1, results: normalized))
            try data.write(to: fileURL, options: [.atomic])
            #if os(iOS) || os(watchOS)
            try FileManager.default.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: fileURL.path
            )
            #endif
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
