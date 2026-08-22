import Foundation
import JARVISKit
import Security

@MainActor
final class WatchTerminalProvisioningSettings: ObservableObject {
    @Published private(set) var isProvisioned: Bool
    @Published private(set) var endpoint: String
    @Published private(set) var errorMessage: String?

    private let defaults: UserDefaults
    private let endpointKey = "jarvis.watch-terminal.endpoint"
    private let fingerprintKey = "jarvis.watch-terminal.certificate-sha256"
    private let keychainService = "com.operation-jarvis.jarvis.watch-terminal"
    private let tokenAccount = "bridge.token"

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let savedEndpoint = defaults.string(forKey: endpointKey) ?? ""
        self.endpoint = savedEndpoint
        let token = Self.readKeychain(service: keychainService, account: tokenAccount)
        let fingerprint = defaults.string(forKey: fingerprintKey) ?? ""
        self.isProvisioned = WatchTerminalConfiguration(
            endpoint: savedEndpoint,
            token: token ?? "",
            certificateSHA256: fingerprint
        ).isValid
    }

    var configuration: WatchTerminalConfiguration? {
        guard let token = Self.readKeychain(service: keychainService, account: tokenAccount) else { return nil }
        let configuration = WatchTerminalConfiguration(
            endpoint: defaults.string(forKey: endpointKey) ?? "",
            token: token,
            certificateSHA256: defaults.string(forKey: fingerprintKey) ?? ""
        )
        return configuration.isValid ? configuration : nil
    }

    @discardableResult
    func save(provisioningCode: String) -> Bool {
        guard let configuration = WatchTerminalConfiguration.fromProvisioningCode(provisioningCode) else {
            errorMessage = "The Watch terminal setup code is invalid."
            return false
        }
        guard Self.writeKeychain(service: keychainService, account: tokenAccount, value: configuration.token) else {
            errorMessage = "Could not save the Watch terminal token in Keychain."
            return false
        }
        defaults.set(configuration.endpoint, forKey: endpointKey)
        defaults.set(configuration.certificateSHA256, forKey: fingerprintKey)
        endpoint = configuration.endpoint
        isProvisioned = true
        errorMessage = nil
        return true
    }

    private static func writeKeychain(service: String, account: String, value: String) -> Bool {
        guard let data = value.data(using: .utf8) else { return false }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }

    private static func readKeychain(service: String, account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
