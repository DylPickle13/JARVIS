import Foundation
import SwiftUI

/// View-owned read-only polling shared by iPhone and Watch. Never persisted
/// or started by widgets; the visible interactive surface owns cancellation.
@MainActor
public final class OMLXStatusModel: ObservableObject {
    @Published public private(set) var snapshot: OMLXSnapshot?
    @Published public private(set) var requestStartedAt: Date?
    @Published public private(set) var unavailable = false
    @Published public private(set) var isPolling = false
    private var endpoint: JarvisEndpoint?
    private var generation = 0
    private var configuration: OMLXPollConfiguration?
    private var ownedTask: Task<Void, Never>?
    private let fetch: @Sendable (JarvisEndpoint) async throws -> OMLXSnapshot
    private let sleep: @Sendable (TimeInterval) async throws -> Void

    public init(fetch: @escaping @Sendable (JarvisEndpoint) async throws -> OMLXSnapshot,
         sleep: @escaping @Sendable (TimeInterval) async throws -> Void = {
             try await Task.sleep(for: .seconds($0))
         }) {
        self.fetch = fetch
        self.sleep = sleep
    }

    /// Watch uses one model-owned task so presenting its detail sheet cannot
    /// accidentally cancel the network owner along with the underlying view.
    public func configure(_ next: OMLXPollConfiguration) {
        guard configuration != next else { return }
        configuration = next
        generation += 1
        ownedTask?.cancel()
        ownedTask = nil
        // Invalidate the old surface synchronously, before the new task gets
        // an actor turn. Endpoint/cadence changes cannot briefly label old data live.
        unavailable = true
        isPolling = false
        guard let endpoint = next.endpoint else { return }
        ownedTask = Task { @MainActor [weak self] in
            guard !Task.isCancelled else { return }
            await self?.run(endpoint: endpoint, interval: next.interval)
        }
    }

    deinit { ownedTask?.cancel() }

    public func run(endpoint newEndpoint: JarvisEndpoint?, interval: TimeInterval = 2) async {
        let cadence = interval.isFinite ? min(60, max(1, interval)) : 2
        generation += 1
        let owner = generation
        if let newEndpoint, endpoint != newEndpoint {
            snapshot = nil
            requestStartedAt = nil
        }
        guard let newEndpoint else {
            isPolling = false
            unavailable = true
            return
        }
        endpoint = newEndpoint
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
                try await sleep(max(0.1, cadence - Date().timeIntervalSince(started)))
            } catch { return }
            guard generation == owner else { return }
        }
    }
}
