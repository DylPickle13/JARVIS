import Foundation
import JARVISKit

/// Target-local, read-only Jobs state for Apple Watch. Networking is active only
/// while the fourth dashboard page is interactively visible, except for an
/// explicit notification-tap lookup.
@MainActor
final class WatchJobsModel: ObservableObject {
    @Published private(set) var scheduledJobs: [ScheduledJob] = []
    @Published private(set) var results: [ScheduledJobResult]
    @Published private(set) var scheduledJobsLoaded = false
    @Published private(set) var resultsLoaded: Bool
    @Published private(set) var isRefreshing = false
    @Published private(set) var scheduledJobsErrorMessage: String?
    @Published private(set) var resultsErrorMessage: String?
    @Published private(set) var selectedJobID: String?
    @Published private(set) var focusedResultSequence: Int?
    @Published private(set) var pendingRoute: ScheduledJobNavigationRequest?
    @Published private(set) var routeErrorMessage: String?
    @Published private(set) var isResolvingRoute = false
    @Published private(set) var lastSuccessfulRefreshAt: Date?

    private let store: EndpointStore
    private let client: any JarvisAPI
    private let resultCache: ScheduledJobResultCache
    private let readStateStore: ScheduledJobReadStateStore
    private let preferences: UserDefaults
    private let activeRefreshInterval: Duration
    private let fullHistoryKey = "jarvis.watch.jobs.full-history-established.v1"
    private let historyCursorKey = "jarvis.watch.jobs.history-cursor.v1"

    private var readState: ScheduledJobReadState
    private var fullHistoryEstablished: Bool
    private var historyCursor: Int?
    private var pageIsVisible = false
    private var sceneIsInteractive = false
    private var pollGeneration = 0
    private var pollingTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?

    init(
        store: EndpointStore,
        client: any JarvisAPI,
        activeRefreshInterval: Duration = JARVISRefreshPolicy.activeInterval,
        preferences: UserDefaults = .standard,
        resultCacheURL: URL? = nil,
        resultReadStateURL: URL? = nil
    ) {
        self.store = store
        self.client = client
        self.activeRefreshInterval = activeRefreshInterval
        self.preferences = preferences
        let cache = ScheduledJobResultCache(fileURL: resultCacheURL)
        self.resultCache = cache
        let readStore = ScheduledJobReadStateStore(fileURL: resultReadStateURL)
        self.readStateStore = readStore

        let cachedResults = cache.load()
        self.results = cachedResults
        self.resultsLoaded = !cachedResults.isEmpty
        self.fullHistoryEstablished = preferences.bool(forKey: fullHistoryKey) && !cachedResults.isEmpty
        if self.fullHistoryEstablished, let cachedCursor = cachedResults.map(\.sequence).max() {
            let persisted = (preferences.object(forKey: historyCursorKey) as? NSNumber)?.intValue
            self.historyCursor = min(max(0, persisted ?? cachedCursor), cachedCursor)
        } else {
            // Never trust a defaults cursor without its protected cache. A
            // focused lookup may also have created a cache before full sync.
            self.historyCursor = nil
        }
        if let saved = readStore.load() {
            self.readState = saved
        } else {
            let cachedBaseline = cachedResults.map(\.sequence).max() ?? 0
            self.readState = ScheduledJobReadState(
                baselineEstablished: self.fullHistoryEstablished && cachedBaseline > 0,
                baselineSequence: self.fullHistoryEstablished ? cachedBaseline : 0,
                jobReadSequences: [:]
            )
            if self.readState.baselineEstablished {
                readStore.save(self.readState)
            }
        }
    }

    deinit {
        pollingTask?.cancel()
        refreshTask?.cancel()
    }

    var sections: ScheduledJobThreadSections {
        JobsPresentation.threads(jobs: scheduledJobs, results: results)
    }

    var selectedThread: ScheduledJobThread? {
        guard let selectedJobID else { return nil }
        return (sections.scheduled + sections.archived).first { $0.id == selectedJobID }
    }

    var unreadJobCount: Int {
        Set(results.lazy.filter(isUnread).map(\.jobId)).count
    }

    var isInitiallyLoading: Bool {
        isRefreshing && scheduledJobs.isEmpty && results.isEmpty
    }

    func containsResult(sequence: Int) -> Bool {
        sequence > 0 && results.contains { $0.sequence == sequence }
    }

    func unreadResultCount(for jobID: String) -> Int {
        results.lazy.filter { $0.jobId == jobID && self.isUnread($0) }.count
    }

    func setPageVisible(_ visible: Bool) {
        guard pageIsVisible != visible else { return }
        pageIsVisible = visible
        updatePolling()
    }

    func sceneDidBecomeInteractive() {
        guard !sceneIsInteractive else { return }
        sceneIsInteractive = true
        updatePolling()
    }

    func sceneDidEnterAlwaysOn() {
        guard sceneIsInteractive else { return }
        sceneIsInteractive = false
        updatePolling()
    }

    func sceneDidEnterBackground() {
        sceneIsInteractive = false
        stopNetworking()
    }

    func refreshIfVisible() async {
        guard pageIsVisible, sceneIsInteractive else { return }
        await refresh()
    }

    func refresh() async {
        if let refreshTask {
            await refreshTask.value
            return
        }
        let generation = pollGeneration
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performRefresh()
        }
        refreshTask = task
        await task.value
        if generation == pollGeneration {
            refreshTask = nil
        }
    }

    func openThread(jobID: String, focusedSequence: Int? = nil) {
        guard !(sections.scheduled + sections.archived).filter({ $0.id == jobID }).isEmpty else { return }
        selectedJobID = jobID
        focusedResultSequence = focusedSequence
        markRead(jobID: jobID)
    }

    func closeThread() {
        selectedJobID = nil
        focusedResultSequence = nil
    }

    func markSelectedThreadRead() {
        guard let selectedJobID else { return }
        markRead(jobID: selectedJobID)
    }

    /// Resolves only the exact requested sequence. A racing page refresh gets a
    /// five-second bounded opportunity to publish it first. The route remains
    /// pending across transient failures and is consumed by the coordinator
    /// only after this method has established the destination.
    func resolve(_ route: ScheduledJobNavigationRequest) async -> Bool {
        pendingRoute = route
        // Loading and Retry are result-specific destinations. Never leave a
        // previously opened thread visible while this explicit route is pending.
        selectedJobID = nil
        focusedResultSequence = nil
        routeErrorMessage = nil
        isResolvingRoute = true
        defer {
            if pendingRoute?.id == route.id { isResolvingRoute = false }
        }

        if openCachedResult(for: route) { return true }

        for _ in 0..<100 where isRefreshing {
            do {
                try await Task.sleep(for: .milliseconds(50))
            } catch {
                return false
            }
            guard pendingRoute?.id == route.id else { return false }
            if openCachedResult(for: route) { return true }
        }

        guard pendingRoute?.id == route.id else { return false }
        guard !isRefreshing else {
            routeErrorMessage = "Jobs are still refreshing. Try again."
            return false
        }
        guard let endpoint = store.endpoint else {
            routeErrorMessage = "The private Jobs endpoint is unavailable."
            return false
        }

        do {
            let response = try await client.scheduledJobResults(
                endpoint,
                after: route.resultSequence - 1,
                limit: 1,
                jobId: nil
            )
            guard pendingRoute?.id == route.id else { return false }
            guard response.ok else {
                routeErrorMessage = response.error ?? "This retained job result is unavailable."
                return false
            }
            guard response.results.count == 1,
                  let result = response.results.first,
                  result.sequence == route.resultSequence else {
                routeErrorMessage = "Result #\(route.resultSequence) is no longer retained."
                return false
            }
            acceptResults(
                [result],
                establishesFullHistory: false,
                preserving: route.resultSequence
            )
            guard openCachedResult(for: route) else {
                routeErrorMessage = "Result #\(route.resultSequence) is no longer retained."
                return false
            }
            return true
        } catch is CancellationError {
            return false
        } catch let error as JarvisError {
            guard pendingRoute?.id == route.id else { return false }
            routeErrorMessage = error.errorDescription
            return false
        } catch {
            guard pendingRoute?.id == route.id else { return false }
            routeErrorMessage = error.localizedDescription
            return false
        }
    }

    @discardableResult
    func dismissPendingRoute() -> ScheduledJobNavigationRequest? {
        let route = pendingRoute
        pendingRoute = nil
        routeErrorMessage = nil
        isResolvingRoute = false
        return route
    }

    private func updatePolling() {
        pollGeneration += 1
        pollingTask?.cancel()
        pollingTask = nil
        guard pageIsVisible, sceneIsInteractive else {
            refreshTask?.cancel()
            refreshTask = nil
            isRefreshing = false
            return
        }
        let generation = pollGeneration
        pollingTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.refresh()
            while !Task.isCancelled,
                  generation == self.pollGeneration,
                  self.pageIsVisible,
                  self.sceneIsInteractive {
                do {
                    try await Task.sleep(for: self.activeRefreshInterval)
                } catch {
                    return
                }
                guard !Task.isCancelled,
                      generation == self.pollGeneration,
                      self.pageIsVisible,
                      self.sceneIsInteractive else { return }
                await self.refresh()
            }
        }
    }

    private func stopNetworking() {
        pollGeneration += 1
        pollingTask?.cancel()
        pollingTask = nil
        refreshTask?.cancel()
        refreshTask = nil
        isRefreshing = false
    }

    private func performRefresh() async {
        guard let endpoint = store.endpoint else {
            scheduledJobsErrorMessage = "The private Jobs endpoint is unavailable."
            resultsErrorMessage = "Cached messages remain available."
            return
        }
        isRefreshing = true
        defer { isRefreshing = false }

        var jobsSucceeded = false
        do {
            let response = try await client.scheduledJobs(endpoint)
            guard !Task.isCancelled else { return }
            scheduledJobsLoaded = true
            if response.ok {
                scheduledJobs = response.jobs
                scheduledJobsErrorMessage = nil
                jobsSucceeded = true
            } else {
                scheduledJobsErrorMessage = response.error ?? "Scheduled-job status is unavailable."
            }
        } catch is CancellationError {
            return
        } catch let error as JarvisError {
            scheduledJobsLoaded = true
            scheduledJobsErrorMessage = error.errorDescription
        } catch {
            scheduledJobsLoaded = true
            scheduledJobsErrorMessage = error.localizedDescription
        }

        guard !Task.isCancelled else { return }
        var resultsSucceeded = false
        let cursor = fullHistoryEstablished ? historyCursor : nil
        do {
            var pageCursor = cursor
            var pageCount = 0
            while true {
                let response = try await client.scheduledJobResults(
                    endpoint,
                    after: pageCursor,
                    limit: ScheduledJobResultCache.limit,
                    jobId: nil
                )
                guard !Task.isCancelled else { return }
                resultsLoaded = true
                guard response.ok else {
                    resultsErrorMessage = response.error ?? "Scheduled-job results are unavailable."
                    resultsSucceeded = false
                    break
                }

                let cacheSaved = acceptResults(response.results, establishesFullHistory: true)
                let advancedCursor = max(pageCursor ?? 0, response.nextAfter)
                historyCursor = advancedCursor
                if cacheSaved {
                    preferences.set(advancedCursor, forKey: historyCursorKey)
                }
                pageCount += 1
                resultsSucceeded = true

                // An uncursored request is already the newest bounded window;
                // only ascending cursored pages need continuation catch-up.
                guard pageCursor != nil,
                      response.hasMore,
                      pageCount < ScheduledJobResultCache.maximumCatchUpPages else { break }
                guard response.nextAfter > (pageCursor ?? 0) else {
                    resultsErrorMessage = "Scheduled-job result continuation is invalid."
                    resultsSucceeded = false
                    break
                }
                pageCursor = response.nextAfter
            }
            if resultsSucceeded { resultsErrorMessage = nil }
        } catch is CancellationError {
            return
        } catch let error as JarvisError {
            resultsLoaded = true
            resultsSucceeded = false
            resultsErrorMessage = error.errorDescription
        } catch {
            resultsLoaded = true
            resultsSucceeded = false
            resultsErrorMessage = error.localizedDescription
        }

        if jobsSucceeded && resultsSucceeded {
            lastSuccessfulRefreshAt = Date()
        }
    }

    @discardableResult
    private func acceptResults(
        _ incoming: [ScheduledJobResult],
        establishesFullHistory: Bool,
        preserving focusedSequence: Int? = nil
    ) -> Bool {
        if let requiredSequence = focusedSequence ?? focusedResultSequence {
            results = ScheduledJobResultCache.merging(
                cached: results,
                incoming: incoming,
                preserving: requiredSequence
            )
        } else {
            results = ScheduledJobResultCache.merging(cached: results, incoming: incoming)
        }
        let cacheSaved = resultCache.save(results)
        if establishesFullHistory {
            fullHistoryEstablished = true
            if cacheSaved { preferences.set(true, forKey: fullHistoryKey) }
        }
        // Only a complete initial history request may establish migration.
        // A focused notification lookup can be older than retained history and
        // must not make later Build 145 results appear unread on first sync.
        if establishesFullHistory, !readState.baselineEstablished {
            // Only the general-sync response owns migration. A focused result
            // already in the cache must not raise this global read floor.
            readState.establishBaseline(incoming.map(\.sequence).max() ?? 0)
            readStateStore.save(readState)
        }
        if let selectedJobID {
            markRead(jobID: selectedJobID)
        }
        return cacheSaved
    }

    private func openCachedResult(for route: ScheduledJobNavigationRequest) -> Bool {
        guard pendingRoute?.id == route.id,
              let result = results.first(where: { $0.sequence == route.resultSequence }) else { return false }
        selectedJobID = result.jobId
        focusedResultSequence = result.sequence
        markRead(jobID: result.jobId)
        pendingRoute = nil
        routeErrorMessage = nil
        isResolvingRoute = false
        return true
    }

    private func markRead(jobID: String) {
        guard let newest = results.lazy
            .filter({ $0.jobId == jobID })
            .map(\.sequence)
            .max() else { return }
        let previous = readState.readSequence(for: jobID)
        readState.markRead(jobID: jobID, through: newest)
        guard readState.readSequence(for: jobID) != previous else { return }
        readStateStore.save(readState)
    }

    private func isUnread(_ result: ScheduledJobResult) -> Bool {
        result.sequence > readState.readSequence(for: result.jobId)
    }
}
