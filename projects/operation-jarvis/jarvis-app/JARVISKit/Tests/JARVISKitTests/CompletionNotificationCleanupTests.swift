import XCTest
@testable import JARVISKit

final class CompletionNotificationCleanupTests: XCTestCase {
    private func entry(_ id: String = "completion", at seconds: Double) -> CompletionNotificationDelivery {
        CompletionNotificationDelivery(identifier: id, deliveredAt: Date(timeIntervalSince1970: seconds),
            userInfo: ["route": "pi-session-completed", "routeVersion": 1, "sessionID": 1])!
    }

    func testOnlyStrictCompletionRoutesAreEligible() {
        let date = Date()
        for slot in 1...6 {
            XCTAssertNotNil(CompletionNotificationDelivery(identifier: "n", deliveredAt: date,
                userInfo: ["route": "pi-session-completed", "routeVersion": 1, "sessionID": slot]))
        }
        let payloads: [[AnyHashable: Any]] = [
            ["route": "scheduled-job-result", "routeVersion": 1, "resultSequence": 1],
            ["route": "other", "routeVersion": 1, "sessionID": 1],
            ["route": "pi-session-completed", "routeVersion": 2, "sessionID": 1],
            ["route": "pi-session-completed", "routeVersion": true, "sessionID": 1],
            ["route": "pi-session-completed", "routeVersion": 1, "sessionID": 7],
            ["route": "pi-session-completed", "routeVersion": 1, "sessionID": false],
            [:]
        ]
        for payload in payloads {
            XCTAssertNil(CompletionNotificationDelivery(identifier: "n", deliveredAt: date, userInfo: payload))
        }
        XCTAssertNil(CompletionNotificationDelivery(identifier: "", deliveredAt: date,
            userInfo: ["route": "pi-session-completed", "routeVersion": 1, "sessionID": 1]))
    }

    @MainActor
    func testOpeningClearsExistingButNotNewCompletionDeliveries() async {
        var time = 100.0
        var removed: [String] = []
        let deliveries = [entry("old", at: 99), entry("new", at: 101)]
        let cleanup = CompletionNotificationCleanup(delivered: { deliveries }, remove: { removed += $0 },
            now: { Date(timeIntervalSince1970: time) }, automaticallyPoll: false)
        cleanup.sceneDidBecomeActive()
        time = 102
        _ = await cleanup.sweep()
        XCTAssertEqual(removed, ["old"])
    }

    @MainActor
    func testThirtySecondBoundaryAndDuplicateActivation() async {
        var time = 100.0
        var removed: [String] = []
        let notification = entry(at: 101)
        let cleanup = CompletionNotificationCleanup(delivered: { [notification] }, remove: { removed += $0 },
            now: { Date(timeIntervalSince1970: time) }, automaticallyPoll: false)
        cleanup.sceneDidBecomeActive()
        time = 130
        cleanup.sceneDidBecomeActive() // Must not treat a duplicate callback as reopening.
        let delay = await cleanup.sweep()
        XCTAssertEqual(delay, 1)
        XCTAssertTrue(removed.isEmpty)
        time = 131
        _ = await cleanup.sweep()
        XCTAssertEqual(removed, ["completion"])
    }

    @MainActor
    func testInactiveDoesNotReadOrRemoveAndResumeClearsRetainedAlerts() async {
        var time = 100.0
        var reads = 0
        var removed: [String] = []
        let notification = entry(at: 101)
        let cleanup = CompletionNotificationCleanup(delivered: { reads += 1; return [notification] }, remove: { removed += $0 },
            now: { Date(timeIntervalSince1970: time) }, automaticallyPoll: false)
        cleanup.sceneDidBecomeActive()
        cleanup.sceneWillResignActive()
        time = 200
        let delay = await cleanup.sweep()
        XCTAssertNil(delay)
        XCTAssertEqual(reads, 0)
        XCTAssertTrue(removed.isEmpty)
        cleanup.sceneDidBecomeActive()
        _ = await cleanup.sweep()
        XCTAssertEqual(removed, ["completion"])
    }

    @MainActor
    func testLateDeliveryQueryCannotRemoveAfterBackgroundOrNewActivation() async {
        for resume in [false, true] {
            var continuation: CheckedContinuation<[CompletionNotificationDelivery], Never>?
            var removed: [String] = []
            let cleanup = CompletionNotificationCleanup(delivered: {
                await withCheckedContinuation { continuation = $0 }
            }, remove: { removed += $0 }, now: { Date(timeIntervalSince1970: 100) }, automaticallyPoll: false)
            cleanup.sceneDidBecomeActive()
            let query = Task { await cleanup.sweep() }
            while continuation == nil { await Task.yield() }
            cleanup.sceneWillResignActive()
            if resume { cleanup.sceneDidBecomeActive() }
            continuation?.resume(returning: [entry(at: 90)])
            let delay = await query.value
            XCTAssertNil(delay)
            XCTAssertTrue(removed.isEmpty)
        }
    }

    @MainActor
    func testReplacementIsJudgedByCurrentDeliveryDateNotRememberedIdentifier() async {
        var time = 100.0
        var notifications = [entry(at: 101)]
        var removed: [String] = []
        let cleanup = CompletionNotificationCleanup(delivered: { notifications }, remove: { removed += $0 },
            now: { Date(timeIntervalSince1970: time) }, automaticallyPoll: false)
        cleanup.sceneDidBecomeActive()
        time = 120
        _ = await cleanup.sweep()
        notifications = [entry(at: 131)]
        time = 132
        _ = await cleanup.sweep()
        XCTAssertTrue(removed.isEmpty)
    }

    @MainActor
    func testIndependentTargetsAndNoRemovalForEmptyQuery() async {
        var phoneRemoved: [String] = []
        var watchRemoved: [String] = []
        let notification = entry(at: 90)
        let phone = CompletionNotificationCleanup(delivered: { [notification] }, remove: { phoneRemoved += $0 },
            now: { Date(timeIntervalSince1970: 100) }, automaticallyPoll: false)
        let watch = CompletionNotificationCleanup(delivered: { [] }, remove: { watchRemoved += $0 },
            now: { Date(timeIntervalSince1970: 100) }, automaticallyPoll: false)
        phone.sceneDidBecomeActive()
        watch.sceneDidBecomeActive()
        _ = await phone.sweep()
        _ = await watch.sweep()
        XCTAssertEqual(phoneRemoved, ["completion"])
        XCTAssertTrue(watchRemoved.isEmpty)
    }
}
