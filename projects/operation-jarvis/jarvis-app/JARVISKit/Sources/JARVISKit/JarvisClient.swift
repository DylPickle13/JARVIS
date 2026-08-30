import Foundation

// URLSession client for the jarvisd API. The production daemon is normally
// reached over LAN/Tailscale HTTP; ATS policy is scoped in each host app's
// Info.plist rather than enabling arbitrary loads globally.

public enum JarvisError: LocalizedError, Equatable, Sendable {
    case notConfigured
    case badURL(String)
    case http(status: Int, body: String)
    case decoding(String)
    case transport(String)

    public var errorDescription: String? {
        switch self {
        case .notConfigured: return "No endpoint configured."
        case .badURL(let value): return "Invalid endpoint URL: \(value)"
        case .http(let status, let body):
            let detail = body.isEmpty ? "" : ": \(body)"
            return "HTTP \(status)\(detail)"
        case .decoding(let value): return "Failed to decode response: \(value)"
        case .transport(let value): return "Network error: \(value)"
        }
    }

    public var isRetryable: Bool {
        switch self {
        case .transport: return true
        case .http(let status, _): return status == 408 || status == 425 || status == 429 || status >= 500
        case .notConfigured, .badURL, .decoding: return false
        }
    }
}

public struct JarvisEndpoint: Equatable, Sendable {
    public let baseURL: URL
    public let token: String

    public init(baseURL: URL, token: String) {
        self.baseURL = baseURL
        self.token = token
    }
}

/// A state snapshot paired with the endpoint that actually served it. Watch
/// clients persist this URL so ordinary refreshes can bypass endpoint
/// discovery until the known-good route fails.
public struct ResolvedJarvisState: Equatable, Sendable {
    public let endpointURL: URL
    public let state: StateSnapshot
    public let usedDiscovery: Bool

    public init(endpointURL: URL, state: StateSnapshot, usedDiscovery: Bool) {
        self.endpointURL = endpointURL
        self.state = state
        self.usedDiscovery = usedDiscovery
    }
}

/// The boundary consumed by AppState, widgets, and the watch relay. Keeping
/// it separate from URLSession makes lifecycle and stale-state behavior
/// testable without a live daemon.
public protocol JarvisAPI: Sendable {
    func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse
    func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot
    func command(_ endpoint: JarvisEndpoint, action: String, params: [String: JSONValue]?) async throws -> CommandResult
    func events(_ endpoint: JarvisEndpoint, since: Int?, limit: Int) async throws -> EventsResponse
    func services(_ endpoint: JarvisEndpoint) async throws -> ServicesListResponse
    func scheduledJobs(_ endpoint: JarvisEndpoint) async throws -> ScheduledJobsResponse
    func scheduledJobResults(
        _ endpoint: JarvisEndpoint,
        after: Int?,
        limit: Int,
        jobId: String?
    ) async throws -> ScheduledJobResultsResponse
    func serviceAction(_ endpoint: JarvisEndpoint, name: String, action: String) async throws -> ServiceActionResult
    func signingRenewalStatus(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus
    func startSigningRenewal(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus
    func discover(_ candidates: [URL], timeout: TimeInterval) async -> URL?
}

public final class JarvisClient: @unchecked Sendable, JarvisAPI {
    private let session: URLSession
    private let discoveryProbe: @Sendable (URL, TimeInterval) async -> Bool

    public init(session: URLSession = .shared) {
        self.session = session
        self.discoveryProbe = { base, timeout in
            await Self.probeHealth(base, timeout: timeout)
        }
    }

    init(
        session: URLSession = .shared,
        discoveryProbe: @escaping @Sendable (URL, TimeInterval) async -> Bool
    ) {
        self.session = session
        self.discoveryProbe = discoveryProbe
    }

    // MARK: - Request plumbing

    private func makeRequest(_ endpoint: JarvisEndpoint, _ path: String, method: String = "GET") throws -> URLRequest {
        guard let baseURL = JarvisEndpointURLPolicy.normalize(endpoint.baseURL),
              let requestComponents = URLComponents(string: path),
              requestComponents.scheme == nil,
              requestComponents.host == nil,
              requestComponents.user == nil,
              requestComponents.password == nil,
              requestComponents.fragment == nil,
              requestComponents.percentEncodedPath.hasPrefix("/"),
              var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw JarvisError.badURL(endpoint.baseURL.absoluteString)
        }
        components.percentEncodedPath = requestComponents.percentEncodedPath
        components.percentEncodedQuery = requestComponents.percentEncodedQuery
        guard let url = components.url else {
            throw JarvisError.badURL(endpoint.baseURL.absoluteString)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if method != "GET" { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if !endpoint.token.isEmpty {
            request.setValue(endpoint.token, forHTTPHeaderField: "x-jarvis-token")
        }
        request.timeoutInterval = 30
        return request
    }

    private func perform<T: Decodable>(
        _ endpoint: JarvisEndpoint,
        _ path: String,
        method: String = "GET",
        body: Data? = nil,
        requestTimeout: TimeInterval? = nil,
        as type: T.Type
    ) async throws -> T {
        var request = try makeRequest(endpoint, path, method: method)
        if let requestTimeout { request.timeoutInterval = max(0.2, requestTimeout) }
        request.httpBody = body
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError {
            throw JarvisError.transport(error.localizedDescription)
        } catch {
            throw JarvisError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw JarvisError.transport("Invalid server response.")
        }
        guard (200..<300).contains(http.statusCode) else {
            let raw = String(data: data, encoding: .utf8) ?? ""
            let body = String(raw.prefix(500))
            throw JarvisError.http(status: http.statusCode, body: body)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw JarvisError.decoding(error.localizedDescription)
        }
    }

    // MARK: - Discovery

    /// Probe candidates concurrently but preserve their declared priority.
    /// A lower-priority success wins only after every higher-priority
    /// candidate has reported failure. Unstructured probe tasks are canceled
    /// once the winner is known, so discovery does not wait for an unrelated
    /// Tailscale timeout.
    public func discover(_ candidates: [URL], timeout: TimeInterval = 3.0) async -> URL? {
        var seen = Set<URL>()
        let unique = candidates.compactMap { candidate -> URL? in
            guard let normalized = JarvisEndpointURLPolicy.normalize(candidate),
                  seen.insert(normalized).inserted else { return nil }
            return normalized
        }
        guard !unique.isEmpty else { return nil }
        if Task.isCancelled { return nil }
        let coordinator = DiscoveryCoordinator(candidates: unique, probe: discoveryProbe)
        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                coordinator.start(timeout: max(0.2, timeout), continuation: continuation)
            }
        }, onCancel: {
            coordinator.cancel()
        })
    }

    /// Fetch state directly from the last known-good endpoint. Discovery is a
    /// bounded recovery path, not part of every refresh. The discovery probe
    /// already validates `/health`, so a successful recovery proceeds straight
    /// to `/api/v1/state` without issuing a redundant second health request.
    public func resolveState(
        preferredEndpoint: URL?,
        candidates: [URL],
        token: String,
        discoveryTimeout: TimeInterval = 3.0
    ) async throws -> ResolvedJarvisState {
        let normalizedPreferred = preferredEndpoint.flatMap(JarvisEndpointURLPolicy.normalize)
        var preferredFailure: JarvisError? = preferredEndpoint != nil && normalizedPreferred == nil
            ? .badURL(preferredEndpoint?.absoluteString ?? "")
            : nil

        if let normalizedPreferred {
            do {
                let endpoint = JarvisEndpoint(baseURL: normalizedPreferred, token: token)
                let state = try await perform(
                    endpoint,
                    "/api/v1/state",
                    requestTimeout: discoveryTimeout,
                    as: StateSnapshot.self
                )
                return ResolvedJarvisState(
                    endpointURL: normalizedPreferred,
                    state: state,
                    usedDiscovery: false
                )
            } catch is CancellationError {
                throw CancellationError()
            } catch let error as JarvisError {
                preferredFailure = error
            } catch {
                preferredFailure = .transport(error.localizedDescription)
            }
        }

        guard !Task.isCancelled else { throw CancellationError() }
        // A failed state read is stronger evidence than a health probe, so do
        // not immediately re-probe the same route. If no alternate succeeds,
        // the stored route remains intact and the next scheduled refresh can
        // try it again.
        let recoveryCandidates = candidates.filter {
            JarvisEndpointURLPolicy.normalize($0) != normalizedPreferred
        }
        guard let discovered = await discover(recoveryCandidates, timeout: discoveryTimeout) else {
            guard !Task.isCancelled else { throw CancellationError() }
            throw preferredFailure ?? JarvisError.transport("No JARVIS endpoint responded.")
        }
        let state = try await state(JarvisEndpoint(baseURL: discovered, token: token))
        return ResolvedJarvisState(
            endpointURL: discovered,
            state: state,
            usedDiscovery: true
        )
    }

    // MARK: - Endpoints

    public func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse {
        try await perform(endpoint, "/health", as: HealthResponse.self)
    }

    public func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot {
        try await perform(endpoint, "/api/v1/state", as: StateSnapshot.self)
    }

    /// Requests one immediate refresh of jarvisd's read-only Codex quota
    /// collector and returns the current state snapshot. Completion remains
    /// observable through subsequent ordinary state reads.
    public func stateRefreshingCodexQuota(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot {
        try await perform(endpoint, "/api/v1/state?refresh=codexQuota", as: StateSnapshot.self)
    }

    public func command(
        _ endpoint: JarvisEndpoint,
        action: String,
        params: [String: JSONValue]? = nil
    ) async throws -> CommandResult {
        let body = try JSONEncoder().encode(CommandRequest(action: action, params: params))
        return try await perform(endpoint, "/api/v1/command", method: "POST", body: body, as: CommandResult.self)
    }

    public func events(_ endpoint: JarvisEndpoint, since: Int? = nil, limit: Int = 100) async throws -> EventsResponse {
        let safeLimit = min(max(limit, 1), 500)
        var path = "/api/v1/events?limit=\(safeLimit)"
        if let since { path += "&since=\(max(0, since))" }
        return try await perform(endpoint, path, as: EventsResponse.self)
    }

    public func services(_ endpoint: JarvisEndpoint) async throws -> ServicesListResponse {
        try await perform(endpoint, "/api/v1/services", as: ServicesListResponse.self)
    }

    public func scheduledJobs(_ endpoint: JarvisEndpoint) async throws -> ScheduledJobsResponse {
        try await perform(endpoint, "/api/v1/scheduled-jobs", as: ScheduledJobsResponse.self)
    }

    public func scheduledJobResults(
        _ endpoint: JarvisEndpoint,
        after: Int? = nil,
        limit: Int = 50,
        jobId: String? = nil
    ) async throws -> ScheduledJobResultsResponse {
        var components = URLComponents()
        components.path = "/api/v1/scheduled-job-results"
        var queryItems = [URLQueryItem(name: "limit", value: String(min(max(limit, 1), 100)))]
        if let after { queryItems.append(URLQueryItem(name: "after", value: String(max(0, after)))) }
        if let jobId, !jobId.isEmpty { queryItems.append(URLQueryItem(name: "jobId", value: jobId)) }
        components.queryItems = queryItems
        guard let path = components.string else { throw JarvisError.badURL("scheduled-job-results") }
        return try await perform(endpoint, path, as: ScheduledJobResultsResponse.self)
    }

    public func serviceAction(_ endpoint: JarvisEndpoint, name: String, action: String) async throws -> ServiceActionResult {
        let encodedName = name.addingPercentEncoding(withAllowedCharacters: .jarvisPathSegment) ?? name
        let body = try JSONSerialization.data(withJSONObject: ["action": action])
        return try await perform(endpoint, "/api/v1/services/\(encodedName)", method: "POST", body: body, as: ServiceActionResult.self)
    }

    public func signingRenewalStatus(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus {
        try await perform(endpoint, "/api/v1/signing/status", as: SigningRenewalStatus.self)
    }

    public func startSigningRenewal(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus {
        try await perform(endpoint, "/api/v1/signing/renew", method: "POST", as: SigningRenewalStatus.self)
    }
}

private extension CharacterSet {
    static let jarvisPathSegment = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")
}

private final class DiscoveryCoordinator: @unchecked Sendable {
    private let lock = NSLock()
    private let candidates: [URL]
    private let probe: @Sendable (URL, TimeInterval) async -> Bool
    private var results: [Bool?]
    private var tasks: [Task<Void, Never>] = []
    private var continuation: CheckedContinuation<URL?, Never>?
    private var finished = false

    init(
        candidates: [URL],
        probe: @escaping @Sendable (URL, TimeInterval) async -> Bool
    ) {
        self.candidates = candidates
        self.probe = probe
        self.results = Array(repeating: nil, count: candidates.count)
    }

    func start(timeout: TimeInterval, continuation: CheckedContinuation<URL?, Never>) {
        lock.lock()
        guard !finished else {
            lock.unlock()
            continuation.resume(returning: nil)
            return
        }
        self.continuation = continuation
        for (index, candidate) in candidates.enumerated() {
            let task = Task { [weak self, probe] in
                let success = await probe(candidate, timeout)
                self?.record(index: index, success: success)
            }
            tasks.append(task)
        }
        lock.unlock()
    }

    func cancel() {
        finish(nil)
    }

    private func record(index: Int, success: Bool) {
        var winner: URL?
        var shouldFinishWithoutWinner = false
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        results[index] = success
        // Re-evaluate every completed success whenever any probe finishes. A
        // lower-priority success may have arrived before the final
        // higher-priority failure that makes it eligible.
        for candidateIndex in candidates.indices where results[candidateIndex] == true {
            let higherFailed = results[..<candidateIndex].allSatisfy { $0 == false }
            if higherFailed {
                winner = candidates[candidateIndex]
                break
            }
        }
        if winner == nil, results.allSatisfy({ $0 != nil }) {
            shouldFinishWithoutWinner = true
        }
        lock.unlock()

        if let winner {
            finish(winner)
        } else if shouldFinishWithoutWinner {
            finish(nil)
        }
    }

    private func finish(_ value: URL?) {
        let continuation: CheckedContinuation<URL?, Never>?
        let tasks: [Task<Void, Never>]
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        continuation = self.continuation
        self.continuation = nil
        tasks = self.tasks
        self.tasks.removeAll()
        lock.unlock()
        tasks.forEach { $0.cancel() }
        continuation?.resume(returning: value)
    }

}

private extension JarvisClient {
    static func probeHealth(_ base: URL, timeout: TimeInterval) async -> Bool {
        guard let base = JarvisEndpointURLPolicy.normalize(base) else { return false }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout
        let session = URLSession(configuration: configuration)
        defer { session.finishTasksAndInvalidate() }
        var request = URLRequest(url: base.appendingPathComponent("health"))
        request.timeoutInterval = timeout
        do {
            let (_, response) = try await session.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }
}
