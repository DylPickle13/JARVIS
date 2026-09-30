import Foundation
import SwiftUI

public struct SystemHistoryConfiguration: Equatable, Sendable {
    public enum Surface: Equatable, Sendable { case phone, watch }
    public let endpoint: JarvisEndpoint?
    public let surface: Surface
    public let visible: Bool
    public let interactive: Bool
    public let connected: Bool
    public init(endpoint: JarvisEndpoint?, surface: Surface, visible: Bool, interactive: Bool, connected: Bool) {
        self.endpoint = endpoint; self.surface = surface; self.visible = visible
        self.interactive = interactive; self.connected = connected
    }
    public var window: SystemHistoryWindow { surface == .watch ? .hour : .day }
    public var component: String? { surface == .watch ? "overall" : nil }
    public var shouldPoll: Bool { visible && interactive && connected && endpoint != nil }
}

/// Memory-only, view-owned historical reads. Never shares foreground state
/// demand, disk caches, discovery/phone relay, device commands or retries.
@MainActor
public final class SystemHistoryModel: ObservableObject {
    @Published public private(set) var snapshot: SystemHistoryResponse?
    @Published public private(set) var isLoading = false
    @Published public private(set) var isPolling = false
    @Published public private(set) var notice: String?
    private var configuration: SystemHistoryConfiguration?
    private var generation = 0
    private var task: Task<Void, Never>?
    private let fetch: @Sendable (JarvisEndpoint, SystemHistoryWindow, String?) async throws -> SystemHistoryResponse
    private let sleep: @Sendable (TimeInterval) async throws -> Void

    public init(fetch: @escaping @Sendable (JarvisEndpoint, SystemHistoryWindow, String?) async throws -> SystemHistoryResponse = {
        try await JarvisClient().systemHistory($0, window: $1, component: $2)
    }, sleep: @escaping @Sendable (TimeInterval) async throws -> Void = {
        try await Task.sleep(for: .seconds($0))
    }) { self.fetch = fetch; self.sleep = sleep }

    public func configure(_ next: SystemHistoryConfiguration) {
        guard configuration != next else { return }
        let identityChanged = configuration?.endpoint != next.endpoint || configuration?.surface != next.surface
        configuration = next
        generation += 1
        task?.cancel(); task = nil
        isLoading = false; isPolling = false
        if identityChanged { snapshot = nil; notice = nil }
        guard next.shouldPoll, let endpoint = next.endpoint else { return }
        start(endpoint: endpoint, configuration: next)
    }

    /// Explicit refresh is single-flight with polling; it cannot issue a second
    /// request while an automatic read is in flight.
    public func refresh() {
        guard let configuration, configuration.shouldPoll, let endpoint = configuration.endpoint, !isLoading else { return }
        generation += 1; task?.cancel(); task = nil
        start(endpoint: endpoint, configuration: configuration)
    }

    private func start(endpoint: JarvisEndpoint, configuration: SystemHistoryConfiguration) {
        let owner = generation
        isPolling = true
        task = Task { @MainActor [weak self] in
            defer {
                if let self, self.generation == owner { self.isPolling = false; self.isLoading = false }
            }
            while !Task.isCancelled {
                guard let self, self.generation == owner else { return }
                self.isLoading = true
                do {
                    let response = try await self.fetch(endpoint, configuration.window, configuration.component)
                    guard !Task.isCancelled, self.generation == owner else { return }
                    self.snapshot = try response.validated(window: configuration.window, component: configuration.component)
                    self.notice = nil
                } catch {
                    guard !Task.isCancelled, self.generation == owner else { return }
                    // No raw error bodies, URLs, tokens or arbitrary backend text.
                    if case JarvisError.http(let status, _) = error, status == 404 {
                        self.notice = "History not supported by this backend"
                    } else if case JarvisError.http(let status, _) = error, status == 401 || status == 403 {
                        self.notice = "History access denied by backend"
                    } else { self.notice = "History temporarily unavailable" }
                }
                self.isLoading = false
                do { try await self.sleep(60) } catch { return }
            }
        }
    }

    public func isStale(now: Date = Date()) -> Bool {
        guard let snapshot, let to = snapshot.end, let latest = snapshot.latestSample else { return snapshot != nil }
        return now.timeIntervalSince(to) > 120 || now.timeIntervalSince(latest) > 150 || to > now.addingTimeInterval(5)
    }

    deinit { task?.cancel() }
}
