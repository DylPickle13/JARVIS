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

    public var errorDescription: String? {
        switch self {
        case .notConfigured: return "The terminal is not configured."
        case .invalidResponse: return "The terminal bridge returned an invalid response."
        case .rejected(let message): return message
        case .certificateRejected: return "The terminal identity did not match."
        case .offline: return "The terminal is offline."
        case .notConnected: return "No authenticated terminal route is selected."
        case .submissionUnconfirmed: return "Terminal submission was not confirmed."
        }
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
    private let candidateBaseURLs: [URL]
    private let endpointLock = NSLock()
    private var activeBaseURL: URL?

    public convenience init(configuration: WatchTerminalConfiguration) {
        self.init(configuration: configuration, injectedSession: nil)
    }

    init(configuration: WatchTerminalConfiguration, injectedSession: URLSession?) {
        self.configuration = configuration
        self.candidateBaseURLs = configuration.candidateBaseURLs
        self.delegate = WatchTerminalPinnedSessionDelegate(expectedFingerprint: configuration.certificateSHA256)
        if let injectedSession {
            self.session = injectedSession
        } else {
            let sessionConfiguration = URLSessionConfiguration.ephemeral
            sessionConfiguration.timeoutIntervalForRequest = 4
            sessionConfiguration.timeoutIntervalForResource = 6
            sessionConfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
            self.session = URLSession(configuration: sessionConfiguration, delegate: delegate, delegateQueue: nil)
        }
    }

    public func close() {
        session.invalidateAndCancel()
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

public struct WatchTerminalFrame: Codable, Equatable, Sendable {
    public let sequence: Int
    public let columns: Int
    public let rows: Int
    public let cursorColumn: Int
    public let cursorRow: Int
    public let alternateScreen: Bool
    public let mouseMode: Bool
    public let historySize: Int
    public let screenStart: Int
    public let lines: [String]
    public let ansiLines: [String]

    enum CodingKeys: String, CodingKey {
        case sequence
        case columns
        case rows
        case cursorColumn
        case cursorRow
        case alternateScreen
        case mouseMode
        case historySize
        case screenStart
        case lines
        case ansiLines
        case capturedLines
        case capturedANSILines
    }

    public init(
        sequence: Int,
        columns: Int,
        rows: Int,
        cursorColumn: Int,
        cursorRow: Int,
        alternateScreen: Bool,
        mouseMode: Bool,
        historySize: Int,
        screenStart: Int? = nil,
        lines: [String],
        ansiLines: [String]? = nil
    ) {
        self.sequence = sequence
        self.columns = columns
        self.rows = rows
        self.cursorColumn = cursorColumn
        self.cursorRow = cursorRow
        self.alternateScreen = alternateScreen
        self.mouseMode = mouseMode
        self.historySize = historySize
        self.screenStart = min(max(0, screenStart ?? max(0, lines.count - rows)), lines.count)
        self.lines = lines
        self.ansiLines = ansiLines?.count == lines.count ? ansiLines! : lines
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        sequence = try values.decode(Int.self, forKey: .sequence)
        columns = try values.decode(Int.self, forKey: .columns)
        rows = try values.decode(Int.self, forKey: .rows)
        cursorColumn = try values.decode(Int.self, forKey: .cursorColumn)
        cursorRow = try values.decode(Int.self, forKey: .cursorRow)
        alternateScreen = try values.decode(Bool.self, forKey: .alternateScreen)
        mouseMode = try values.decode(Bool.self, forKey: .mouseMode)
        historySize = try values.decode(Int.self, forKey: .historySize)
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
        try values.encode(columns, forKey: .columns)
        try values.encode(rows, forKey: .rows)
        try values.encode(cursorColumn, forKey: .cursorColumn)
        try values.encode(cursorRow, forKey: .cursorRow)
        try values.encode(alternateScreen, forKey: .alternateScreen)
        try values.encode(mouseMode, forKey: .mouseMode)
        try values.encode(historySize, forKey: .historySize)
        try values.encode(screenStart, forKey: .screenStart)
        try values.encode(lines, forKey: .lines)
        try values.encode(ansiLines, forKey: .ansiLines)
    }

    public var liveCursorLineIndex: Int {
        guard !lines.isEmpty else { return 0 }
        return min(max(0, screenStart + cursorRow), lines.count - 1)
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
