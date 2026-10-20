import Foundation
import Security

/// Injectable Security operations. Tests supply in-memory fixtures, never real credentials.
public struct JARVISKeychainOperations: @unchecked Sendable {
    public let update: ([String: Any], [String: Any]) -> OSStatus
    public let add: ([String: Any]) -> OSStatus
    public let delete: ([String: Any]) -> OSStatus
    public let read: ([String: Any]) -> (OSStatus, Data?)

    public init(update: @escaping ([String: Any], [String: Any]) -> OSStatus,
                add: @escaping ([String: Any]) -> OSStatus,
                delete: @escaping ([String: Any]) -> OSStatus,
                read: @escaping ([String: Any]) -> (OSStatus, Data?)) {
        self.update = update; self.add = add; self.delete = delete; self.read = read
    }

    public static let live = Self(
        update: { SecItemUpdate($0 as CFDictionary, $1 as CFDictionary) },
        add: { SecItemAdd($0 as CFDictionary, nil) },
        delete: { SecItemDelete($0 as CFDictionary) },
        read: { query in
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            return (status, result as? Data)
        }
    )
}

/// Update-first replacement preserves the old secret if Security rejects a save.
/// No retry, delete/reinsert fallback, protection-class migration or credential logging.
public enum JARVISCredentialPersistence {
    private static func identity(service: String, account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    public static func write(service: String, account: String, value: String,
                             operations: JARVISKeychainOperations = .live) -> Bool {
        let data = Data(value.utf8)
        let query = identity(service: service, account: account)
        let status = operations.update(query, [kSecValueData as String: data])
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return operations.add(add) == errSecSuccess
    }

    public static func read(service: String, account: String,
                            operations: JARVISKeychainOperations = .live) -> (status: OSStatus, data: Data?) {
        var query = identity(service: service, account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        return operations.read(query)
    }

    public static func delete(service: String, account: String,
                              operations: JARVISKeychainOperations = .live) -> Bool {
        let status = operations.delete(identity(service: service, account: account))
        return status == errSecSuccess || status == errSecItemNotFound
    }
}
