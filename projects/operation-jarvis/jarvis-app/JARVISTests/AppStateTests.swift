import XCTest
import UIKit
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

        app.setActiveSection(.pi)
        try await Task.sleep(for: .milliseconds(50))
        let piCounts = (api.stateCalls, api.servicesCalls, api.scheduledJobsCalls, api.healthCalls)
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertEqual(api.stateCalls, piCounts.0)
        XCTAssertEqual(api.servicesCalls, piCounts.1)
        XCTAssertEqual(api.scheduledJobsCalls, piCounts.2)
        XCTAssertEqual(api.healthCalls, piCounts.3)

        app.setActiveSection(.settings)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertEqual(api.stateCalls, piCounts.0)
        XCTAssertEqual(api.servicesCalls, piCounts.1)
        XCTAssertEqual(api.scheduledJobsCalls, piCounts.2)
        XCTAssertEqual(api.healthCalls, piCounts.3)

        app.setActiveSection(.home)
        for _ in 0..<20 where api.stateCalls == piCounts.0 {
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertGreaterThan(api.stateCalls, piCounts.0)

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

    func testSiriPromptNormalizesAndDeliversOneAtomicReturnRequest() async {
        let configuration = WatchTerminalConfiguration(
            endpoint: "https://fixture.invalid:8792",
            token: String(repeating: "a", count: 64),
            certificateSHA256: String(repeating: "ab", count: 32)
        )
        var deliveredConfiguration: WatchTerminalConfiguration?
        var deliveredInput: WatchTerminalInput?

        let outcome = await JARVISSiriPromptRuntime.submit(
            "  inspect this\r\nonce  ",
            configurationLoader: { .configured(configuration) },
            delivery: { value, input in
                deliveredConfiguration = value
                deliveredInput = input
            }
        )

        XCTAssertEqual(outcome, .sent)
        XCTAssertEqual(deliveredConfiguration, configuration)
        XCTAssertEqual(deliveredInput?.data, Data("inspect this once".utf8))
        XCTAssertEqual(deliveredInput?.appendReturn, true)
    }

    func testSiriTerminalURLOnlyAcceptsTheTerminalDeepLink() {
        XCTAssertTrue(JARVISSiriNavigation.isTerminalURL(JARVISSiriNavigation.terminalURL))
        XCTAssertFalse(JARVISSiriNavigation.isTerminalURL(URL(string: "jarvis://settings")!))
        XCTAssertFalse(JARVISSiriNavigation.isTerminalURL(URL(string: "https://terminal")!))
    }

    func testSuccessfulSiriPromptNavigationRequestPersistsAndConsumesOnce() {
        let suite = "jarvis.siri-navigation.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = NotificationCenter()
        let posted = expectation(description: "terminal navigation posted")
        let token = center.addObserver(
            forName: JARVISSiriNavigation.terminalRequestNotification,
            object: nil,
            queue: nil
        ) { _ in
            posted.fulfill()
        }
        defer { center.removeObserver(token) }

        JARVISSiriNavigation.requestTerminalPresentation(
            defaults: defaults,
            notificationCenter: center
        )

        wait(for: [posted], timeout: 1)
        XCTAssertTrue(JARVISSiriNavigation.consumeTerminalPresentationRequest(defaults: defaults))
        XCTAssertFalse(JARVISSiriNavigation.consumeTerminalPresentationRequest(defaults: defaults))
    }

    func testSiriPromptFailsBeforeNetworkAndMapsAmbiguousSend() async {
        var loadedConfiguration = false
        var attemptedDelivery = false
        let emptyOutcome = await JARVISSiriPromptRuntime.submit(
            "\r\n",
            configurationLoader: {
                loadedConfiguration = true
                return .missing
            },
            delivery: { _, _ in attemptedDelivery = true }
        )
        XCTAssertEqual(emptyOutcome, .empty)
        XCTAssertFalse(loadedConfiguration)
        XCTAssertFalse(attemptedDelivery)

        let configuration = WatchTerminalConfiguration(
            endpoint: "https://fixture.invalid:8792",
            token: String(repeating: "a", count: 64),
            certificateSHA256: String(repeating: "ab", count: 32)
        )
        let uncertainOutcome = await JARVISSiriPromptRuntime.submit(
            "send once",
            configurationLoader: { .configured(configuration) },
            delivery: { _, _ in throw WatchTerminalClientError.submissionUnconfirmed }
        )
        XCTAssertEqual(uncertainOutcome, .unconfirmed)
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

    func testPiTerminalContractUsesPersistentTmuxBootstrap() {
        XCTAssertEqual(AppSection(rawValue: "pi"), .pi)
        XCTAssertEqual(
            PiTerminalConfiguration.remoteCommand,
            "/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app/scripts/jarvis-mobile-terminal.sh"
        )
        XCTAssertFalse(PiTerminalConfiguration.remoteCommand.contains("kill-session"))
    }

    func testPiTerminalMigratesLegacyZoomAndPreservesLaterPinchChanges() {
        XCTAssertEqual(PiTerminalPresentation.resolvedFontSize(savedValue: 0, savedZoomSchema: 0), 18)
        XCTAssertEqual(PiTerminalPresentation.resolvedFontSize(savedValue: 12.5, savedZoomSchema: 0), 18)
        XCTAssertEqual(PiTerminalPresentation.resolvedFontSize(savedValue: 12.5, savedZoomSchema: 1), 12.5)
        XCTAssertEqual(PiTerminalPresentation.resolvedFontSize(savedValue: 4, savedZoomSchema: 1), 9)
        XCTAssertEqual(PiTerminalPresentation.resolvedFontSize(savedValue: 40, savedZoomSchema: 1), 20)
    }

    func testPiTerminalUsesUndecoratedBackspaceRepeatSentinel() throws {
        let terminalView = PiTerminalHostView(frame: .zero)
        XCTAssertEqual(terminalView.keyboardDismissMode, .interactive)
        XCTAssertEqual(terminalView.autocorrectionType, .no)
        XCTAssertFalse(terminalView.isFirstResponder)

        terminalView.ensureBackspaceAutoRepeatSentinel()
        XCTAssertTrue(terminalView.hasText)
        XCTAssertNil(terminalView.markedTextRange, "Marked text makes UIKit draw dotted rows over SwiftTerm")
        let initialRange = try XCTUnwrap(
            terminalView.textRange(from: terminalView.beginningOfDocument, to: terminalView.endOfDocument)
        )
        XCTAssertEqual(terminalView.text(in: initialRange), PiTerminalKeyboard.backspaceRepeatSentinel)

        terminalView.deleteBackward()
        XCTAssertTrue(terminalView.hasText)
        XCTAssertNil(terminalView.markedTextRange)
        let repeatedRange = try XCTUnwrap(
            terminalView.textRange(from: terminalView.beginningOfDocument, to: terminalView.endOfDocument)
        )
        XCTAssertEqual(terminalView.text(in: repeatedRange), PiTerminalKeyboard.backspaceRepeatSentinel)
    }

    func testPiTerminalPrioritizesTouchScrollingAndProvidesSlashShortcut() {
        let terminalView = PiTerminalHostView(frame: .zero)
        XCTAssertFalse(terminalView.allowMouseReporting)
        XCTAssertTrue(terminalView.alwaysBounceVertical)
        XCTAssertTrue(terminalView.isDirectionalLockEnabled)
        XCTAssertEqual(PiTerminalKeyDeck.slashBytes, [0x2f])
        XCTAssertEqual(PiTerminalTouchScroll.pointsPerWheelStep(fontSize: 18), 45)
        XCTAssertEqual(PiTerminalTouchScroll.pointsPerWheelStep(fontSize: 9), 36)
        XCTAssertEqual(PiTerminalTouchScroll.deliveryFramesPerSecond, 60)
        XCTAssertEqual(PiTerminalTouchScroll.pendingSteps(after: 0, scrollingUp: true), 1)
        XCTAssertEqual(PiTerminalTouchScroll.pendingSteps(after: 7, scrollingUp: true), 8)
        XCTAssertEqual(PiTerminalTouchScroll.pendingSteps(after: 8, scrollingUp: true), 8)
        XCTAssertEqual(PiTerminalTouchScroll.pendingSteps(after: 4, scrollingUp: false), -1)
        XCTAssertEqual(PiTerminalTouchScroll.pendingSteps(after: -7, scrollingUp: false), -8)
        XCTAssertEqual(PiTerminalTouchScroll.pendingSteps(after: -8, scrollingUp: false), -8)
        let cursorLocation = PiTerminalTouchScroll.cursorLocation(column: 7, row: 11, columns: 48, rows: 28)
        XCTAssertEqual(cursorLocation.column, 8)
        XCTAssertEqual(cursorLocation.row, 12)
        let clampedCursorLocation = PiTerminalTouchScroll.cursorLocation(column: 99, row: -2, columns: 48, rows: 28)
        XCTAssertEqual(clampedCursorLocation.column, 48)
        XCTAssertEqual(clampedCursorLocation.row, 1)
        XCTAssertEqual(
            String(bytes: PiTerminalTouchScroll.wheelBytes(scrollingUp: true, column: 8, row: 12), encoding: .utf8),
            "\u{1b}[<64;8;12M"
        )
        XCTAssertEqual(
            String(bytes: PiTerminalTouchScroll.wheelBytes(scrollingUp: false, column: 8, row: 12), encoding: .utf8),
            "\u{1b}[<65;8;12M"
        )

        let multiTapRecognizers = (terminalView.gestureRecognizers ?? []).compactMap { $0 as? UITapGestureRecognizer }
            .filter { $0.numberOfTapsRequired > 1 }
        let longPressRecognizers = (terminalView.gestureRecognizers ?? []).compactMap { $0 as? UILongPressGestureRecognizer }
        XCTAssertFalse(multiTapRecognizers.isEmpty)
        XCTAssertFalse(longPressRecognizers.isEmpty)
        XCTAssertTrue(multiTapRecognizers.allSatisfy { !$0.isEnabled })
        XCTAssertTrue(longPressRecognizers.allSatisfy { !$0.isEnabled })

        let panCountBeforeMouseMode = (terminalView.gestureRecognizers ?? []).filter { $0 is UIPanGestureRecognizer }.count
        let mouseModeSequence = Array("\u{1b}[?1002h".utf8)
        terminalView.feed(byteArray: mouseModeSequence[...])
        XCTAssertTrue(terminalView.isRoutingTouchScrollToPi)
        let panCountAfterMouseMode = (terminalView.gestureRecognizers ?? []).filter { $0 is UIPanGestureRecognizer }.count
        XCTAssertEqual(panCountAfterMouseMode, panCountBeforeMouseMode)
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
