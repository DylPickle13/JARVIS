import Foundation
import Security
import XCTest
@testable import JARVISKit

final class APIRolloutRemovalTests: XCTestCase {
    private func defaults() -> UserDefaults {
        let name = "rollout-removal-tests-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        defaults.set(true, forKey: APIRolloutRemoval.marker)
        defaults.set("http://192.168.1.99:8790", forKey: "jarvis.endpoint.url")
        defaults.set("fixture-ssh-host", forKey: "existing.unrelated.setting")
        return defaults
    }

    func testOnlyAddedRecordAndMarkerAreTargeted() {
        XCTAssertEqual(APIRolloutRemoval.service, "com.operation-jarvis.app")
        XCTAssertEqual(APIRolloutRemoval.account, "jarvis.api.configuration.v1")
        XCTAssertNotEqual(APIRolloutRemoval.account, "jarvis.api.token")
        let store = defaults()
        var deletes = 0, lookups = 0
        XCTAssertTrue(APIRolloutRemoval.remove(defaults: store, delete: { deletes += 1; return errSecSuccess },
                                               lookup: { lookups += 1; return errSecItemNotFound }))
        XCTAssertEqual(deletes, 1)
        XCTAssertEqual(lookups, 1)
        XCTAssertNil(store.object(forKey: APIRolloutRemoval.marker))
        XCTAssertEqual(store.string(forKey: "jarvis.endpoint.url"), "http://192.168.1.99:8790")
        XCTAssertEqual(store.string(forKey: "existing.unrelated.setting"), "fixture-ssh-host")
    }

    func testAlreadyAbsentRecordIsVerifiedWithoutCreatingAnything() {
        let store = defaults()
        XCTAssertTrue(APIRolloutRemoval.remove(defaults: store, delete: { errSecItemNotFound },
                                               lookup: { errSecItemNotFound }))
        XCTAssertNil(store.object(forKey: APIRolloutRemoval.marker))
    }

    func testLockedOrFailedDeletionDoesNotClearMarkerOrRetry() {
        for status in [errSecInteractionNotAllowed, errSecAuthFailed, errSecParam] {
            let store = defaults()
            var deletes = 0
            XCTAssertFalse(APIRolloutRemoval.remove(defaults: store, delete: { deletes += 1; return status },
                lookup: { XCTFail("Do not claim removal after failed deletion"); return errSecItemNotFound }))
            XCTAssertEqual(deletes, 1)
            XCTAssertTrue(store.bool(forKey: APIRolloutRemoval.marker))
        }
    }

    func testSuccessfulDeletionRequiresActualAbsenceReadback() {
        for status in [errSecSuccess, errSecInteractionNotAllowed, errSecAuthFailed] {
            let store = defaults()
            XCTAssertFalse(APIRolloutRemoval.remove(defaults: store, delete: { errSecSuccess }, lookup: { status }))
            XCTAssertTrue(store.bool(forKey: APIRolloutRemoval.marker))
        }
    }

    func testOtherTargetDefaultsAreNotCleared() {
        let phone = defaults(), watch = defaults()
        XCTAssertTrue(APIRolloutRemoval.remove(defaults: phone, delete: { errSecSuccess }, lookup: { errSecItemNotFound }))
        XCTAssertTrue(watch.bool(forKey: APIRolloutRemoval.marker))
        XCTAssertNil(phone.object(forKey: APIRolloutRemoval.marker))
    }
}
