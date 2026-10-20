import Foundation
import Security

// Persists the jarvisd endpoint. The URL is non-secret (UserDefaults); the
// API token is secret (Keychain, accessible when the device is unlocked).
//
// Works on both iOS and watchOS (Security framework is available on watchOS).
public final class EndpointStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let keychain: JARVISKeychainOperations
    private let urlKey = "jarvis.endpoint.url"
    private let service = "com.operation-jarvis.app"
    private let tokenAccount = "jarvis.api.token"
    private let lock = NSLock()

    /// Non-secret diagnostic for Settings/tests. The token itself is never
    /// exposed; a failed Keychain write is kept visible to the owner instead
    /// of being silently discarded.
    public private(set) var keychainError: String?

    public init(defaults: UserDefaults = .standard, keychain: JARVISKeychainOperations = .live) {
        self.defaults = defaults
        self.keychain = keychain
    }

    // MARK: - Endpoint URL (non-secret)

    public var endpointURLString: String? {
        get { defaults.string(forKey: urlKey) }
        set {
            lock.lock(); defer { lock.unlock() }
            guard let newValue else {
                defaults.removeObject(forKey: urlKey)
                return
            }
            let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else {
                defaults.removeObject(forKey: urlKey)
                return
            }
            // Invalid input never replaces a previously trusted endpoint.
            guard let normalized = JarvisEndpointURLPolicy.parse(trimmed) else { return }
            let normalizedValue = normalized.absoluteString
            guard defaults.string(forKey: urlKey) != normalizedValue else { return }
            defaults.set(normalizedValue, forKey: urlKey)
        }
    }

    public var endpointURL: URL? {
        guard let value = endpointURLString else { return nil }
        return JarvisEndpointURLPolicy.parse(value)
    }

    // MARK: - Token (secret, Keychain)

    public var token: String? {
        get {
            let result = JARVISCredentialPersistence.read(service: service, account: tokenAccount, operations: keychain)
            guard result.status == errSecSuccess, let data = result.data else { return nil }
            return String(data: data, encoding: .utf8)
        }
        set {
            if let newValue, !newValue.isEmpty {
                if JARVISCredentialPersistence.write(service: service, account: tokenAccount, value: newValue, operations: keychain) {
                    keychainError = nil
                } else {
                    keychainError = "Could not save the API token in Keychain."
                }
            } else {
                keychainError = JARVISCredentialPersistence.delete(service: service, account: tokenAccount, operations: keychain)
                    ? nil : "Could not remove the API token from Keychain."
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

    @discardableResult
    public func clear() -> Bool {
        token = nil
        guard keychainError == nil else { return false }
        endpointURLString = nil
        return true
    }
}
