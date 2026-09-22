import XCTest
@testable import JARVIS

@MainActor
final class PiSessionMaintenanceTests: XCTestCase {
    private func defaults() -> UserDefaults {
        let name = "maintenance-tests-\(UUID())"
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return defaults
    }

    func testRestoresPendingOperationWithoutAutomaticallyRestarting() {
        let defaults = defaults()
        let id = UUID().uuidString.lowercased()
        defaults.set(id, forKey: "jarvis.pi-maintenance.pending-operation")
        let controller = PiSessionMaintenanceController(defaults: defaults)
        XCTAssertEqual(controller.operationID, id)
        XCTAssertFalse(controller.isWorking)
        XCTAssertFalse(controller.canRetrySubmission)
        XCTAssertNotNil(controller.message)
    }

    func testUntrustedHostCannotStartRestart() {
        let controller = PiSessionMaintenanceController(defaults: defaults())
        controller.run(configuration: .init(host: "example.invalid", port: 22, username: "test", password: ""),
                       trustedHostKey: nil, start: true) { XCTFail("Must not connect") }
        XCTAssertNil(controller.operationID)
        XCTAssertFalse(controller.isWorking)
        XCTAssertTrue(controller.message?.contains("trust") == true)
    }

    func testPendingOperationCannotMoveToAnotherHost() {
        let defaults = defaults()
        let id = UUID().uuidString.lowercased()
        defaults.set(id, forKey: "jarvis.pi-maintenance.pending-operation")
        defaults.set("test@original.invalid:22", forKey: "jarvis.pi-maintenance.pending-host")
        let controller = PiSessionMaintenanceController(defaults: defaults)
        controller.run(configuration: .init(host: "other.invalid", port: 22, username: "test", password: ""),
                       trustedHostKey: "test", start: false) { XCTFail("Must not connect") }
        XCTAssertEqual(controller.operationID, id)
        XCTAssertFalse(controller.isWorking)
        XCTAssertTrue(controller.message?.contains("original SSH host") == true)
    }
}
