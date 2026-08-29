import CryptoKit
import Foundation
import Security

/// Target-local credentials and endpoint for the Watch terminal bridge.
/// The bearer token is transferred only over WatchConnectivity and stored in
/// each host's local Keychain; it must never be logged or committed.
public struct WatchTerminalConfiguration: Codable, Equatable, Sendable {
    public let endpoint: String
    public let token: String
    public let certificateSHA256: String

    public init(endpoint: String, token: String, certificateSHA256: String) {
        self.endpoint = endpoint.trimmingCharacters(in: .whitespacesAndNewlines)
        self.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        self.certificateSHA256 = Self.normalizeFingerprint(certificateSHA256)
    }

    public var baseURL: URL? {
        guard let components = URLComponents(string: endpoint),
              components.scheme?.lowercased() == "https",
              components.host?.isEmpty == false,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil else { return nil }
        return components.url
    }

    public var isValid: Bool {
        baseURL != nil
            && token.utf8.count >= 32
            && certificateSHA256.count == 64
            && certificateSHA256.allSatisfy(\.isHexDigit)
    }

    /// Direct terminal bridge candidates in priority order. Existing setup
    /// codes contain one preferred endpoint, normally the home LAN address.
    /// The stable MagicDNS and current Tailscale hosts are derived from the
    /// canonical jarvisd candidate list so previously provisioned Watches gain
    /// off-LAN recovery without retransmitting credentials.
    public var candidateBaseURLs: [URL] {
        guard let preferred = baseURL else { return [] }
        var output: [URL] = []
        var seen = Set<String>()

        func add(_ url: URL?) {
            guard let url else { return }
            let key = url.absoluteString.lowercased()
            guard seen.insert(key).inserted else { return }
            output.append(url)
        }

        add(preferred)
        for controlEndpoint in JarvisEndpoints.defaults {
            guard let controlURL = URL(string: controlEndpoint),
                  let host = controlURL.host else { continue }
            var components = URLComponents()
            components.scheme = "https"
            components.host = host
            components.port = preferred.port ?? 8792
            components.path = preferred.path
            add(components.url)
        }
        return output
    }

    public func provisioningCode() throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(self).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    public static func fromProvisioningCode(_ raw: String) -> WatchTerminalConfiguration? {
        var encoded = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = encoded.count % 4
        if remainder != 0 { encoded += String(repeating: "=", count: 4 - remainder) }
        guard let data = Data(base64Encoded: encoded),
              let decoded = try? JSONDecoder().decode(Self.self, from: data),
              decoded.isValid else { return nil }
        return decoded
    }

    public static func normalizeFingerprint(_ raw: String) -> String {
        raw.lowercased().filter(\.isHexDigit)
    }
}

public enum WatchTerminalClientError: LocalizedError, Equatable, Sendable {
    case notConfigured
    case invalidResponse
    case rejected(String)
    case certificateRejected
    case offline
    case notConnected
    case submissionUnconfirmed
    case invalidAudio

    public var errorDescription: String? {
        switch self {
        case .notConfigured: return "The terminal is not configured."
        case .invalidResponse: return "The terminal bridge returned an invalid response."
        case .rejected(let message): return message
        case .certificateRejected: return "The terminal identity did not match."
        case .offline: return "The terminal is offline."
        case .notConnected: return "No authenticated terminal route is selected."
        case .submissionUnconfirmed: return "Terminal submission was not confirmed."
        case .invalidAudio: return "The JARVIS voice service returned invalid audio."
        }
    }
}

public enum WatchTerminalSpeechRetryPolicy {
    public static let maximumAttempts = 6

    public static func shouldRetry(_ error: WatchTerminalClientError) -> Bool {
        switch error {
        case .offline, .notConnected:
            return true
        case .notConfigured, .invalidResponse, .rejected,
             .certificateRejected, .submissionUnconfirmed, .invalidAudio:
            return false
        }
    }

    public static func delaySeconds(afterFailure attempt: Int) -> Double {
        min(12, pow(2, Double(max(0, attempt - 1))))
    }
}

public struct PreparedWatchTerminalSpeech: Equatable, Sendable {
    public let responseID: String
    public let fileURL: URL

    public init(responseID: String, fileURL: URL) {
        self.responseID = responseID
        self.fileURL = fileURL
    }
}

/// Owns the Watch's one retained response WAV and cleans up interrupted
/// UUID-named downloads without touching unrelated temporary files.
public final class WatchTerminalSpeechFileStore {
    public static let maximumAudioBytes = 20 * 1024 * 1024
    public static let transientFilePrefix = "jarvis-watch-speech-"
    public static let preparedFileName = "jarvis-watch-last-response.wav"
    public static let defaultResponseIDKey = "jarvis.watch-terminal.prepared-speech-response-id"

    private let fileManager: FileManager
    private let defaults: UserDefaults
    private let cacheDirectory: URL?
    private let temporaryDirectory: URL
    private let responseIDKey: String

    public init(
        fileManager: FileManager = .default,
        defaults: UserDefaults = .standard,
        cacheDirectory: URL? = nil,
        temporaryDirectory: URL? = nil,
        responseIDKey: String = WatchTerminalSpeechFileStore.defaultResponseIDKey
    ) {
        self.fileManager = fileManager
        self.defaults = defaults
        self.cacheDirectory = cacheDirectory
            ?? fileManager.urls(for: .cachesDirectory, in: .userDomainMask).first
        self.temporaryDirectory = temporaryDirectory ?? fileManager.temporaryDirectory
        self.responseIDKey = responseIDKey
    }

    public var preparedFileURL: URL? {
        cacheDirectory?.appendingPathComponent(Self.preparedFileName, isDirectory: false)
    }

    @discardableResult
    public func removeOrphanedDownloads() -> Int {
        guard let files = try? fileManager.contentsOfDirectory(
            at: temporaryDirectory,
            includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey],
            options: [.skipsHiddenFiles, .skipsSubdirectoryDescendants]
        ) else { return 0 }
        var removed = 0
        for fileURL in files where Self.isTransientSpeechFileName(fileURL.lastPathComponent) {
            guard let values = try? fileURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]),
                  values.isRegularFile == true,
                  values.isSymbolicLink != true else { continue }
            do {
                try fileManager.removeItem(at: fileURL)
                removed += 1
            } catch {
                continue
            }
        }
        return removed
    }

    public func restorePreparedSpeech() -> PreparedWatchTerminalSpeech? {
        guard let responseID = defaults.string(forKey: responseIDKey),
              Self.isValidResponseID(responseID),
              let fileURL = preparedFileURL,
              isValidAudioFile(fileURL) else {
            discardPreparedSpeech()
            return nil
        }
        return PreparedWatchTerminalSpeech(responseID: responseID, fileURL: fileURL)
    }

    public func retainPreparedSpeech(from sourceURL: URL, responseID: String) throws -> URL {
        guard Self.isValidResponseID(responseID),
              isValidAudioFile(sourceURL),
              let destination = preparedFileURL else {
            throw WatchTerminalClientError.invalidAudio
        }
        try fileManager.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        defaults.removeObject(forKey: responseIDKey)
        if sourceURL.standardizedFileURL != destination.standardizedFileURL {
            try? fileManager.removeItem(at: destination)
            do {
                try fileManager.moveItem(at: sourceURL, to: destination)
            } catch {
                try? fileManager.removeItem(at: destination)
                throw error
            }
        }
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutableDestination = destination
        try? mutableDestination.setResourceValues(values)
        defaults.set(responseID, forKey: responseIDKey)
        return destination
    }

    public func discardPreparedSpeech() {
        if let preparedFileURL { try? fileManager.removeItem(at: preparedFileURL) }
        defaults.removeObject(forKey: responseIDKey)
    }

    private static func isTransientSpeechFileName(_ name: String) -> Bool {
        guard name.hasPrefix(transientFilePrefix), name.hasSuffix(".wav") else { return false }
        let start = name.index(name.startIndex, offsetBy: transientFilePrefix.count)
        let end = name.index(name.endIndex, offsetBy: -4)
        let identifier = String(name[start..<end])
        return identifier.count == 36 && UUID(uuidString: identifier) != nil
    }

    private static func isValidResponseID(_ responseID: String) -> Bool {
        responseID.count == 64 && responseID.allSatisfy(\.isHexDigit)
    }

    private func isValidAudioFile(_ fileURL: URL) -> Bool {
        guard let values = try? fileURL.resourceValues(
            forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
        ),
        values.isRegularFile == true,
        values.isSymbolicLink != true,
        let size = values.fileSize,
        size > 12,
        size <= Self.maximumAudioBytes,
        let handle = try? FileHandle(forReadingFrom: fileURL) else { return false }
        defer { try? handle.close() }
        guard let header = try? handle.read(upToCount: 12), header.count == 12 else { return false }
        return String(data: header.prefix(4), encoding: .ascii) == "RIFF"
            && String(data: header.suffix(4), encoding: .ascii) == "WAVE"
    }
}

private final class WatchTerminalPinnedSessionDelegate: NSObject, URLSessionDelegate, @unchecked Sendable {
    private let expectedFingerprint: String
    private let lock = NSLock()
    private var certificateWasRejected = false

    init(expectedFingerprint: String) {
        self.expectedFingerprint = WatchTerminalConfiguration.normalizeFingerprint(expectedFingerprint)
    }

    var rejectedCertificate: Bool {
        lock.lock()
        defer { lock.unlock() }
        return certificateWasRejected
    }

    func clearRejectedCertificate() {
        lock.lock()
        certificateWasRejected = false
        lock.unlock()
    }

    func urlSession(
        _ session: URLSession,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let leaf = chain.first else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        let digest = SHA256.hash(data: SecCertificateCopyData(leaf) as Data)
        let actual = digest.map { String(format: "%02x", $0) }.joined()
        guard actual == expectedFingerprint else {
            lock.lock()
            certificateWasRejected = true
            lock.unlock()
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
}

/// Shared authenticated and certificate-pinned client used by the foreground
/// Watch terminal and host-only Siri intent. GET failover is permitted before
/// a route is selected; a POST is attempted once on that route and never
/// replayed against another endpoint.
public final class WatchTerminalClient: @unchecked Sendable {
    private let configuration: WatchTerminalConfiguration
    private let delegate: WatchTerminalPinnedSessionDelegate
    private let session: URLSession
    private let speechSession: URLSession
    private let candidateBaseURLs: [URL]
    private let endpointLock = NSLock()
    private var activeBaseURL: URL?

    public convenience init(configuration: WatchTerminalConfiguration) {
        self.init(configuration: configuration, injectedSession: nil, preferredBaseURL: nil)
    }

    public convenience init(configuration: WatchTerminalConfiguration, preferredBaseURL: URL?) {
        self.init(configuration: configuration, injectedSession: nil, preferredBaseURL: preferredBaseURL)
    }

    init(
        configuration: WatchTerminalConfiguration,
        injectedSession: URLSession?,
        preferredBaseURL: URL? = nil
    ) {
        self.configuration = configuration
        self.candidateBaseURLs = configuration.candidateBaseURLs
        if let preferredBaseURL,
           self.candidateBaseURLs.contains(where: { $0.absoluteString == preferredBaseURL.absoluteString }) {
            self.activeBaseURL = preferredBaseURL
        }
        self.delegate = WatchTerminalPinnedSessionDelegate(expectedFingerprint: configuration.certificateSHA256)
        if let injectedSession {
            self.session = injectedSession
            self.speechSession = injectedSession
        } else {
            let sessionConfiguration = URLSessionConfiguration.ephemeral
            sessionConfiguration.timeoutIntervalForRequest = 4
            sessionConfiguration.timeoutIntervalForResource = 6
            sessionConfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
            self.session = URLSession(configuration: sessionConfiguration, delegate: delegate, delegateQueue: nil)

            let speechConfiguration = URLSessionConfiguration.ephemeral
            speechConfiguration.timeoutIntervalForRequest = 180
            speechConfiguration.timeoutIntervalForResource = 180
            speechConfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
            self.speechSession = URLSession(configuration: speechConfiguration, delegate: delegate, delegateQueue: nil)
        }
    }

    public var selectedBaseURL: URL? {
        endpointLock.lock()
        defer { endpointLock.unlock() }
        return activeBaseURL
    }

    public func close() {
        session.invalidateAndCancel()
        if speechSession !== session { speechSession.invalidateAndCancel() }
    }

    @discardableResult
    public func preflight() async throws -> WatchTerminalFrame {
        try await frame(after: 0)
    }

    public func frame(after sequence: Int) async throws -> WatchTerminalFrame {
        guard configuration.isValid, !candidateBaseURLs.isEmpty else {
            throw WatchTerminalClientError.notConfigured
        }
        var observedInvalidResponse = false
        for baseURL in orderedBaseURLs() {
            if Task.isCancelled { throw CancellationError() }
            do {
                var components = try endpointComponents(baseURL: baseURL, path: "v1/terminal/frame")
                components.queryItems = [URLQueryItem(name: "after", value: String(max(0, sequence)))]
                guard let url = components.url else { throw WatchTerminalClientError.notConfigured }
                var request = URLRequest(url: url)
                request.httpMethod = "GET"
                request.timeoutInterval = 4
                authorize(&request)
                let (data, response) = try await session.data(for: request)
                try validate(response: response, data: data)
                let frame: WatchTerminalFrame
                do {
                    frame = try JSONDecoder().decode(WatchTerminalFrame.self, from: data)
                } catch {
                    observedInvalidResponse = true
                    continue
                }
                rememberActive(baseURL)
                delegate.clearRejectedCertificate()
                return frame
            } catch let error as URLError where error.code == .cancelled {
                throw CancellationError()
            } catch is CancellationError {
                throw CancellationError()
            } catch WatchTerminalClientError.certificateRejected {
                continue
            } catch WatchTerminalClientError.invalidResponse {
                observedInvalidResponse = true
            } catch {
                continue
            }
        }
        if delegate.rejectedCertificate { throw WatchTerminalClientError.certificateRejected }
        if observedInvalidResponse { throw WatchTerminalClientError.invalidResponse }
        throw WatchTerminalClientError.offline
    }

    public func historyPage(start: Int, limit: Int = WatchTerminalHistoryPage.maximumRows) async throws -> WatchTerminalHistoryPage {
        guard configuration.isValid, !candidateBaseURLs.isEmpty,
              start >= 0, limit > 0, limit <= WatchTerminalHistoryPage.maximumRows else {
            throw WatchTerminalClientError.invalidResponse
        }
        var observedInvalidResponse = false
        for baseURL in orderedBaseURLs() {
            if Task.isCancelled { throw CancellationError() }
            do {
                var components = try endpointComponents(baseURL: baseURL, path: "v1/terminal/history")
                components.queryItems = [
                    URLQueryItem(name: "start", value: String(start)),
                    URLQueryItem(name: "limit", value: String(limit)),
                ]
                guard let url = components.url else { throw WatchTerminalClientError.notConfigured }
                var request = URLRequest(url: url)
                request.httpMethod = "GET"
                request.timeoutInterval = 6
                authorize(&request)
                let (data, response) = try await session.data(for: request)
                try validate(response: response, data: data)
                let page: WatchTerminalHistoryPage
                do {
                    page = try JSONDecoder().decode(WatchTerminalHistoryPage.self, from: data)
                } catch {
                    observedInvalidResponse = true
                    continue
                }
                guard page.start >= 0, page.lines.count <= limit else {
                    observedInvalidResponse = true
                    continue
                }
                rememberActive(baseURL)
                delegate.clearRejectedCertificate()
                return page
            } catch let error as URLError where error.code == .cancelled {
                throw CancellationError()
            } catch is CancellationError {
                throw CancellationError()
            } catch WatchTerminalClientError.certificateRejected {
                continue
            } catch WatchTerminalClientError.invalidResponse {
                observedInvalidResponse = true
            } catch {
                continue
            }
        }
        if delegate.rejectedCertificate { throw WatchTerminalClientError.certificateRejected }
        if observedInvalidResponse { throw WatchTerminalClientError.invalidResponse }
        throw WatchTerminalClientError.offline
    }

    public func send(_ input: WatchTerminalInput) async throws {
        guard let baseURL = preferredBaseURL() else { throw WatchTerminalClientError.notConnected }
        let components = try endpointComponents(baseURL: baseURL, path: "v1/terminal/input")
        guard let url = components.url else { throw WatchTerminalClientError.notConfigured }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 6
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        authorize(&request)
        request.httpBody = try JSONEncoder().encode(input)
        do {
            let (data, response) = try await session.data(for: request)
            try validate(response: response, data: data)
        } catch let error as WatchTerminalClientError {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            if delegate.rejectedCertificate {
                throw WatchTerminalClientError.certificateRejected
            }
            // The request may have reached terminald. Never retry an ambiguous
            // POST and never select another route after transmission begins.
            throw WatchTerminalClientError.submissionUnconfirmed
        }
    }

    public func speechAudio(responseID: String) async throws -> URL {
        guard responseID.count == 64, responseID.allSatisfy(\.isHexDigit) else {
            throw WatchTerminalClientError.invalidResponse
        }
        guard let baseURL = preferredBaseURL() else { throw WatchTerminalClientError.notConnected }
        let components = try endpointComponents(baseURL: baseURL, path: "v1/terminal/speech")
        guard let url = components.url else { throw WatchTerminalClientError.notConfigured }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 180
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        authorize(&request)
        request.httpBody = try JSONSerialization.data(withJSONObject: ["responseID": responseID])

        let temporaryURL: URL
        let response: URLResponse
        do {
            (temporaryURL, response) = try await speechSession.download(for: request)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            if delegate.rejectedCertificate { throw WatchTerminalClientError.certificateRejected }
            throw WatchTerminalClientError.offline
        }

        guard let http = response as? HTTPURLResponse else {
            throw WatchTerminalClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let data = (try? Data(contentsOf: temporaryURL, options: [.mappedIfSafe])) ?? Data()
            try validate(response: response, data: data)
            throw WatchTerminalClientError.invalidResponse
        }
        guard http.value(forHTTPHeaderField: "Content-Type")?.lowercased().hasPrefix("audio/wav") == true else {
            throw WatchTerminalClientError.invalidAudio
        }
        let values = try temporaryURL.resourceValues(forKeys: [.fileSizeKey])
        guard let fileSize = values.fileSize,
              fileSize > 12,
              fileSize <= WatchTerminalSpeechFileStore.maximumAudioBytes else {
            throw WatchTerminalClientError.invalidAudio
        }
        let handle = try FileHandle(forReadingFrom: temporaryURL)
        defer { try? handle.close() }
        let header = try handle.read(upToCount: 12) ?? Data()
        guard header.count == 12,
              String(data: header.prefix(4), encoding: .ascii) == "RIFF",
              String(data: header.suffix(4), encoding: .ascii) == "WAVE" else {
            throw WatchTerminalClientError.invalidAudio
        }

        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "\(WatchTerminalSpeechFileStore.transientFilePrefix)\(UUID().uuidString)"
            )
            .appendingPathExtension("wav")
        try FileManager.default.moveItem(at: temporaryURL, to: destination)
        return destination
    }

    private func preferredBaseURL() -> URL? {
        endpointLock.lock()
        defer { endpointLock.unlock() }
        return activeBaseURL
    }

    private func orderedBaseURLs() -> [URL] {
        endpointLock.lock()
        let active = activeBaseURL
        endpointLock.unlock()
        guard let active else { return candidateBaseURLs }
        return [active] + candidateBaseURLs.filter { $0 != active }
    }

    private func rememberActive(_ baseURL: URL) {
        endpointLock.lock()
        activeBaseURL = baseURL
        endpointLock.unlock()
    }

    private func endpointComponents(baseURL: URL, path: String) throws -> URLComponents {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: true) else {
            throw WatchTerminalClientError.notConfigured
        }
        return components
    }

    private func authorize(_ request: inout URLRequest) {
        request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw WatchTerminalClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            let message = object?["error"] as? String ?? "Terminal bridge rejected the request."
            throw WatchTerminalClientError.rejected(message)
        }
    }
}

public enum JARVISSpokenPromptError: Error, Equatable, Sendable {
    case empty
    case containsControlCharacters
    case tooLong
}

public enum JARVISSpokenPrompt {
    public static let maximumUTF8Bytes = 3_500

    /// Produces one logical terminal line. CR/LF runs become one space while
    /// every remaining C0/C1 control is rejected before any network access.
    public static func normalize(_ raw: String) throws -> String {
        var output = ""
        var replacingNewlineRun = false
        for scalar in raw.unicodeScalars {
            if scalar.value == 0x0a || scalar.value == 0x0d {
                if !replacingNewlineRun {
                    output.append(" ")
                    replacingNewlineRun = true
                }
                continue
            }
            replacingNewlineRun = false
            if scalar.value <= 0x1f || (0x7f...0x9f).contains(scalar.value) {
                throw JARVISSpokenPromptError.containsControlCharacters
            }
            output.unicodeScalars.append(scalar)
        }
        let normalized = output.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { throw JARVISSpokenPromptError.empty }
        guard normalized.utf8.count <= maximumUTF8Bytes else { throw JARVISSpokenPromptError.tooLong }
        return normalized
    }
}

public struct WatchTerminalSpeechState: Codable, Equatable, Sendable {
    public let available: Bool
    public let generating: Bool
    public let responseID: String

    public init(available: Bool, generating: Bool, responseID: String) {
        self.available = available
        self.generating = generating
        self.responseID = responseID
    }
}

/// Maps the bounded Digital Crown position directly to read-only terminal
/// history. Position zero is the live edge, so the Crown cannot cross it and
/// rebound into a synthetic one-row history offset.
public enum WatchTerminalCrownHistory {
    public static func scrollOffset(crownPosition: Double, maximumOffset: Int) -> Int {
        guard crownPosition.isFinite else { return 0 }
        let safeMaximum = max(0, maximumOffset)
        let bounded = min(Double(safeMaximum), max(0, -crownPosition))
        return Int(bounded.rounded())
    }

    public static func crownPosition(scrollOffset: Int) -> Double {
        -Double(max(0, scrollOffset))
    }
}

public struct WatchTerminalHistoryPage: Codable, Equatable, Sendable {
    public static let maximumRows = 256

    public let paneID: String
    public let historySize: Int
    public let start: Int
    public let lines: [String]
    public let ansiLines: [String]

    enum CodingKeys: String, CodingKey {
        case paneID
        case historySize
        case start
        case lines
        case ansiLines
    }

    public init(
        paneID: String,
        historySize: Int,
        start: Int,
        lines: [String],
        ansiLines: [String]? = nil
    ) {
        self.paneID = paneID
        self.historySize = max(0, historySize)
        self.start = max(0, start)
        self.lines = Array(lines.prefix(Self.maximumRows))
        let styled = ansiLines?.count == lines.count ? ansiLines! : lines
        self.ansiLines = Array(styled.prefix(Self.maximumRows))
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        paneID = try values.decode(String.self, forKey: .paneID)
        historySize = max(0, try values.decode(Int.self, forKey: .historySize))
        start = max(0, try values.decode(Int.self, forKey: .start))
        let decodedLines = try values.decode([String].self, forKey: .lines)
        guard paneID.hasPrefix("%"), start <= historySize,
              decodedLines.count <= Self.maximumRows,
              start + decodedLines.count <= historySize else {
            throw DecodingError.dataCorruptedError(
                forKey: .lines,
                in: values,
                debugDescription: "Terminal history page metadata was invalid."
            )
        }
        lines = decodedLines
        let styled = try values.decodeIfPresent([String].self, forKey: .ansiLines) ?? decodedLines
        ansiLines = styled.count == decodedLines.count ? styled : decodedLines
    }

    public var end: Int { min(historySize, start + lines.count) }

    public func contains(_ range: Range<Int>) -> Bool {
        range.lowerBound >= start && range.upperBound <= end
    }

    public func ansiLines(in range: Range<Int>) -> [String]? {
        guard contains(range) else { return nil }
        let lower = range.lowerBound - start
        let upper = range.upperBound - start
        return Array(ansiLines[lower..<upper])
    }
}

public struct WatchTerminalFrame: Codable, Equatable, Sendable {
    public let sequence: Int
    public let paneID: String
    public let columns: Int
    public let rows: Int
    public let cursorColumn: Int
    public let cursorRow: Int
    public let alternateScreen: Bool
    public let mouseMode: Bool
    public let historySize: Int
    public let speech: WatchTerminalSpeechState?
    public let screenStart: Int
    public let lines: [String]
    public let ansiLines: [String]

    enum CodingKeys: String, CodingKey {
        case sequence
        case paneID
        case columns
        case rows
        case cursorColumn
        case cursorRow
        case alternateScreen
        case mouseMode
        case historySize
        case speech
        case screenStart
        case lines
        case ansiLines
        case capturedLines
        case capturedANSILines
    }

    public init(
        sequence: Int,
        paneID: String = "",
        columns: Int,
        rows: Int,
        cursorColumn: Int,
        cursorRow: Int,
        alternateScreen: Bool,
        mouseMode: Bool,
        historySize: Int,
        speech: WatchTerminalSpeechState? = nil,
        screenStart: Int? = nil,
        lines: [String],
        ansiLines: [String]? = nil
    ) {
        self.sequence = sequence
        self.paneID = paneID
        self.columns = columns
        self.rows = rows
        self.cursorColumn = cursorColumn
        self.cursorRow = cursorRow
        self.alternateScreen = alternateScreen
        self.mouseMode = mouseMode
        self.historySize = historySize
        self.speech = speech
        self.screenStart = min(max(0, screenStart ?? max(0, lines.count - rows)), lines.count)
        self.lines = lines
        self.ansiLines = ansiLines?.count == lines.count ? ansiLines! : lines
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        sequence = try values.decode(Int.self, forKey: .sequence)
        paneID = try values.decodeIfPresent(String.self, forKey: .paneID) ?? ""
        columns = try values.decode(Int.self, forKey: .columns)
        rows = try values.decode(Int.self, forKey: .rows)
        cursorColumn = try values.decode(Int.self, forKey: .cursorColumn)
        cursorRow = try values.decode(Int.self, forKey: .cursorRow)
        alternateScreen = try values.decode(Bool.self, forKey: .alternateScreen)
        mouseMode = try values.decode(Bool.self, forKey: .mouseMode)
        historySize = try values.decode(Int.self, forKey: .historySize)
        speech = try values.decodeIfPresent(WatchTerminalSpeechState.self, forKey: .speech)
        let liveLines = try values.decode([String].self, forKey: .lines)
        let mirroredLines = try values.decodeIfPresent([String].self, forKey: .capturedLines) ?? liveLines
        lines = mirroredLines
        screenStart = min(
            max(
                0,
                try values.decodeIfPresent(Int.self, forKey: .screenStart)
                    ?? max(0, mirroredLines.count - rows)
            ),
            mirroredLines.count
        )
        let liveANSI = try values.decodeIfPresent([String].self, forKey: .ansiLines) ?? liveLines
        let mirroredANSI = try values.decodeIfPresent([String].self, forKey: .capturedANSILines) ?? liveANSI
        ansiLines = mirroredANSI.count == mirroredLines.count ? mirroredANSI : mirroredLines
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(sequence, forKey: .sequence)
        try values.encode(paneID, forKey: .paneID)
        try values.encode(columns, forKey: .columns)
        try values.encode(rows, forKey: .rows)
        try values.encode(cursorColumn, forKey: .cursorColumn)
        try values.encode(cursorRow, forKey: .cursorRow)
        try values.encode(alternateScreen, forKey: .alternateScreen)
        try values.encode(mouseMode, forKey: .mouseMode)
        try values.encode(historySize, forKey: .historySize)
        try values.encodeIfPresent(speech, forKey: .speech)
        try values.encode(screenStart, forKey: .screenStart)
        try values.encode(lines, forKey: .lines)
        try values.encode(ansiLines, forKey: .ansiLines)
    }

    public var liveCursorLineIndex: Int {
        guard !lines.isEmpty else { return 0 }
        return min(max(0, screenStart + cursorRow), lines.count - 1)
    }

    /// Absolute index of the first locally captured row in tmux's combined
    /// history-plus-screen coordinate space.
    public var capturedAbsoluteStart: Int {
        max(0, historySize - screenStart)
    }

    /// The current Pi editor is bounded by full-width divider rows. This live
    /// block stays unwrapped in a clipped, cursor-following viewport; output
    /// above it can wrap locally without resizing the authoritative PTY.
    public var liveEditorRange: Range<Int>? {
        guard !lines.isEmpty else { return nil }
        let screenEnd = min(lines.count, screenStart + max(0, rows))
        let cursor = liveCursorLineIndex
        guard cursor >= screenStart, cursor < screenEnd else { return nil }

        let upperSearchStart = max(screenStart, cursor - 8)
        let lowerSearchEnd = min(screenEnd, cursor + 10)
        let upper = stride(from: cursor - 1, through: upperSearchStart, by: -1).first {
            Self.isEditorDivider(lines[$0], terminalColumns: columns)
        }
        let lower = (cursor + 1..<lowerSearchEnd).first {
            Self.isEditorDivider(lines[$0], terminalColumns: columns)
        }
        guard let upper, let lower, upper < cursor, cursor < lower else { return nil }
        // Include the lower divider plus Pi's path and token/model footer rows.
        return upper..<min(screenEnd, lower + 3)
    }

    public var liveOutputEndIndex: Int {
        if let editor = liveEditorRange { return editor.lowerBound }
        return max(0, min(lines.count, liveCursorLineIndex))
    }

    public var absoluteOutputEnd: Int {
        capturedAbsoluteStart + liveOutputEndIndex
    }

    public func maximumOutputScrollOffset(maximumSourceRows: Int) -> Int {
        max(0, absoluteOutputEnd - max(1, maximumSourceRows))
    }

    public func localANSILines(inAbsoluteRange range: Range<Int>) -> [String]? {
        let localStart = range.lowerBound - capturedAbsoluteStart
        let localEnd = range.upperBound - capturedAbsoluteStart
        guard localStart >= 0, localEnd <= ansiLines.count, localStart <= localEnd else { return nil }
        return Array(ansiLines[localStart..<localEnd])
    }

    private static func isEditorDivider(_ line: String, terminalColumns: Int) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        let minimumLength = max(12, min(terminalColumns / 2, 24))
        guard trimmed.count >= minimumLength else { return false }
        let dividers = CharacterSet(charactersIn: "-_=~─━═")
        return trimmed.unicodeScalars.allSatisfy { dividers.contains($0) }
    }

    /// Exact captured grid rows around the live Pi view, offset toward tmux
    /// history by the Digital Crown. Scrolling is local and read-only: no mouse
    /// sequence or terminal input is emitted.
    public func viewportRange(maximumLines: Int, scrollOffset: Int = 0) -> Range<Int> {
        guard maximumLines > 0, !lines.isEmpty else { return 0..<0 }
        let lastContent = (lines.lastIndex { !$0.trimmingCharacters(in: .whitespaces).isEmpty } ?? liveCursorLineIndex) + 1
        let liveEnd = min(lines.count, max(liveCursorLineIndex + 2, lastContent))
        let visibleCapacity = min(maximumLines, liveEnd)
        let maximumOffset = max(0, liveEnd - visibleCapacity)
        let safeOffset = min(max(0, scrollOffset), maximumOffset)
        let end = liveEnd - safeOffset
        let start = max(0, end - maximumLines)
        return start..<end
    }

    public func maximumScrollOffset(maximumLines: Int) -> Int {
        guard maximumLines > 0, !lines.isEmpty else { return 0 }
        let range = viewportRange(maximumLines: maximumLines, scrollOffset: 0)
        return max(0, range.upperBound - maximumLines)
    }

    public func visibleLines(maximumLines: Int, scrollOffset: Int = 0) -> [String] {
        let range = viewportRange(maximumLines: maximumLines, scrollOffset: scrollOffset)
        return Array(lines[range])
    }

    public func visibleANSILines(maximumLines: Int, scrollOffset: Int = 0) -> [String] {
        let range = viewportRange(maximumLines: maximumLines, scrollOffset: scrollOffset)
        return Array(ansiLines[range])
    }

    public func visibleText(maximumLines: Int) -> String {
        visibleLines(maximumLines: maximumLines).joined(separator: "\n")
    }

    /// Compatibility helper retained for tests and narrow non-styled surfaces.
    public func readableOutputLines(displayColumns: Int, maximumLines: Int) -> [String] {
        guard maximumLines > 0, !lines.isEmpty else { return [] }
        var source = Array(lines[..<min(lines.count, liveCursorLineIndex + 2)])
        if liveCursorLineIndex < source.count { source.remove(at: liveCursorLineIndex) }
        let wrapped = source.flatMap {
            WatchTerminalLayout.wrapTerminalLine($0, displayColumns: displayColumns)
        }
        guard wrapped.count > maximumLines else { return wrapped }
        return Array(wrapped.suffix(maximumLines))
    }

    /// Keeps the current Pi editor row readable and follows the cursor when a
    /// command is wider than the Watch. The block is a native Watch cursor;
    /// tmux capture styling is rendered in the mirrored grid above it.
    public func promptViewport(displayColumns: Int) -> String {
        guard !lines.isEmpty, displayColumns > 0 else { return "▌" }
        var characters = Array(WatchTerminalLayout.trimmingTrailingWhitespace(lines[liveCursorLineIndex]))
        let safeCursorColumn = max(0, cursorColumn)
        if characters.count < safeCursorColumn {
            characters.append(contentsOf: repeatElement(" ", count: safeCursorColumn - characters.count))
        }
        characters.insert("▌", at: min(safeCursorColumn, characters.count))

        guard characters.count > displayColumns else { return String(characters) }
        let preferredStart = safeCursorColumn < displayColumns
            ? 0
            : max(0, safeCursorColumn - displayColumns + 4)
        let start = min(preferredStart, characters.count - displayColumns)
        return String(characters[start..<(start + displayColumns)])
    }
}

public struct WatchTerminalRGBColor: Equatable, Sendable {
    public let red: Int
    public let green: Int
    public let blue: Int

    public init(red: Int, green: Int, blue: Int) {
        self.red = min(255, max(0, red))
        self.green = min(255, max(0, green))
        self.blue = min(255, max(0, blue))
    }
}

public enum WatchTerminalANSIColor: Equatable, Sendable {
    case `default`
    case rgb(WatchTerminalRGBColor)
}

public struct WatchTerminalANSIStyle: Equatable, Sendable {
    public var foreground: WatchTerminalANSIColor = .default
    public var background: WatchTerminalANSIColor = .default
    public var bold = false
    public var dim = false
    public var italic = false
    public var underline = false
    public var inverse = false
    public var hidden = false
    public var strikethrough = false

    public init() {}
}

public struct WatchTerminalANSISpan: Equatable, Sendable {
    public let text: String
    public let style: WatchTerminalANSIStyle

    public init(text: String, style: WatchTerminalANSIStyle) {
        self.text = text
        self.style = style
    }
}

/// Decodes only terminal SGR presentation emitted by `tmux capture-pane -e`.
/// It does not infer Pi concepts: thinking, tool calls, usage, and assistant
/// output arrive as ordinary styled terminal cells and are mirrored verbatim.
public enum WatchTerminalANSIParser {
    public static func parse(lines: [String]) -> [[WatchTerminalANSISpan]] {
        var style = WatchTerminalANSIStyle()
        return lines.map { line in
            var spans: [WatchTerminalANSISpan] = []
            var buffer = ""
            var index = line.startIndex

            func flush() {
                guard !buffer.isEmpty else { return }
                spans.append(WatchTerminalANSISpan(text: buffer, style: style))
                buffer.removeAll(keepingCapacity: true)
            }

            while index < line.endIndex {
                if line[index] == "\u{1b}" {
                    let bracket = line.index(after: index)
                    let parametersStart = bracket < line.endIndex ? line.index(after: bracket) : line.endIndex
                    if bracket < line.endIndex, line[bracket] == "[",
                       let final = line[parametersStart...].firstIndex(where: { character in
                           character.unicodeScalars.count == 1
                               && (0x40...0x7e).contains(character.unicodeScalars.first!.value)
                       }) {
                        flush()
                        if line[final] == "m" {
                            applySGR(String(line[parametersStart..<final]), to: &style)
                        }
                        index = line.index(after: final)
                        continue
                    }
                }
                buffer.append(line[index])
                index = line.index(after: index)
            }
            flush()
            return spans
        }
    }

    /// Wraps styled terminal rows for the Watch output surface without changing
    /// the PTY grid. Default trailing padding is discarded, ANSI backgrounds
    /// are retained, and adjacent characters with the same style are coalesced.
    public static func wrapped(
        lines: [[WatchTerminalANSISpan]],
        displayColumns: Int
    ) -> [[WatchTerminalANSISpan]] {
        lines.flatMap { wrapped(line: $0, displayColumns: displayColumns) }
    }

    public static func wrapped(
        line: [WatchTerminalANSISpan],
        displayColumns: Int
    ) -> [[WatchTerminalANSISpan]] {
        struct Cell {
            let character: Character
            let style: WatchTerminalANSIStyle
        }

        let columns = max(1, displayColumns)
        var cells = line.flatMap { span in
            span.text.map { Cell(character: $0, style: span.style) }
        }
        while let last = cells.last,
              last.character.isWhitespace,
              last.style.background == .default,
              !last.style.inverse {
            cells.removeLast()
        }
        guard !cells.isEmpty else { return [[]] }

        let dividerCharacters = CharacterSet(charactersIn: "-_=~─━═")
        if cells.count > columns,
           cells.allSatisfy({ cell in
               cell.character.unicodeScalars.allSatisfy { dividerCharacters.contains($0) }
           }) {
            cells = Array(cells.prefix(columns))
        }

        func spans(from slice: ArraySlice<Cell>) -> [WatchTerminalANSISpan] {
            var output: [WatchTerminalANSISpan] = []
            var text = ""
            var style: WatchTerminalANSIStyle?
            for cell in slice {
                if let style, style != cell.style {
                    output.append(WatchTerminalANSISpan(text: text, style: style))
                    text = ""
                }
                style = cell.style
                text.append(cell.character)
            }
            if let style, !text.isEmpty {
                output.append(WatchTerminalANSISpan(text: text, style: style))
            }
            return output
        }

        var output: [[WatchTerminalANSISpan]] = []
        while cells.count > columns {
            let candidate = cells.prefix(columns)
            let lowerBound = max(1, columns / 2)
            let breakIndex = candidate.indices.reversed().first { index in
                index >= lowerBound
                    && candidate[index].character.isWhitespace
                    && candidate[index].style.background == .default
                    && !candidate[index].style.inverse
            }
            if let breakIndex {
                output.append(spans(from: cells[..<breakIndex]))
                cells.removeFirst(breakIndex + 1)
                while let first = cells.first,
                      first.character.isWhitespace,
                      first.style.background == .default,
                      !first.style.inverse {
                    cells.removeFirst()
                }
            } else {
                output.append(spans(from: cells.prefix(columns)))
                cells.removeFirst(columns)
            }
        }
        output.append(spans(from: cells[...]))
        return output
    }

    /// Returns one unwrapped styled cell window. The Watch editor uses this to
    /// keep the cursor visible at the same font as output without a horizontal
    /// gesture or any change to the 48-column PTY.
    public static func viewport(
        line: [WatchTerminalANSISpan],
        start: Int,
        columns: Int
    ) -> [WatchTerminalANSISpan] {
        struct Cell {
            let character: Character
            let style: WatchTerminalANSIStyle
        }
        let cells = line.flatMap { span in
            span.text.map { Cell(character: $0, style: span.style) }
        }
        let safeStart = min(cells.count, max(0, start))
        let end = min(cells.count, safeStart + max(1, columns))
        guard safeStart < end else { return [] }
        var output: [WatchTerminalANSISpan] = []
        var text = ""
        var style: WatchTerminalANSIStyle?
        for cell in cells[safeStart..<end] {
            if let style, style != cell.style {
                output.append(WatchTerminalANSISpan(text: text, style: style))
                text = ""
            }
            style = cell.style
            text.append(cell.character)
        }
        if let style, !text.isEmpty {
            output.append(WatchTerminalANSISpan(text: text, style: style))
        }
        return output
    }

    private static func applySGR(_ raw: String, to style: inout WatchTerminalANSIStyle) {
        let values = raw.isEmpty
            ? [0]
            : raw.replacingOccurrences(of: ":", with: ";").split(separator: ";", omittingEmptySubsequences: false).map {
                Int($0) ?? 0
            }
        var index = 0
        while index < values.count {
            let value = values[index]
            switch value {
            case 0: style = WatchTerminalANSIStyle()
            case 1: style.bold = true
            case 2: style.dim = true
            case 3: style.italic = true
            case 4: style.underline = true
            case 7: style.inverse = true
            case 8: style.hidden = true
            case 9: style.strikethrough = true
            case 22:
                style.bold = false
                style.dim = false
            case 23: style.italic = false
            case 24: style.underline = false
            case 27: style.inverse = false
            case 28: style.hidden = false
            case 29: style.strikethrough = false
            case 30...37:
                style.foreground = indexedColor(value - 30)
            case 38:
                if let (color, consumed) = extendedColor(values, startingAt: index + 1) {
                    style.foreground = color
                    index += consumed
                }
            case 39: style.foreground = .default
            case 40...47:
                style.background = indexedColor(value - 40)
            case 48:
                if let (color, consumed) = extendedColor(values, startingAt: index + 1) {
                    style.background = color
                    index += consumed
                }
            case 49: style.background = .default
            case 90...97:
                style.foreground = indexedColor(value - 90 + 8)
            case 100...107:
                style.background = indexedColor(value - 100 + 8)
            default: break
            }
            index += 1
        }
    }

    private static func extendedColor(_ values: [Int], startingAt index: Int) -> (WatchTerminalANSIColor, Int)? {
        guard index < values.count else { return nil }
        if values[index] == 2, index + 3 < values.count {
            return (
                .rgb(WatchTerminalRGBColor(red: values[index + 1], green: values[index + 2], blue: values[index + 3])),
                4
            )
        }
        if values[index] == 5, index + 1 < values.count {
            return (indexedColor(values[index + 1]), 2)
        }
        return nil
    }

    private static func indexedColor(_ raw: Int) -> WatchTerminalANSIColor {
        let index = min(255, max(0, raw))
        let standard = [
            (0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16),
            (36, 114, 200), (188, 63, 188), (17, 168, 205), (229, 229, 229),
            (102, 102, 102), (241, 76, 76), (35, 209, 139), (245, 245, 67),
            (59, 142, 234), (214, 112, 214), (41, 184, 219), (255, 255, 255),
        ]
        if index < standard.count {
            let value = standard[index]
            return .rgb(WatchTerminalRGBColor(red: value.0, green: value.1, blue: value.2))
        }
        if index <= 231 {
            let cube = index - 16
            let levels = [0, 95, 135, 175, 215, 255]
            return .rgb(WatchTerminalRGBColor(
                red: levels[cube / 36],
                green: levels[(cube / 6) % 6],
                blue: levels[cube % 6]
            ))
        }
        let gray = 8 + (index - 232) * 10
        return .rgb(WatchTerminalRGBColor(red: gray, green: gray, blue: gray))
    }
}

public enum WatchTerminalLayout {
    public static let readableFontSize = 11.0
    public static let rawFontSize = 9.0
    public static let minimumMirrorFontSize = 5.5
    public static let maximumMirrorFontSize = 8.0
    public static let promptFontSize = 10.5
    public static let monospacedCharacterWidthRatio = 0.61
    public static let lineHeightRatio = 1.24
    public static let minimumReadableColumns = 20
    public static let maximumReadableColumns = 36
    public static let minimumForegroundLuminance = 188

    /// Raises dark ANSI foregrounds for the small OLED display while retaining
    /// their hue relationships. True black stays black for inverse cells.
    public static func brightenedForeground(_ color: WatchTerminalRGBColor) -> WatchTerminalRGBColor {
        guard max(color.red, max(color.green, color.blue)) > 0 else { return color }
        let luminance = (299 * color.red + 587 * color.green + 114 * color.blue) / 1_000
        guard luminance < minimumForegroundLuminance else { return color }
        let lift = minimumForegroundLuminance - luminance
        return WatchTerminalRGBColor(
            red: color.red + lift,
            green: color.green + lift,
            blue: color.blue + lift
        )
    }

    public static func displayColumns(availableWidth: Double, fontSize: Double = readableFontSize) -> Int {
        guard availableWidth > 0, fontSize > 0 else { return minimumReadableColumns }
        let fitted = Int(availableWidth / fontSize / monospacedCharacterWidthRatio)
        return min(maximumReadableColumns, max(minimumReadableColumns, fitted))
    }

    public static func mirrorFontSize(availableWidth: Double, terminalColumns: Int) -> Double {
        guard availableWidth > 0, terminalColumns > 0 else { return minimumMirrorFontSize }
        let fitted = availableWidth / Double(terminalColumns) / monospacedCharacterWidthRatio
        return min(maximumMirrorFontSize, max(minimumMirrorFontSize, fitted))
    }

    /// Legacy readable wrapping helper retained for compatibility tests. The
    /// Watch UI now renders exact ANSI grid cells rather than reconstructing Pi.
    public static func wrapTerminalLine(_ line: String, displayColumns: Int) -> [String] {
        let columns = max(1, displayColumns)
        let trimmed = trimmingTrailingWhitespace(line)
        guard !trimmed.isEmpty else { return [""] }
        var remaining = Array(trimmed)

        let dividerCharacters = CharacterSet(charactersIn: "-_=~─━═")
        if remaining.count > columns,
           remaining.allSatisfy({ character in
               character.unicodeScalars.allSatisfy { dividerCharacters.contains($0) }
           }) {
            return [String(remaining.prefix(columns))]
        }

        var wrapped: [String] = []
        while remaining.count > columns {
            let candidate = Array(remaining.prefix(columns))
            let lowerBound = max(1, columns / 2)
            let breakIndex = candidate.indices.reversed().first {
                $0 >= lowerBound && candidate[$0].isWhitespace
            }
            if let breakIndex {
                wrapped.append(String(candidate[..<breakIndex]))
                remaining.removeFirst(breakIndex + 1)
                while remaining.first?.isWhitespace == true { remaining.removeFirst() }
            } else {
                wrapped.append(String(candidate))
                remaining.removeFirst(columns)
            }
        }
        wrapped.append(String(remaining))
        return wrapped
    }

    public static func trimmingTrailingWhitespace(_ line: String) -> String {
        var value = line
        while let last = value.last, last.isWhitespace {
            value.removeLast()
        }
        return value
    }

    public static func lineHeight(fontSize: Double) -> Double {
        fontSize * lineHeightRatio
    }
}

public struct WatchTerminalInput: Codable, Equatable, Sendable {
    public let requestID: String
    public let dataBase64: String
    public let appendReturn: Bool

    public init(requestID: String = UUID().uuidString, data: Data, appendReturn: Bool) {
        self.requestID = requestID
        self.dataBase64 = data.base64EncodedString()
        self.appendReturn = appendReturn
    }

    public var data: Data? { Data(base64Encoded: dataBase64) }
}

public enum WatchTerminalKeyBytes {
    public static let escape = Data([0x1b])
    public static let tab = Data([0x09])
    public static let carriageReturn = Data([0x0d])
    public static let backspace = Data([0x7f])
    public static let slash = Data([0x2f])
    public static let up = Data([0x1b, 0x5b, 0x41])
    public static let down = Data([0x1b, 0x5b, 0x42])

    public static func control(_ byte: UInt8) -> Data? {
        guard byte >= 0x40, byte <= 0x7f else { return nil }
        return Data([byte & 0x1f])
    }

    public static func wheel(scrollingUp: Bool, column: Int, row: Int) -> Data {
        let button = scrollingUp ? 64 : 65
        return Data("\u{1b}[<\(button);\(max(1, column));\(max(1, row))M".utf8)
    }
}
