import Foundation
import Security

// Persists the jarvisd endpoint. The URL is non-secret (UserDefaults); the
// API token is secret (Keychain, accessible when the device is unlocked).
//
// Works on both iOS and watchOS (Security framework is available on watchOS).
public final class EndpointStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let urlKey = "jarvis.endpoint.url"
    private let service = "com.operation-jarvis.app"
    private let tokenAccount = "jarvis.api.token"
    private let lock = NSLock()

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    // MARK: - Endpoint URL (non-secret)

    public var endpointURLString: String? {
        get { defaults.string(forKey: urlKey) }
        set {
            lock.lock(); defer { lock.unlock() }
            if let newValue, !newValue.isEmpty {
                defaults.set(newValue, forKey: urlKey)
            } else {
                defaults.removeObject(forKey: urlKey)
            }
        }
    }

    public var endpointURL: URL? {
        guard let s = endpointURLString, !s.isEmpty else { return nil }
        var string = s
        if !string.hasPrefix("http://") && !string.hasPrefix("https://") {
            string = "http://" + string
        }
        return URL(string: string)
    }

    // MARK: - Token (secret, Keychain)

    public var token: String? {
        get { Keychain.read(service: service, account: tokenAccount) }
        set {
            if let newValue, !newValue.isEmpty {
                Keychain.write(service: service, account: tokenAccount, value: newValue)
            } else {
                Keychain.delete(service: service, account: tokenAccount)
            }
        }
    }

    // MARK: - Combined endpoint

    public var endpoint: JarvisEndpoint? {
        guard let url = endpointURL else { return nil }
        return JarvisEndpoint(baseURL: url, token: token ?? "")
    }

    public func isConfigured() -> Bool {
        endpointURL != nil
    }

    public func clear() {
        endpointURLString = nil
        token = nil
    }
}

// MARK: - Minimal Keychain wrapper

enum Keychain {
    static func write(service: String, account: String, value: String) -> Bool {
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

    static func read(service: String, account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(service: String, account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
