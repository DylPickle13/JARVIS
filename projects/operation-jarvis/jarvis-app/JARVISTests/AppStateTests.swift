import XCTest
@testable import JARVIS
import JARVISKit

@MainActor
final class AppStateTests: XCTestCase {
    func testRefreshConnectsHealthFirstAndLoadsState() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(store: store, client: api)
        app.endpointDraft = "http://fake.jarvis:8790"

        await app.refresh()

        XCTAssertEqual(app.connectionState, .connected)
        XCTAssertEqual(app.lastHealth?.version, "test")
        XCTAssertEqual(app.lastState?.summary?.plugsOn, 1)
        XCTAssertFalse(app.isStateLoading)
    }

    func testHomePollingWaitsBeforeItsFirstRefresh() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(store: store, client: api)
        app.endpointDraft = "http://fake.jarvis:8790"

        app.sceneDidBecomeActive()
        for _ in 0..<20 where api.stateCalls == 0 {
            try await Task.sleep(for: .milliseconds(50))
        }
        let initialCalls = api.stateCalls
        XCTAssertEqual(initialCalls, 1)
        try await Task.sleep(for: .milliseconds(300))
        XCTAssertEqual(api.stateCalls, initialCalls)
        app.sceneWillResignActive()
    }

    func testPlugWritesUseDesiredStateAndRefresh() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(store: store, client: api)
        app.endpointDraft = "http://fake.jarvis:8790"
        await app.refresh()

        let result = await app.setPlug("lamp", isOn: true)

        XCTAssertTrue(result)
        XCTAssertEqual(api.commands, ["plug-on"])
        XCTAssertFalse(app.busyOperations.contains("plug:lamp"))
        XCTAssertNil(app.operationErrorMessage)
    }

    func testWatchCommandCacheIsBounded() {
        let app = AppState()
        for index in 0..<60 {
            app.rememberWatchCommand(
                "request-\(index)",
                entry: WatchCommandCacheEntry(result: CommandResult(ok: true), error: nil)
            )
        }
        XCTAssertEqual(app.watchCommandResponses.count, app.watchCommandCacheLimit)
        XCTAssertNil(app.watchCommandResponses["request-0"])
        XCTAssertNotNil(app.watchCommandResponses["request-59"])
    }

    func testDuplicateWatchRequestExecutesOnlyOnce() async throws {
        let api = FakeAPI(commandDelay: .milliseconds(100))
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(store: store, client: api)
        let requestID = "duplicate-request"

        app.watchBridgeDidReceivePlugCommand(.shared, name: "lamp", isOn: true, requestID: requestID)
        app.watchBridgeDidReceivePlugCommand(.shared, name: "lamp", isOn: true, requestID: requestID)

        for _ in 0..<20 where app.watchCommandResponses[requestID] == nil {
            try await Task.sleep(for: .milliseconds(25))
        }

        XCTAssertEqual(api.commands, ["plug-on"])
        XCTAssertNotNil(app.watchCommandResponses[requestID])
        XCTAssertTrue(app.watchCommandInFlight.isEmpty)
    }

    func testCommandFailureRemainsVisibleAfterStateRefresh() async throws {
        let api = FakeAPI(commandSucceeds: false)
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(store: store, client: api)
        app.endpointDraft = "http://fake.jarvis:8790"
        await app.refresh()

        let result = await app.setPlug("lamp", isOn: true)

        XCTAssertFalse(result)
        XCTAssertEqual(app.operationErrorMessage, "simulated failure")
    }
}

private final class FakeAPI: JarvisAPI, @unchecked Sendable {
    let state: StateSnapshot
    let commandSucceeds: Bool
    let commandDelay: Duration?
    var commands: [String] = []
    var stateCalls = 0

    init(commandSucceeds: Bool = true, commandDelay: Duration? = nil) {
        self.commandSucceeds = commandSucceeds
        self.commandDelay = commandDelay
        self.state = try! JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(#"{"ok":true,"summary":{"plugsOn":1,"plugsTotal":2}}"#.utf8)
        )
    }

    func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse {
        HealthResponse(ok: true, version: "test", uptimeSeconds: 2)
    }

    func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot {
        stateCalls += 1
        return state
    }

    func command(_ endpoint: JarvisEndpoint, action: String, params: [String: JSONValue]?) async throws -> CommandResult {
        if let commandDelay { try await Task.sleep(for: commandDelay) }
        commands.append(action)
        return CommandResult(ok: commandSucceeds, action: action, error: commandSucceeds ? nil : "simulated failure")
    }

    func events(_ endpoint: JarvisEndpoint, since: Int?, limit: Int) async throws -> EventsResponse {
        try! JSONDecoder().decode(EventsResponse.self, from: Data(#"{"ok":true,"count":0,"events":[]}"#.utf8))
    }

    func services(_ endpoint: JarvisEndpoint) async throws -> ServicesListResponse {
        try! JSONDecoder().decode(ServicesListResponse.self, from: Data(#"{"ok":true,"services":{}}"#.utf8))
    }

    func serviceAction(_ endpoint: JarvisEndpoint, name: String, action: String) async throws -> ServiceActionResult {
        try! JSONDecoder().decode(ServiceActionResult.self, from: Data(#"{"ok":true,"service":"test","action":"status"}"#.utf8))
    }

    func discover(_ candidates: [URL], timeout: TimeInterval) async -> URL? { candidates.first }
}
