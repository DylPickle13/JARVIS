import Foundation

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

public struct WatchTerminalFrame: Codable, Equatable, Sendable {
    public let sequence: Int
    public let columns: Int
    public let rows: Int
    public let cursorColumn: Int
    public let cursorRow: Int
    public let alternateScreen: Bool
    public let mouseMode: Bool
    public let historySize: Int
    public let lines: [String]

    public init(
        sequence: Int,
        columns: Int,
        rows: Int,
        cursorColumn: Int,
        cursorRow: Int,
        alternateScreen: Bool,
        mouseMode: Bool,
        historySize: Int,
        lines: [String]
    ) {
        self.sequence = sequence
        self.columns = columns
        self.rows = rows
        self.cursorColumn = cursorColumn
        self.cursorRow = cursorRow
        self.alternateScreen = alternateScreen
        self.mouseMode = mouseMode
        self.historySize = historySize
        self.lines = lines
    }

    public func visibleLines(maximumLines: Int) -> [String] {
        guard maximumLines > 0, lines.count > maximumLines else { return lines }
        let preferredStart = cursorRow - maximumLines + 2
        let start = min(max(0, preferredStart), lines.count - maximumLines)
        return Array(lines[start..<(start + maximumLines)])
    }

    public func visibleText(maximumLines: Int) -> String {
        visibleLines(maximumLines: maximumLines).joined(separator: "\n")
    }
}

public enum WatchTerminalLayout {
    public static let maximumFontSize = 6.8
    public static let minimumFontSize = 4.8
    public static let monospacedCharacterWidthRatio = 0.61
    public static let lineHeightRatio = 1.22

    /// Fits one tmux row onto one Watch display row. The renderer also applies
    /// a one-line limit and clipping so a long pane row can never soft-wrap.
    public static func fontSize(columns: Int, availableWidth: Double) -> Double {
        guard columns > 0, availableWidth > 0 else { return maximumFontSize }
        let fitted = availableWidth / Double(columns) / monospacedCharacterWidthRatio
        return min(maximumFontSize, max(minimumFontSize, fitted))
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
