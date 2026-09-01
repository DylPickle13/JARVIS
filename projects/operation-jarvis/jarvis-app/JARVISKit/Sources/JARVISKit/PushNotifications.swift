import Foundation

public enum JARVISPushPlatform: String, Codable, CaseIterable, Sendable {
    case iphone
    case watch

    public var topic: String {
        switch self {
        case .iphone: return "com.operation-jarvis.jarvis"
        case .watch: return "com.operation-jarvis.jarvis.watchkitapp"
        }
    }
}

public enum JARVISPushEnvironment: String, Codable, Sendable {
    case development
    case production
}

public enum JARVISPushRegistrationAction: String, Codable, Sendable {
    case register
    case deactivate
}

/// Strict token-registration envelope. Tokens are carried only through the
/// immediate WatchConnectivity relay and one fixed host-key-pinned SSH child.
public struct JARVISPushRegistration: Codable, Equatable, Sendable {
    public static let protocolVersion = 1

    public let protocolVersion: Int
    public let action: JARVISPushRegistrationAction
    public let platform: JARVISPushPlatform
    public let environment: JARVISPushEnvironment
    public let installationID: String
    public let deviceToken: String?

    public init?(
        action: JARVISPushRegistrationAction,
        platform: JARVISPushPlatform,
        environment: JARVISPushEnvironment,
        installationID: String,
        deviceToken: String?
    ) {
        guard let identifier = UUID(uuidString: installationID) else { return nil }
        let normalizedID = identifier.uuidString.lowercased()
        let normalizedToken = deviceToken?.lowercased()
        switch action {
        case .register:
            guard let normalizedToken,
                  (64...200).contains(normalizedToken.utf8.count),
                  Self.isASCIIHex(normalizedToken) else { return nil }
        case .deactivate:
            guard normalizedToken == nil else { return nil }
        }
        self.protocolVersion = Self.protocolVersion
        self.action = action
        self.platform = platform
        self.environment = environment
        self.installationID = normalizedID
        self.deviceToken = normalizedToken
    }

    public var isValid: Bool {
        guard protocolVersion == Self.protocolVersion,
              UUID(uuidString: installationID) != nil else { return false }
        switch action {
        case .register:
            guard let deviceToken else { return false }
            return (64...200).contains(deviceToken.utf8.count)
                && Self.isASCIIHex(deviceToken)
        case .deactivate:
            return deviceToken == nil
        }
    }

    private static func isASCIIHex(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.allSatisfy { byte in
            (48...57).contains(byte) || (65...70).contains(byte) || (97...102).contains(byte)
        }
    }
}

public struct JARVISPushRegistrationAcknowledgement: Codable, Equatable, Sendable {
    public let ok: Bool
    public let protocolVersion: Int?
    public let platform: String?
    public let active: Bool?
    public let changed: Bool?
    public let tokenFingerprint: String?
    public let registeredAt: String?
    public let error: String?
}

public struct JARVISNotificationDeviceStatus: Codable, Equatable, Sendable {
    public let registered: Bool
    public let registeredAt: String?
    public let lastAcceptedAt: String?
}

public struct JARVISNotificationDevicesStatus: Codable, Equatable, Sendable {
    public let iphone: JARVISNotificationDeviceStatus
    public let watch: JARVISNotificationDeviceStatus
}

public struct JARVISNotificationStatus: Codable, Equatable, Sendable {
    public let ok: Bool
    public let providerConfigured: Bool
    public let dispatchEnabled: Bool
    public let environment: String?
    public let devices: JARVISNotificationDevicesStatus
    public let pendingCount: Int
    public let failedCount: Int
    public let ambiguousCount: Int
    public let lastOutcome: String?
    public let lastAttemptAt: String?
    public let lastAcceptedAt: String?
    public let error: String?
}

public enum JARVISNotificationLocalState: String, Equatable, Sendable {
    case off
    case needsPermission
    case registering
    case pendingSecureUpload
    case active
    case denied
    case error

    public var title: String {
        switch self {
        case .off: return "Off"
        case .needsPermission: return "Needs permission"
        case .registering: return "Registering"
        case .pendingSecureUpload: return "Pending secure upload"
        case .active: return "Active"
        case .denied: return "Denied"
        case .error: return "Error"
        }
    }
}
