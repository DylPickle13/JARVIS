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

    func testHomePollingRefreshesTogetherAndStopsOutsideHome() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(store: store, client: api, activeRefreshInterval: .milliseconds(100))
        app.endpointDraft = "http://fake.jarvis:8790"

        app.sceneDidBecomeActive()
        for _ in 0..<40 where api.stateCalls < 2 || api.servicesCalls < 2 || api.scheduledJobsCalls < 2 {
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertGreaterThanOrEqual(api.stateCalls, 2)
        XCTAssertEqual(api.stateCalls, api.servicesCalls)
        XCTAssertEqual(api.stateCalls, api.scheduledJobsCalls)

        app.setActiveSection(.settings)
        try await Task.sleep(for: .milliseconds(50))
        let settingsCounts = (api.stateCalls, api.servicesCalls, api.scheduledJobsCalls, api.healthCalls)
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertEqual(api.stateCalls, settingsCounts.0)
        XCTAssertEqual(api.servicesCalls, settingsCounts.1)
        XCTAssertEqual(api.scheduledJobsCalls, settingsCounts.2)
        XCTAssertEqual(api.healthCalls, settingsCounts.3)

        app.setActiveSection(.home)
        for _ in 0..<20 where api.stateCalls == settingsCounts.0 {
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertGreaterThan(api.stateCalls, settingsCounts.0)

        app.sceneWillResignActive()
        try await Task.sleep(for: .milliseconds(50))
        let backgroundCounts = (api.stateCalls, api.servicesCalls, api.scheduledJobsCalls, api.healthCalls)
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertEqual(api.stateCalls, backgroundCounts.0)
        XCTAssertEqual(api.servicesCalls, backgroundCounts.1)
        XCTAssertEqual(api.scheduledJobsCalls, backgroundCounts.2)
        XCTAssertEqual(api.healthCalls, backgroundCounts.3)
    }

    func testWatchStateRequestFetchesFreshStateBeforeReplying() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(store: store, client: api)
        app.endpointDraft = "http://fake.jarvis:8790"
        await app.refresh()
        let initialCalls = api.stateCalls

        app.watchBridgeDidReceiveStateRequest(.shared, requestID: "test-state-request")
        for _ in 0..<20 where api.stateCalls == initialCalls {
            try await Task.sleep(for: .milliseconds(25))
        }

        XCTAssertGreaterThan(api.stateCalls, initialCalls)
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

    func testWatchRelayAlreadyDesiredStateDoesNotPost() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(store: store, client: api)
        let requestID = "already-desired-request"

        app.watchBridgeDidReceivePlugCommand(.shared, name: "tv", isOn: true, requestID: requestID)
        for _ in 0..<20 where app.watchCommandResponses[requestID] == nil {
            try await Task.sleep(for: .milliseconds(25))
        }

        XCTAssertTrue(api.commands.isEmpty)
        XCTAssertEqual(app.watchCommandResponses[requestID]?.result?.plug?.is_on, true)
        XCTAssertEqual(app.watchCommandResponses[requestID]?.result?.summary, "already-in-desired-state")
    }

    func testWatchRelayRejectsUnknownPlugWithoutPost() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(store: store, client: api)
        let requestID = "unknown-plug-request"

        app.watchBridgeDidReceivePlugCommand(.shared, name: "removed-plug", isOn: true, requestID: requestID)
        for _ in 0..<20 where app.watchCommandResponses[requestID] == nil {
            try await Task.sleep(for: .milliseconds(25))
        }

        XCTAssertTrue(api.commands.isEmpty)
        XCTAssertNil(app.watchCommandResponses[requestID]?.result)
        XCTAssertNotNil(app.watchCommandResponses[requestID]?.error)
    }

    func testSiriParameterRegistrarPublishesOnceAndRepublishesForNewPhraseSchema() async throws {
        let api = FakeAPI()
        let suite = "jarvis.siri-registrar.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        var seededCatalogues: [[String]] = []
        var publishCount = 0

        let registrar = JARVISSiriParameterRegistrar(
            defaults: defaults,
            schemaVersion: 1,
            seed: { plugs in seededCatalogues.append(plugs.map(\.id)) },
            publish: { publishCount += 1 }
        )
        registrar.updateIfNeeded(from: api.state)
        for _ in 0..<20 where publishCount == 0 {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(publishCount, 1)
        XCTAssertEqual(seededCatalogues, [["lamp", "tv"]])

        registrar.updateIfNeeded(from: api.state)
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(publishCount, 1)

        let upgradedRegistrar = JARVISSiriParameterRegistrar(
            defaults: defaults,
            schemaVersion: 2,
            seed: { plugs in seededCatalogues.append(plugs.map(\.id)) },
            publish: { publishCount += 1 }
        )
        upgradedRegistrar.updateIfNeeded(from: api.state)
        for _ in 0..<20 where publishCount == 1 {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(publishCount, 2)
        XCTAssertEqual(seededCatalogues, [["lamp", "tv"], ["lamp", "tv"]])
    }

    func testScheduledJobsFailureDoesNotHideServiceStatus() async throws {
        let api = FakeAPI(scheduledJobsSucceeds: false)
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(store: store, client: api)
        app.endpointDraft = "http://fake.jarvis:8790"
        await app.refresh()

        await app.fetchServices()
        await app.fetchScheduledJobs()

        XCTAssertTrue(app.servicesLoaded)
        XCTAssertEqual(app.lastServices["room-audio-server"]?.running, true)
        XCTAssertTrue(app.scheduledJobsLoaded)
        XCTAssertNotNil(app.scheduledJobsErrorMessage)
        XCTAssertTrue(app.lastScheduledJobs.isEmpty)
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
    let scheduledJobsSucceeds: Bool
    var commands: [String] = []
    var stateCalls = 0
    var healthCalls = 0
    var servicesCalls = 0
    var scheduledJobsCalls = 0

    init(
        commandSucceeds: Bool = true,
        commandDelay: Duration? = nil,
        scheduledJobsSucceeds: Bool = true
    ) {
        self.commandSucceeds = commandSucceeds
        self.commandDelay = commandDelay
        self.scheduledJobsSucceeds = scheduledJobsSucceeds
        self.state = try! JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(#"{"ok":true,"stale":false,"summary":{"plugsOn":1,"plugsTotal":2},"subsystems":{"plugs":{"ok":true,"stale":false,"plugs":{"lamp":{"ok":true,"stale":false,"isOn":false},"tv":{"ok":true,"stale":false,"isOn":true}}}}}"#.utf8)
        )
    }

    func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse {
        healthCalls += 1
        return HealthResponse(ok: true, version: "test", uptimeSeconds: 2)
    }

    func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot {
        stateCalls += 1
        return state
    }

    func command(_ endpoint: JarvisEndpoint, action: String, params: [String: JSONValue]?) async throws -> CommandResult {
        if let commandDelay { try await Task.sleep(for: commandDelay) }
        commands.append(action)
        return CommandResult(
            ok: commandSucceeds,
            action: action,
            error: commandSucceeds ? nil : "simulated failure",
            plug: commandSucceeds
                ? PlugCommandData(name: "lamp", is_on: action == "plug-on")
                : nil
        )
    }

    func events(_ endpoint: JarvisEndpoint, since: Int?, limit: Int) async throws -> EventsResponse {
        try! JSONDecoder().decode(EventsResponse.self, from: Data(#"{"ok":true,"count":0,"events":[]}"#.utf8))
    }

    func services(_ endpoint: JarvisEndpoint) async throws -> ServicesListResponse {
        servicesCalls += 1
        return try! JSONDecoder().decode(
            ServicesListResponse.self,
            from: Data(#"{"ok":true,"services":{"room-audio-server":{"ok":true,"running":true}}}"#.utf8)
        )
    }

    func scheduledJobs(_ endpoint: JarvisEndpoint) async throws -> ScheduledJobsResponse {
        scheduledJobsCalls += 1
        guard scheduledJobsSucceeds else { throw JarvisError.transport("simulated scheduled-job failure") }
        return try! JSONDecoder().decode(
            ScheduledJobsResponse.self,
            from: Data(#"{"ok":true,"summary":{"total":1,"enabled":1,"running":0,"errors":0},"jobs":[{"id":"job_demo","name":"demo","kind":"interval","schedule":"5m","enabled":true,"nextRunAt":null,"lastRunAt":null,"lastStatus":"success","runCount":1,"description":null}]}"#.utf8)
        )
    }

    func serviceAction(_ endpoint: JarvisEndpoint, name: String, action: String) async throws -> ServiceActionResult {
        try! JSONDecoder().decode(ServiceActionResult.self, from: Data(#"{"ok":true,"service":"test","action":"status"}"#.utf8))
    }

    func discover(_ candidates: [URL], timeout: TimeInterval) async -> URL? { candidates.first }
}
