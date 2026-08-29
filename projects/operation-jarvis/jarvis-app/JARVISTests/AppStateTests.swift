import XCTest
import UIKit
@testable import JARVIS
import JARVISKit

@MainActor
final class AppStateTests: XCTestCase {
    func testISO8601ParsingSupportsPlainAndFractionalTimestampsWithoutSharedMutableFormatter() throws {
        let plain = try XCTUnwrap(JarvisFormat.parseISO8601("2026-08-29T12:34:56Z"))
        let fractional = try XCTUnwrap(JarvisFormat.parseISO8601("2026-08-29T12:34:56.250Z"))
        let offset = try XCTUnwrap(JarvisFormat.parseISO8601("2026-08-29T08:34:56-04:00"))

        XCTAssertEqual(fractional.timeIntervalSince(plain), 0.25, accuracy: 0.000_001)
        XCTAssertEqual(offset, plain)
        XCTAssertNil(JarvisFormat.parseISO8601("not-an-iso8601-timestamp"))
    }

    func testStreamlinedSettingsSigningSummaryUsesBoundedDayAndHourPrecision() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)

        XCTAssertEqual(
            SettingsPresentation.signingCountdown(
                to: now.addingTimeInterval(2 * 86_400 + 3 * 3_600),
                at: now
            ),
            "2d 3h remaining"
        )
        XCTAssertEqual(
            SettingsPresentation.signingCountdown(
                to: now.addingTimeInterval(5 * 3_600 + 7 * 60),
                at: now
            ),
            "5h 7m remaining"
        )
        XCTAssertEqual(SettingsPresentation.signingCountdown(to: now, at: now), "Expired")
    }

    func testProvisioningStatusUsesEarliestOfAllFourEmbeddedProfiles() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let relativePaths = [
            "embedded.mobileprovision",
            "PlugIns/JARVISWidget.appex/embedded.mobileprovision",
            "Watch/JARVISWatch.app/embedded.mobileprovision",
            "Watch/JARVISWatch.app/PlugIns/JARVISWatchWidget.appex/embedded.mobileprovision",
        ]
        let base = Date(timeIntervalSince1970: 1_800_000_000)
        for (index, bundleIdentifier) in LocalSigningStatus.expectedBundleIdentifiers.enumerated() {
            let destination = root.appendingPathComponent(relativePaths[index])
            try FileManager.default.createDirectory(
                at: destination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let payload: [String: Any] = [
                "UUID": "profile-\(index)",
                "ExpirationDate": base.addingTimeInterval(Double(index) * 3_600),
                "Entitlements": ["application-identifier": "5GB5BU49Q8.\(bundleIdentifier)"],
            ]
            let plist = try PropertyListSerialization.data(fromPropertyList: payload, format: .xml, options: 0)
            var wrapped = Data("signed-prefix".utf8)
            wrapped.append(plist)
            wrapped.append(Data("signed-suffix".utf8))
            try wrapped.write(to: destination)
        }

        let status = LocalSigningStatus.current(bundleURL: root)

        XCTAssertTrue(status.hasAllExpectedProfiles)
        XCTAssertEqual(status.profiles.count, 4)
        XCTAssertEqual(status.earliestExpiration, base)
    }

    func testSigningRenewalStatusAndStartUseDedicatedAPI() async {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(store: store, client: api)

        await app.fetchSigningRenewalStatus()
        let started = await app.startSigningRenewal()

        XCTAssertEqual(api.signingStatusCalls, 1)
        XCTAssertEqual(api.signingStartCalls, 1)
        XCTAssertTrue(started)
        XCTAssertEqual(app.signingRenewalStatus?.phase, "queued")
        XCTAssertNil(app.signingRenewalErrorMessage)
    }

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

    func testWatchPurifierRelayUsesClosedCommandAndConfirmsFreshState() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(store: store, client: api)
        let requestID = "purifier-power-request"

        app.watchBridgeDidReceivePurifierCommand(
            .shared,
            command: .power(true),
            requestID: requestID
        )
        for _ in 0..<40 where app.watchCommandResponses[requestID] == nil {
            try await Task.sleep(for: .milliseconds(25))
        }

        XCTAssertEqual(api.commands, ["purifier-set"])
        XCTAssertEqual(api.commandParams.first?["setting"], .string("power"))
        XCTAssertEqual(api.commandParams.first?["value"], .string("on"))
        XCTAssertEqual(app.watchCommandResponses[requestID]?.result?.ok, true)
        XCTAssertNil(app.watchCommandResponses[requestID]?.error)
        XCTAssertEqual(app.lastState?.subsystems?.purifier?.isOn, true)
        XCTAssertTrue(app.watchCommandInFlight.isEmpty)
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

    func testPiTerminalUsesIsolatedKeyboardProxyForBackspaceRepeat() {
        let terminalView = PiTerminalHostView(frame: .zero)
        XCTAssertEqual(terminalView.keyboardDismissMode, .interactive)
        XCTAssertEqual(terminalView.autocorrectionType, .no)
        XCTAssertFalse(terminalView.hasText)
        XCTAssertNil(terminalView.markedTextRange, "SwiftTerm must not retain text that UIKit can decorate")

        let responder = PiTerminalKeyboardResponder()
        var insertedText: [String] = []
        var deleteCount = 0
        responder.insertTextHandler = { insertedText.append($0) }
        responder.deleteBackwardHandler = { deleteCount += 1 }

        responder.insertText("hello")
        for _ in 0..<20 { responder.deleteBackward() }

        XCTAssertEqual(insertedText, ["hello"])
        XCTAssertEqual(deleteCount, 20)
        XCTAssertTrue(responder.hasText, "Backspace auto-repeat must remain enabled")
        XCTAssertEqual(responder.text, PiTerminalKeyboard.proxyBufferSentinel)
        XCTAssertNil(responder.markedTextRange)
    }

    func testPiTerminalResetsStaleAlternateScreenBeforeFreshConnection() {
        let terminalView = PiTerminalHostView(frame: .zero)
        let staleGrid = Array(("\u{1b}[?1049h" + String(repeating: ".", count: 24)).utf8)
        terminalView.feed(byteArray: staleGrid[...])

        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 0, row: 0), Character("."))
        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 23, row: 0), Character("."))

        terminalView.prepareTerminalForFreshConnection()

        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 0, row: 0), Character("\u{0}"))
        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 23, row: 0), Character("\u{0}"))
    }

    func testPiTerminalRetainsLayoutResizeUntilSSHSessionIsReady() {
        let initial = PiTerminalWindowSize(cols: 80, rows: 25)!
        let windowState = PiTerminalWindowState(initial: initial)

        XCTAssertEqual(windowState.update(cols: 48, rows: 42), PiTerminalWindowSize(cols: 48, rows: 42))
        XCTAssertEqual(windowState.snapshot(), PiTerminalWindowSize(cols: 48, rows: 42))
        XCTAssertNil(windowState.update(cols: 0, rows: 42))
        XCTAssertEqual(
            windowState.snapshot(),
            PiTerminalWindowSize(cols: 48, rows: 42),
            "An invalid transient layout must not replace the latest usable PTY size"
        )
    }

    func testPiTerminalUsesImmediateFixedStepPiScrollingAndProvidesSlashShortcut() {
        let terminalView = PiTerminalHostView(frame: CGRect(x: 0, y: 0, width: 390, height: 360))
        terminalView.layoutIfNeeded()

        XCTAssertFalse(terminalView.allowMouseReporting)
        XCTAssertFalse(terminalView.panGestureRecognizer.isEnabled)
        XCTAssertFalse(terminalView.alwaysBounceVertical)
        XCTAssertFalse(terminalView.bounces)
        XCTAssertTrue(terminalView.isDirectionalLockEnabled)
        XCTAssertEqual(PiTerminalKeyDeck.slashBytes, [0x2f])
        XCTAssertEqual(PiTerminalTouchScroll.pointsPerWheelStep(fontSize: 18), 45)
        XCTAssertEqual(PiTerminalTouchScroll.pointsPerWheelStep(fontSize: 9), 36)

        let cursorLocation = PiTerminalTouchScroll.cursorLocation(
            column: 7,
            row: 11,
            columns: 48,
            rows: 28
        )
        XCTAssertEqual(cursorLocation.column, 8)
        XCTAssertEqual(cursorLocation.row, 12)
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

        var outboundBytes: [UInt8] = []
        terminalView.outboundBytesObserver = { outboundBytes.append(contentsOf: $0) }
        terminalView.sendAccessoryBytes(PiTerminalKeyDeck.slashBytes)
        XCTAssertEqual(outboundBytes, PiTerminalKeyDeck.slashBytes)
        outboundBytes.removeAll()

        terminalView.feed(byteArray: Array("\u{1b}[?1002h".utf8)[...])
        XCTAssertTrue(terminalView.isRoutingTouchScrollToPi)
        terminalView.sendTouchScrollStep(scrollingUp: true, column: 8, row: 12)
        XCTAssertEqual(outboundBytes, PiTerminalTouchScroll.wheelBytes(scrollingUp: true, column: 8, row: 12))
        outboundBytes.removeAll()

        terminalView.sendTouchScrollStep(scrollingUp: false, column: 8, row: 12)
        XCTAssertEqual(outboundBytes, PiTerminalTouchScroll.wheelBytes(scrollingUp: false, column: 8, row: 12))
        outboundBytes.removeAll()

        terminalView.feed(byteArray: Array("\u{1b}[?1002l".utf8)[...])
        XCTAssertFalse(terminalView.isRoutingTouchScrollToPi)
        terminalView.sendTouchScrollStep(scrollingUp: true, column: 8, row: 12)
        XCTAssertTrue(outboundBytes.isEmpty, "No wheel byte may be retained or sent after Pi disables mouse mode")
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
    let commandSucceeds: Bool
    let commandDelay: Duration?
    let scheduledJobsSucceeds: Bool
    var commands: [String] = []
    var commandParams: [[String: JSONValue]] = []
    var stateCalls = 0
    var healthCalls = 0
    var servicesCalls = 0
    var scheduledJobsCalls = 0
    var signingStatusCalls = 0
    var signingStartCalls = 0
    private var purifierIsOn = false
    private var purifierMode = "auto"
    private var purifierFan = 2

    private var state: StateSnapshot {
        try! JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(
                #"{"ok":true,"stale":false,"summary":{"plugsOn":1,"plugsTotal":2,"purifierOn":\#(purifierIsOn)},"subsystems":{"plugs":{"ok":true,"stale":false,"plugs":{"lamp":{"ok":true,"stale":false,"isOn":false},"tv":{"ok":true,"stale":false,"isOn":true}}},"purifier":{"ok":true,"stale":false,"isOn":\#(purifierIsOn),"mode":"\#(purifierMode)","fanLevel":\#(purifierFan),"fanSetLevel":\#(purifierFan),"pm25":3}}}"#.utf8
            )
        )
    }

    init(
        commandSucceeds: Bool = true,
        commandDelay: Duration? = nil,
        scheduledJobsSucceeds: Bool = true
    ) {
        self.commandSucceeds = commandSucceeds
        self.commandDelay = commandDelay
        self.scheduledJobsSucceeds = scheduledJobsSucceeds
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
        commandParams.append(params ?? [:])
        if commandSucceeds, action == "purifier-set", case .string(let setting)? = params?["setting"] {
            switch setting {
            case "power":
                if case .string(let value)? = params?["value"] { purifierIsOn = value == "on" }
            case "mode":
                if case .string(let value)? = params?["value"] { purifierMode = value }
            case "speed":
                if case .number(let value)? = params?["level"] {
                    purifierMode = "manual"
                    purifierFan = Int(value)
                }
            default:
                break
            }
        }
        return CommandResult(
            ok: commandSucceeds,
            action: action,
            error: commandSucceeds ? nil : "simulated failure",
            plug: commandSucceeds && action.hasPrefix("plug-")
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

    func signingRenewalStatus(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus {
        signingStatusCalls += 1
        return SigningRenewalStatus(ok: true, available: true, phase: "idle", running: false)
    }

    func startSigningRenewal(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus {
        signingStartCalls += 1
        return SigningRenewalStatus(ok: true, available: true, phase: "queued", running: true)
    }

    func discover(_ candidates: [URL], timeout: TimeInterval) async -> URL? { candidates.first }
}
