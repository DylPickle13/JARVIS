import Foundation

// URLSession client for the jarvisd API.
//
// Networking note: jarvisd speaks plain HTTP on the LAN / Tailscale. Each host
// app (iOS + watch) sets NSAllowsArbitraryLoads in its Info.plist so the
// standard URLSession below can reach local HTTP endpoints.

public enum JarvisError: LocalizedError, Equatable {
    case notConfigured
    case badURL(String)
    case http(status: Int, body: String)
    case decoding(String)
    case transport(String)

    public var errorDescription: String? {
        switch self {
        case .notConfigured: return "No endpoint configured."
        case .badURL(let s): return "Invalid endpoint URL: \(s)"
        case .http(let status, let body): return "HTTP \(status): \(body)"
        case .decoding(let s): return "Failed to decode response: \(s)"
        case .transport(let s): return "Network error: \(s)"
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

public final class JarvisClient: Sendable {
    private let session: URLSession
    private let decoder: JSONDecoder

    public init(session: URLSession = .shared) {
        self.session = session
        // No key strategy: jarvisd mixes camelCase (state) and snake_case
        // (command passthrough), so each model matches its exact JSON keys.
        self.decoder = JSONDecoder()
    }

    // MARK: - Request plumbing

    private func makeRequest(_ endpoint: JarvisEndpoint, _ path: String, method: String = "GET") throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: endpoint.baseURL)?.absoluteURL else {
            throw JarvisError.badURL(endpoint.baseURL.absoluteString)
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !endpoint.token.isEmpty {
            req.setValue(endpoint.token, forHTTPHeaderField: "x-jarvis-token")
        }
        req.timeoutInterval = 30
        return req
    }

    private func perform<T: Decodable>(_ endpoint: JarvisEndpoint, _ path: String,
                                       method: String = "GET", body: Data? = nil,
                                       as type: T.Type) async throws -> T {
        var req = try makeRequest(endpoint, path, method: method)
        req.httpBody = body
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch let urlError as URLError {
            throw JarvisError.transport(urlError.localizedDescription)
        } catch {
            throw JarvisError.transport(error.localizedDescription)
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw JarvisError.http(status: http.statusCode, body: String(body.prefix(300)))
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw JarvisError.decoding(error.localizedDescription)
        }
    }

    // MARK: - Endpoints

    public func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse {
        try await perform(endpoint, "/health", as: HealthResponse.self)
    }

    /// Try a list of candidate base URLs in parallel (short timeout each) and
    /// return the first one — in the given priority order — that answers
    /// `/health` with 200. Returns nil if none respond. This is what lets the
    /// app "just work": it probes the home LAN IP and the Tailscale IP and
    /// uses whichever is reachable.
    public func discover(_ candidates: [URL], timeout: TimeInterval = 3.0) async -> URL? {
        var ok: [URL: Bool] = [:]
        await withTaskGroup(of: (URL, Bool).self) { group in
            for url in candidates {
                group.addTask { () -> (URL, Bool) in
                    let cfg = URLSessionConfiguration.ephemeral
                    cfg.timeoutIntervalForRequest = timeout
                    cfg.timeoutIntervalForResource = timeout
                    let session = URLSession(configuration: cfg)
                    defer { session.finishTasksAndInvalidate() }
                    var req = URLRequest(url: url.appendingPathComponent("health"))
                    req.timeoutInterval = timeout
                    do {
                        let (_, resp) = try await session.data(for: req)
                        let good = (resp as? HTTPURLResponse)?.statusCode == 200
                        return (url, good)
                    } catch {
                        return (url, false)
                    }
                }
            }
            for await (url, success) in group {
                ok[url] = success
                // Return the highest-priority success as soon as it's known:
                // once the first (best) candidate succeeds, or every candidate
                // has reported, no later result can change the answer. This
                // avoids waiting on a slow/unreachable candidate (e.g. the
                // Tailscale IP when on the home LAN).
                let firstSucceeded = candidates.first.flatMap { ok[$0] } == true
                let allReported = ok.count == candidates.count
                if firstSucceeded || allReported {
                    group.cancelAll()
                }
            }
        }
        for url in candidates where ok[url] == true {
            return url
        }
        return nil
    }

    public func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot {
        try await perform(endpoint, "/api/v1/state", as: StateSnapshot.self)
    }

    public func command(_ endpoint: JarvisEndpoint, action: String, params: [String: JSONValue]? = nil) async throws -> CommandResult {
        let req = CommandRequest(action: action, params: params)
        let encoder = JSONEncoder()
        let body = try encoder.encode(req)
        return try await perform(endpoint, "/api/v1/command", method: "POST", body: body, as: CommandResult.self)
    }

    public func events(_ endpoint: JarvisEndpoint, since: Int? = nil, limit: Int = 100) async throws -> EventsResponse {
        var path = "/api/v1/events?limit=\(limit)"
        if let since { path += "&since=\(since)" }
        return try await perform(endpoint, path, as: EventsResponse.self)
    }

    public func services(_ endpoint: JarvisEndpoint) async throws -> ServicesListResponse {
        try await perform(endpoint, "/api/v1/services", as: ServicesListResponse.self)
    }

    public func serviceAction(_ endpoint: JarvisEndpoint, name: String, action: String) async throws -> ServiceActionResult {
        let body = try JSONSerialization.data(withJSONObject: ["action": action])
        return try await perform(endpoint, "/api/v1/services/\(name)", method: "POST", body: body, as: ServiceActionResult.self)
    }
}
