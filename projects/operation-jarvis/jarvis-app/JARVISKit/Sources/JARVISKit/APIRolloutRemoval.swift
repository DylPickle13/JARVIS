import Foundation
import Security

/// Explicit owner action to undo ONLY the enrollment record added by the
/// cancelled rollout. Does not read a secret, touch the older API-token account,
/// endpoint, SSH credentials, backend configuration or another target's vault.
public enum APIRolloutRemoval {
    static let service = "com.operation-jarvis.app"
    static let account = "jarvis.api.configuration.v1"
    static let marker = "jarvis.api.enrolled.v1"

    @discardableResult
    public static func remove(defaults: UserDefaults = .standard) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        return remove(defaults: defaults,
            delete: { SecItemDelete(query as CFDictionary) },
            lookup: {
                var attributes = query
                attributes[kSecReturnAttributes as String] = true
                attributes[kSecMatchLimit as String] = kSecMatchLimitOne
                // Attribute-only existence check; never request credential data.
                return SecItemCopyMatching(attributes as CFDictionary, nil)
            })
    }

    // Synthetic tests never read or mutate a real Keychain.
    static func remove(defaults: UserDefaults, delete: () -> OSStatus,
                       lookup: () -> OSStatus) -> Bool {
        let status = delete()
        guard status == errSecSuccess || status == errSecItemNotFound,
              lookup() == errSecItemNotFound else { return false }
        defaults.removeObject(forKey: marker)
        return true
    }
}
