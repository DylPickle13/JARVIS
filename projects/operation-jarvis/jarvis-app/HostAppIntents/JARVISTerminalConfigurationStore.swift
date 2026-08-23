import Foundation
import JARVISKit
import Security

enum JARVISTerminalConfigurationLoadResult {
    case configured(WatchTerminalConfiguration)
    case missing
    case locked
    case invalid
}

/// Target-local terminal credentials for host app UI and App Intents. Free
/// provisioning prevents shared Keychain access, so iPhone and Watch use their
/// existing local service names while retaining identical defaults keys.
struct JARVISTerminalConfigurationStore {
    static let endpointKey = "jarvis.watch-terminal.endpoint"
    static let fingerprintKey = "jarvis.watch-terminal.certificate-sha256"
    static let tokenAccount = "bridge.token"

    #if os(watchOS)
    static let keychainService = "com.operation-jarvis.jarvis.watchkitapp.watch-terminal"
    #else
    static let keychainService = "com.operation-jarvis.jarvis.watch-terminal"
    #endif

    static func load(defaults: UserDefaults = .standard) -> JARVISTerminalConfigurationLoadResult {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: tokenAccount,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess:
            guard let data = result as? Data,
                  let token = String(data: data, encoding: .utf8) else { return .invalid }
            let configuration = WatchTerminalConfiguration(
                endpoint: defaults.string(forKey: endpointKey) ?? "",
                token: token,
                certificateSHA256: defaults.string(forKey: fingerprintKey) ?? ""
            )
            return configuration.isValid ? .configured(configuration) : .invalid
        case errSecItemNotFound:
            return .missing
        case errSecInteractionNotAllowed, errSecAuthFailed:
            return .locked
        default:
            return .invalid
        }
    }

    @discardableResult
    static func save(
        _ configuration: WatchTerminalConfiguration,
        defaults: UserDefaults = .standard
    ) -> Bool {
        guard configuration.isValid,
              let data = configuration.token.data(using: .utf8) else { return false }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: tokenAccount,
        ]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(add as CFDictionary, nil) == errSecSuccess else { return false }
        defaults.set(configuration.endpoint, forKey: endpointKey)
        defaults.set(configuration.certificateSHA256, forKey: fingerprintKey)
        return true
    }
}
