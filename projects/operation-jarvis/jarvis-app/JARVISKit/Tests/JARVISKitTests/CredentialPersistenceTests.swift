import Foundation
import Security
import XCTest
@testable import JARVISKit

final class CredentialPersistenceTests: XCTestCase {
    final class Fixture {
        var value: Data? = Data("previous".utf8)
        var updateError: OSStatus?
        var addError: OSStatus?
        var deleteError: OSStatus?
        var calls: [String] = []
        var operations: JARVISKeychainOperations {
            .init(update: { _, attributes in
                self.calls.append("update")
                if let error = self.updateError { return error }
                guard self.value != nil else { return errSecItemNotFound }
                self.value = attributes[kSecValueData as String] as? Data
                XCTAssertNil(attributes[kSecAttrAccessible as String], "Do not migrate existing protection")
                return errSecSuccess
            }, add: { attributes in
                self.calls.append("add")
                if let error = self.addError { return error }
                XCTAssertEqual(attributes[kSecAttrAccessible as String] as? String,
                               kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
                self.value = attributes[kSecValueData as String] as? Data
                return errSecSuccess
            }, delete: { _ in
                self.calls.append("delete")
                if let error = self.deleteError { return error }
                self.value = nil
                return errSecSuccess
            }, read: { _ in
                (self.value == nil ? errSecItemNotFound : errSecSuccess, self.value)
            })
        }
    }

    func testUpdateFailurePreservesExistingSecretWithoutDeleteOrInsert() {
        for status in [errSecInteractionNotAllowed, errSecAuthFailed, errSecNotAvailable] {
            let fixture = Fixture(); fixture.updateError = status
            XCTAssertFalse(JARVISCredentialPersistence.write(service: "fixture", account: "fixture", value: "replacement", operations: fixture.operations))
            XCTAssertEqual(fixture.value, Data("previous".utf8))
            XCTAssertEqual(fixture.calls, ["update"])
        }
    }

    func testUpdateAndInsertAreOneAttemptWithNoDeleteFallback() {
        let fixture = Fixture()
        XCTAssertTrue(JARVISCredentialPersistence.write(service: "fixture", account: "fixture", value: "new", operations: fixture.operations))
        XCTAssertEqual(fixture.calls, ["update"])
        XCTAssertEqual(fixture.value, Data("new".utf8))
        fixture.value = nil; fixture.calls = []
        XCTAssertTrue(JARVISCredentialPersistence.write(service: "fixture", account: "fixture", value: "first", operations: fixture.operations))
        XCTAssertEqual(fixture.calls, ["update", "add"])
        fixture.value = nil; fixture.calls = []; fixture.addError = errSecNotAvailable
        XCTAssertFalse(JARVISCredentialPersistence.write(service: "fixture", account: "fixture", value: "first", operations: fixture.operations))
        XCTAssertNil(fixture.value)
        XCTAssertEqual(fixture.calls, ["update", "add"])
    }

    func testEndpointFailedSaveAndClearPreserveConfigurationAndExposeError() {
        let fixture = Fixture()
        let name = "jarvis.credential-fixture.\(UUID())"
        let defaults = UserDefaults(suiteName: name)!
        defer { defaults.removePersistentDomain(forName: name) }
        let store = EndpointStore(defaults: defaults, keychain: fixture.operations)
        store.endpointURLString = "http://fixture.invalid:8790"
        fixture.updateError = errSecInteractionNotAllowed
        store.token = "replacement"
        XCTAssertEqual(store.token, "previous")
        XCTAssertNotNil(store.keychainError)
        fixture.deleteError = errSecNotAvailable
        XCTAssertFalse(store.clear())
        XCTAssertNotNil(store.endpointURL)
        XCTAssertEqual(store.token, "previous")
        XCTAssertNotNil(store.keychainError)
        fixture.deleteError = nil
        XCTAssertTrue(store.clear())
        XCTAssertNil(store.endpointURL)
        XCTAssertNil(store.token)
        XCTAssertNil(store.keychainError)
    }

    func testAbsentDeletionIsSuccessful() {
        let fixture = Fixture(); fixture.value = nil; fixture.deleteError = errSecItemNotFound
        XCTAssertTrue(JARVISCredentialPersistence.delete(service: "fixture", account: "fixture", operations: fixture.operations))
    }
}
