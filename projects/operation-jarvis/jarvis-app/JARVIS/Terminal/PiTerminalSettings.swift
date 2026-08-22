import Combine
import Foundation
import Security

struct PiTerminalConfiguration: Equatable, Sendable {
    let host: String
    let port: Int
    let username: String
    let password: String

    static let defaultPort = 22
    static let defaultUsername = "dylanrapanan"
    static let remoteCommand = #"/opt/homebrew/bin/tmux -L jarvis-mobile -f /Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app/config/jarvis-mobile.tmux.conf new-session -A -s jarvis-ios -c /Users/dylanrapanan/JARVIS '/opt/homebrew/bin/pi --name "JARVIS iPhone"'"#
}

@MainActor
final class PiTerminalSettings: ObservableObject {
    @Published private(set) var host: String
    @Published private(set) var port: Int
    @Published private(set) var username: String
    @Published private(set) var hasPassword: Bool
    @Published private(set) var credentialError: String?

    private let defaults: UserDefaults
    private let hostKey = "jarvis.pi-terminal.host"
    private let portKey = "jarvis.pi-terminal.port"
    private let usernameKey = "jarvis.pi-terminal.username"
    private let trustedHostPrefix = "jarvis.pi-terminal.trusted-host."
    private let keychainService = "com.operation-jarvis.jarvis.pi-terminal"
    private let passwordAccount = "ssh.password"
#if DEBUG && targetEnvironment(simulator)
    private var simulatorSeededPassword: String?
#endif

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.host = defaults.string(forKey: hostKey) ?? ""
        let savedPort = defaults.integer(forKey: portKey)
        self.port = savedPort > 0 ? savedPort : PiTerminalConfiguration.defaultPort
        self.username = defaults.string(forKey: usernameKey) ?? PiTerminalConfiguration.defaultUsername
        self.hasPassword = Self.readKeychain(service: keychainService, account: passwordAccount) != nil
#if DEBUG && targetEnvironment(simulator)
        applySimulatorLaunchSeedIfPresent()
#endif
    }

    func passwordForEditing() -> String {
#if DEBUG && targetEnvironment(simulator)
        if let simulatorSeededPassword { return simulatorSeededPassword }
#endif
        return Self.readKeychain(service: keychainService, account: passwordAccount) ?? ""
    }

    @discardableResult
    func save(host: String, portText: String, username: String, password: String) -> Bool {
        let cleanHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanUsername = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parsedPort = Int(portText), (1...65_535).contains(parsedPort), !cleanUsername.isEmpty else {
            credentialError = "Enter a valid SSH username and port."
            return false
        }

        defaults.set(cleanHost, forKey: hostKey)
        defaults.set(parsedPort, forKey: portKey)
        defaults.set(cleanUsername, forKey: usernameKey)

        if password.isEmpty {
            Self.deleteKeychain(service: keychainService, account: passwordAccount)
        } else if !Self.writeKeychain(service: keychainService, account: passwordAccount, value: password) {
            credentialError = "Could not save the SSH password in Keychain."
            return false
        }

        self.host = cleanHost
        self.port = parsedPort
        self.username = cleanUsername
        self.hasPassword = !password.isEmpty
        credentialError = nil
        return true
    }

    func configuration(fallbackHost: String?) -> PiTerminalConfiguration? {
        let resolvedHost = host.isEmpty
            ? fallbackHost?.trimmingCharacters(in: .whitespacesAndNewlines)
            : host
        guard let resolvedHost, !resolvedHost.isEmpty, !username.isEmpty else { return nil }
#if DEBUG && targetEnvironment(simulator)
        if let simulatorSeededPassword, !simulatorSeededPassword.isEmpty {
            return PiTerminalConfiguration(host: resolvedHost, port: port, username: username, password: simulatorSeededPassword)
        }
#endif
        guard let password = Self.readKeychain(service: keychainService, account: passwordAccount), !password.isEmpty else {
            return nil
        }
        return PiTerminalConfiguration(host: resolvedHost, port: port, username: username, password: password)
    }

    func trustedHostKey(host: String, port: Int) -> String? {
        defaults.string(forKey: trustedHostDefaultsKey(host: host, port: port))
    }

    func trustHostKey(_ key: String, host: String, port: Int) {
        defaults.set(key, forKey: trustedHostDefaultsKey(host: host, port: port))
    }

    func forgetTrustedHost(host: String, port: Int) {
        defaults.removeObject(forKey: trustedHostDefaultsKey(host: host, port: port))
    }

    func forgetCurrentTrustedHost(fallbackHost: String?) {
        let resolvedHost = host.isEmpty ? fallbackHost : host
        guard let resolvedHost, !resolvedHost.isEmpty else { return }
        forgetTrustedHost(host: resolvedHost, port: port)
    }

    private func trustedHostDefaultsKey(host: String, port: Int) -> String {
        trustedHostPrefix + host.lowercased() + ":" + String(port)
    }

#if DEBUG && targetEnvironment(simulator)
    private func applySimulatorLaunchSeedIfPresent() {
        let arguments = CommandLine.arguments
        func value(after flag: String) -> String? {
            guard let index = arguments.firstIndex(of: flag), index + 1 < arguments.count else { return nil }
            return arguments[index + 1]
        }
        guard let seededPassword = value(after: "-jarvisSeedSSHPassword") else { return }
        let seededHost = value(after: "-jarvisSeedSSHHost") ?? "127.0.0.1"
        let seededPort = Int(value(after: "-jarvisSeedSSHPort") ?? "22") ?? 22
        let seededUsername = value(after: "-jarvisSeedSSHUsername") ?? "test"
        defaults.set(seededHost, forKey: hostKey)
        defaults.set(seededPort, forKey: portKey)
        defaults.set(seededUsername, forKey: usernameKey)
        host = seededHost
        port = seededPort
        username = seededUsername
        simulatorSeededPassword = seededPassword
        hasPassword = true
        credentialError = nil
    }
#endif

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

    private static func deleteKeychain(service: String, account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
