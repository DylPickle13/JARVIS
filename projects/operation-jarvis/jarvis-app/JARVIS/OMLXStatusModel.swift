import Foundation
import SwiftUI
import JARVISKit

/// Owned only by the iPhone Home card. No AppState/Watch/widget persistence or
/// timer, and no automatic retry for any write (this API supports reads only).
@MainActor
final class OMLXStatusModel: ObservableObject {
    @Published private(set) var snapshot: OMLXSnapshot?
    @Published private(set) var requestStartedAt: Date?
    @Published private(set) var unavailable = false
    @Published private(set) var isPolling = false
    private var endpoint: JarvisEndpoint?
    private var generation = 0
    private let fetch: @Sendable (JarvisEndpoint) async throws -> OMLXSnapshot
    private let sleep: @Sendable (TimeInterval) async throws -> Void

    init(fetch: @escaping @Sendable (JarvisEndpoint) async throws -> OMLXSnapshot,
         sleep: @escaping @Sendable (TimeInterval) async throws -> Void = {
             try await Task.sleep(for: .seconds($0))
         }) {
        self.fetch = fetch
        self.sleep = sleep
    }

    func run(endpoint newEndpoint: JarvisEndpoint?) async {
        generation += 1
        let owner = generation
        if endpoint != newEndpoint {
            snapshot = nil
            requestStartedAt = nil
        }
        endpoint = newEndpoint
        guard let newEndpoint else {
            isPolling = false
            unavailable = true
            return
        }
        isPolling = true
        unavailable = snapshot != nil // resume must first validate old data
        defer {
            if generation == owner {
                isPolling = false
                unavailable = true
            }
        }
        while !Task.isCancelled {
            let started = Date()
            do {
                let result = try await fetch(newEndpoint)
                guard !Task.isCancelled, generation == owner else { return }
                snapshot = result
                requestStartedAt = started
                unavailable = false
            } catch {
                guard !Task.isCancelled, generation == owner else { return }
                // Keep last-good metadata, but never stale rates/progress.
                // Do not display transport error bodies or credentials.
                unavailable = true
            }
            do {
                try await sleep(max(0.1, 2 - Date().timeIntervalSince(started)))
            } catch { return }
            guard generation == owner else { return }
        }
    }
}
