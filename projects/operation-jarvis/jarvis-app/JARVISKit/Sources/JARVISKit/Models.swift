import Foundation

// Shared connection lifecycle state (used by both the iOS and watch apps).
public enum ConnectionState: Equatable {
    case idle        // nothing attempted yet
    case connecting
    case connected
    case failed
}

// Codable DTOs mirroring the jarvisd JSON contract (see jarvisd.py).
// All fields that jarvisd may omit or null out are optional.

// MARK: - Health

public struct HealthResponse: Codable, Equatable {
    public let ok: Bool
    public let version: String?
    public let uptimeSeconds: Double?
}

// MARK: - State snapshot

public struct StateSnapshot: Codable, Equatable {
    public let ok: Bool
    public let generatedAt: String?
    public let version: String?
    public let uptimeSeconds: Double?
    public let summary: Summary?
    public let subsystems: Subsystems?
}

public struct Summary: Codable, Equatable {
    public let plugsOn: Int?
    public let plugsTotal: Int?
    public let purifierOn: Bool?
    public let pm25: Int?
    public let piActive: Int?
}

public struct Subsystems: Codable, Equatable {
    public let plugs: PlugsSubsystem?
    public let purifier: PurifierSubsystem?
    public let pi: PiSubsystem?
    public let weather: WeatherSubsystem?
    public let services: ServicesSubsystem?
    public let network: NetworkSubsystem?
}

public struct PlugsSubsystem: Codable, Equatable {
    public let ok: Bool?
    public let count: Int?
    public let onCount: Int?
    public let plugs: [String: PlugState]?
    public let error: String?
}

public struct PlugState: Codable, Equatable {
    public let ok: Bool?
    public let isOn: Bool?
    public let host: String?
    public let rssi: Int?
    public let alias: String?
}

public struct PurifierSubsystem: Codable, Equatable {
    public let ok: Bool?
    public let isOn: Bool?
    public let power: String?
    public let mode: String?
    public let fanLevel: Int?
    public let fanSetLevel: Int?
    public let pm25: Int?
    public let airQualityLevel: Int?
    public let filterLife: Int?
    public let childLock: Bool?
    public let display: String?
    public let timer: String?
    public let name: String?
    public let model: String?
    public let error: String?
}

public struct PiSubsystem: Codable, Equatable {
    public let ok: Bool?
    public let active: Int?
    public let localActive: Int?
    public let localTotal: Int?
    public let rpcActive: Int?
}

public struct WeatherSubsystem: Codable, Equatable {
    public let ok: Bool?
    public let location: String?
    public let temperatureC: Double?
    public let feelsLikeC: Double?
    public let humidityPercent: Int?
    public let windKph: Double?
    public let weatherCode: Int?
    public let at: String?
    public let error: String?
}

public struct ServicesSubsystem: Codable, Equatable {
    public let ok: Bool?
    public let label: String?
    public let running: Bool?
    public let pid: Int?
    public let description: String?
    public let error: String?
}

public struct NetworkSubsystem: Codable, Equatable {
    public let ok: Bool?
    public let macLanIp: String?
    public let tailscaleIp: String?
}

// MARK: - Events

public struct EventItem: Codable, Equatable, Identifiable {
    public var id: Int { seq }
    public let seq: Int
    public let receivedAt: String?
    public let source: String?
    public let eventType: String?
    public let action: String?
    public let ok: Bool?
    public let summary: String?
    public let error: String?
    public let at: String?
}

public struct EventsResponse: Codable, Equatable {
    public let ok: Bool
    public let count: Int
    public let events: [EventItem]
}

// MARK: - Commands

public struct CommandRequest: Codable {
    public let action: String
    public let params: [String: JSONValue]?
}

public struct CommandResult: Codable, Equatable {
    public let ok: Bool
    public let action: String?
    public let error: String?
    // Plug-specific passthrough.
    public let plug: PlugCommandData?
    // Purifier-specific passthrough.
    public let airPurifier: PurifierCommandData?
    public let summary: String?
}

public struct PlugCommandData: Codable, Equatable {
    public let name: String?
    public let is_on: Bool?
    public let host: String?
    public let rssi: Int?
    public let alias: String?
}

public struct PurifierCommandData: Codable, Equatable {
    public let ok: Bool?
    public let data: [String: JSONValue]?
}

// MARK: - Services control

public struct ServiceActionResult: Codable, Equatable {
    public let ok: Bool
    public let service: String?
    public let action: String?
    public let label: String?
    public let running: Bool?
    public let pid: Int?
    public let description: String?
    public let returncode: Int?
    public let stderr: String?
    public let error: String?
    public let known: [String]?
}

public struct ServicesListResponse: Codable, Equatable {
    public let ok: Bool
    public let services: [String: ServiceActionResult]
}

// MARK: - Flexible JSON value

/// A JSON value that can decode to object/array/string/number/bool/null.
/// Used for command params and purifier data passthrough.
public enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let b = try? container.decode(Bool.self) { self = .bool(b) }
        else if let i = try? container.decode(Int.self) { self = .number(Double(i)) }
        else if let d = try? container.decode(Double.self) { self = .number(d) }
        else if let s = try? container.decode(String.self) { self = .string(s) }
        else if let a = try? container.decode([JSONValue].self) { self = .array(a) }
        else if let o = try? container.decode([String: JSONValue].self) { self = .object(o) }
        else { self = .null }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let s): try container.encode(s)
        case .number(let n): try container.encode(n)
        case .bool(let b): try container.encode(b)
        case .object(let o): try container.encode(o)
        case .array(let a): try container.encode(a)
        case .null: try container.encodeNil()
        }
    }

    public var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }
    public var intValue: Int? {
        if case .number(let n) = self { return Int(n) }
        return nil
    }
    public var boolValue: Bool? {
        if case .bool(let b) = self { return b }
        return nil
    }
}
