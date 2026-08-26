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

    func testPiTerminalOutputFilterSuppressesOnlyFragmentedTmuxAlternateScreenEnvelope() {
        var filter = PiTerminalOutputFilter()
        var output: [UInt8] = []

        for chunk in ["before\u{1b}[?104", "9hmiddle\u{1b}[?1049", "lafter\u{1b}[?1048h"] {
            let batch = filter.consume(Array(chunk.utf8), terminalRows: 42)
            for segment in batch.segments {
                guard case .bytes(let bytes) = segment else {
                    XCTFail("The alternate-screen envelope must not synthesize a scroll")
                    continue
                }
                output.append(contentsOf: bytes)
            }
        }

        XCTAssertEqual(String(decoding: output, as: UTF8.self), "beforemiddleafter\u{1b}[?1048h")
    }

    func testPiTerminalControlSequenceDiagnosticsCountsFragmentedOperationsWithoutContent() {
        var diagnostics = PiTerminalControlSequenceDiagnostics()
        diagnostics.consume(Array("ignored\u{1b}]0;not-recorded\u{1b}".utf8), terminalRows: 42)
        diagnostics.consume(Array("\\\n\u{1b}D\u{1b}[2;40r\u{1b}[3M\u{1b}[2S".utf8), terminalRows: 42)
        diagnostics.consume(Array("\u{1b}[H\u{1b}[12d\u{1b}[2J\u{1b}[K".utf8) + [0x9b] + Array("4L".utf8), terminalRows: 42)

        XCTAssertEqual(
            diagnostics.counts,
            PiTerminalControlSequenceCounts(
                lineFeeds: 1,
                indexes: 1,
                csiSequences: 8,
                c1CSIBytes: 1,
                scrollUpCommands: 1,
                scrollUpRows: 2,
                deleteLineCommands: 1,
                deleteLineRows: 3,
                insertLineCommands: 1,
                eraseDisplayCommands: 1,
                eraseLineCommands: 1,
                cursorPositionCommands: 1,
                verticalPositionCommands: 1,
                scrollRegionCommands: 1,
                restrictedScrollRegionCommands: 1
            )
        )
    }

    func testPiTerminalHistoryMetadataParserAndPromotionStateAreFragmentSafe() {
        var parser = PiTerminalHistorySizeParser()
        XCTAssertEqual(parser.consume(Array("28\n3".utf8)), [28])
        XCTAssertEqual(parser.consume(Array("1\r\nnot-a-count\n32\n".utf8)), [31, 32])

        var state = PiTerminalHistoryPromotionState()
        XCTAssertEqual(state.observe(historySize: 283), 0, "The first read-only count is a baseline, not old history")
        XCTAssertEqual(state.observe(historySize: 284), 1)
        XCTAssertEqual(state.observe(historySize: 287), 3)
        XCTAssertEqual(state.observe(historySize: 12), 0, "A server-side clear must not rewind local history")
        state.rebaseline(historySize: 40)
        XCTAssertEqual(state.observe(historySize: 42), 2)
        state.reset()
        XCTAssertNil(state.latestHistorySize)
        XCTAssertEqual(
            PiTerminalHistoryMonitor.remoteCommand.contains("capture-pane"),
            false,
            "The metadata channel must never retrieve terminal text"
        )
        XCTAssertFalse(PiTerminalHistoryMonitor.remoteCommand.contains("send-keys"))
    }

    func testPiTerminalPromotesReadOnlyTmuxHistoryDeltaBeforeCursorAddressedRedraw() {
        let terminalView = PiTerminalHostView(frame: CGRect(x: 0, y: 0, width: 390, height: 360))
        terminalView.layoutIfNeeded()
        terminalView.getTerminal().resize(cols: 12, rows: 4)
        var outboundBytes: [UInt8] = []
        terminalView.outboundBytesObserver = { outboundBytes.append(contentsOf: $0) }

        let initialScreen = "\u{1b}[1;4r\u{1b}[1;1Hold-0\u{1b}[2;1Hold-1\u{1b}[3;1Hold-2\u{1b}[4;1Hold-3"
        terminalView.consumeRemoteOutput(Array(initialScreen.utf8))
        let cursorAddressedRedraw = "\u{1b}[1;1Hnew-0\u{1b}[K\u{1b}[2;1Hnew-1\u{1b}[K\u{1b}[3;1Hnew-2\u{1b}[K\u{1b}[4;1Hnew-3\u{1b}[K"
        terminalView.consumeRemoteOutput(Array(cursorAddressedRedraw.utf8), historyRows: 2)

        let retained = String(
            decoding: terminalView.getTerminal().getBufferAsData(kind: .normal),
            as: UTF8.self
        )
        XCTAssertEqual(retained.filter { $0 == "\n" }.count, 6)
        XCTAssertTrue(retained.contains("old-0"))
        XCTAssertTrue(retained.contains("old-1"))
        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 0, row: 0), Character("n"))
        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 4, row: 0), Character("0"))
        XCTAssertTrue(outboundBytes.isEmpty, "Read-only history metadata must never emit terminal input")
    }

    func testPiTerminalOutputFilterLeavesRestrictedRegionScrollUpUntouched() {
        var filter = PiTerminalOutputFilter()
        let bytes = Array("\u{1b}[2;4r\u{1b}[2S".utf8)
        let batch = filter.consume(bytes, terminalRows: 4)

        XCTAssertEqual(batch.segments, [.bytes(bytes)])
    }

    func testPiTerminalPromotesFragmentedFullScreenTmuxScrollUpIntoLocalHistory() {
        let terminalView = PiTerminalHostView(frame: CGRect(x: 0, y: 0, width: 390, height: 360))
        terminalView.layoutIfNeeded()
        terminalView.getTerminal().resize(cols: 12, rows: 4)
        var outboundBytes: [UInt8] = []
        terminalView.outboundBytesObserver = { outboundBytes.append(contentsOf: $0) }

        let initialScreen = "\u{1b}[1;4r\u{1b}[1;1Hrow-0\u{1b}[2;1Hrow-1\u{1b}[3;1Hrow-2\u{1b}[4;1Hrow-3"
        terminalView.consumeRemoteOutput(Array(initialScreen.utf8))
        XCTAssertEqual(
            terminalView.getTerminal().getBufferAsData(kind: .normal).reduce(0) { $1 == 0x0a ? $0 + 1 : $0 },
            4
        )

        terminalView.consumeRemoteOutput(Array("\u{1b}[2".utf8))
        terminalView.consumeRemoteOutput(Array("S".utf8))

        let retained = String(
            decoding: terminalView.getTerminal().getBufferAsData(kind: .normal),
            as: UTF8.self
        )
        XCTAssertEqual(retained.filter { $0 == "\n" }.count, 6)
        XCTAssertTrue(retained.contains("row-0"))
        XCTAssertTrue(retained.contains("row-1"))
        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 0, row: 0), Character("r"))
        XCTAssertEqual(terminalView.getTerminal().getCharacter(col: 4, row: 0), Character("2"))
        XCTAssertTrue(outboundBytes.isEmpty, "Promoting tmux's full-screen SU must emit zero terminal input")
    }

    func testPiTerminalUsesNativeReadOnlyTextScrollingAndProvidesSlashShortcut() {
        let terminalView = PiTerminalHostView(frame: CGRect(x: 0, y: 0, width: 390, height: 360))
        terminalView.layoutIfNeeded()

        XCTAssertFalse(terminalView.allowMouseReporting)
        XCTAssertTrue(terminalView.isScrollEnabled)
        XCTAssertTrue(terminalView.alwaysBounceVertical)
        XCTAssertTrue(terminalView.isDirectionalLockEnabled)
        XCTAssertEqual(terminalView.decelerationRate, .normal)
        XCTAssertTrue(terminalView.panGestureRecognizer.view === terminalView)
        XCTAssertEqual(terminalView.getTerminal().options.scrollback, PiTerminalPresentation.localScrollbackLines)
        XCTAssertEqual(PiTerminalKeyDeck.slashBytes, [0x2f])

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
        XCTAssertEqual(outboundBytes, PiTerminalKeyDeck.slashBytes, "The outbound test observer must see real terminal input")
        outboundBytes.removeAll()

        let panCountBeforeMouseMode = (terminalView.gestureRecognizers ?? []).filter { $0 is UIPanGestureRecognizer }.count
        XCTAssertEqual(
            panCountBeforeMouseMode,
            1,
            "Keyboard dismissal must observe UIScrollView's native pan instead of competing with a second pan recognizer"
        )
        terminalView.consumeRemoteOutput(Array("\u{1b}[?10".utf8))
        terminalView.consumeRemoteOutput(Array("49h\u{1b}[22;0;0t\u{1b}[H\u{1b}[2J\u{1b}[?1002h\u{1b}[?1006h".utf8))
        XCTAssertFalse(
            terminalView.getTerminal().isCurrentBufferAlternate,
            "tmux's outer DECSET 1049 wrapper must not move local rendering into SwiftTerm's history-free alternate buffer"
        )
        let panCountAfterMouseMode = (terminalView.gestureRecognizers ?? []).filter { $0 is UIPanGestureRecognizer }.count
        XCTAssertEqual(panCountAfterMouseMode, panCountBeforeMouseMode)

        let transcript = (0..<120).map { "native-scroll-row-\($0)\r\n" }.joined()
        terminalView.consumeRemoteOutput(Array(transcript.utf8))
        terminalView.consumeRemoteOutput(Array("\u{1b}[?1049l".utf8))
        terminalView.layoutIfNeeded()
        XCTAssertFalse(terminalView.getTerminal().isCurrentBufferAlternate)
        XCTAssertGreaterThan(terminalView.contentSize.height, terminalView.bounds.height)

        let maximumDisplayRow = max(
            0,
            terminalView.getTerminal().getBufferAsData(kind: .normal).split(separator: 0x0a).count
                - terminalView.getTerminal().rows
        )
        let historyRow = max(0, maximumDisplayRow - 8)
        terminalView.scrollTo(row: historyRow)
        let historyOffset = terminalView.contentOffset.y
        terminalView.consumeRemoteOutput(Array("new-output-while-reading\r\nnew-output-while-reading\r\n".utf8))

        XCTAssertEqual(terminalView.getTerminal().buffer.yDisp, historyRow)
        XCTAssertEqual(
            terminalView.contentOffset.y,
            historyOffset,
            accuracy: 0.01,
            "SwiftTerm must preserve its native viewport while history is being read"
        )

        terminalView.scrollTo(row: Int.max)
        terminalView.consumeRemoteOutput(Array("new-output-at-live-edge\r\nnew-output-at-live-edge\r\n".utf8))
        let liveEdgeAfterAppend = max(0, terminalView.contentSize.height - terminalView.bounds.height)
        XCTAssertEqual(
            terminalView.contentOffset.y,
            liveEdgeAfterAppend,
            accuracy: 0.01,
            "SwiftTerm must continue following when its native viewport was already at the live edge"
        )
        XCTAssertTrue(outboundBytes.isEmpty, "Local native scrolling must never emit terminal input")
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
