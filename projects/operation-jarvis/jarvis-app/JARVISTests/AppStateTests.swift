import XCTest
import UIKit
@testable import JARVIS
import JARVISKit

@MainActor
final class AppStateTests: XCTestCase {
    func testPiSessionIndicatorsPresentEveryLifecycleAndFailClosedUnknown() {
        let expected: [(PiSessionLifecycle, String, PiSessionIndicatorTone)] = [
            (.offline, "Offline", .offline),
            (.idle, "Idle", .idle),
            (.running, "Running", .running),
            (.waiting, "Waiting", .waiting),
            (.compacting, "Compacting", .compacting),
            (.unknown, "Unknown", .unknown),
        ]

        for (lifecycle, label, tone) in expected {
            let presentation = PiSessionIndicatorPresentation(lifecycle: lifecycle)
            XCTAssertEqual(presentation.label, label)
            XCTAssertEqual(presentation.tone, tone)
        }
    }

    func testPeriodicSchedulerIsScheduledAndAvailableBetweenLaunchdRuns() throws {
        let response = try JSONDecoder().decode(
            ServicesListResponse.self,
            from: Data(
                #"{"ok":true,"services":{"room-audio-server":{"ok":true,"loaded":true,"running":true},"jobs-scheduler":{"ok":true,"loaded":true,"running":false,"configured":true,"allowedActions":[]}}}"#.utf8
            )
        )
        let services = response.services.map { (name: $0.key, service: $0.value) }
        let scheduler = try XCTUnwrap(response.services["jobs-scheduler"])

        XCTAssertEqual(
            RuntimeServicePresentation.state(name: "jobs-scheduler", service: scheduler),
            .scheduled
        )
        XCTAssertEqual(
            RuntimeServicePresentation.summary(servicesLoaded: true, services: services),
            "2 of 2 available"
        )
    }

    func testPeriodicSchedulerStillFailsClosedWhenUnavailable() throws {
        let response = try JSONDecoder().decode(
            ServicesListResponse.self,
            from: Data(
                #"{"ok":true,"services":{"jobs-scheduler":{"ok":false,"loaded":null,"running":null,"error":"launchctl probe failed"}}}"#.utf8
            )
        )
        let scheduler = try XCTUnwrap(response.services["jobs-scheduler"])

        XCTAssertEqual(
            RuntimeServicePresentation.state(name: "jobs-scheduler", service: scheduler),
            .unknown
        )
        XCTAssertEqual(
            RuntimeServicePresentation.summary(
                servicesLoaded: true,
                services: [(name: "jobs-scheduler", service: scheduler)]
            ),
            "0 of 1 available"
        )
    }

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
        XCTAssertEqual(api.codexRefreshCalls, 1)
        XCTAssertFalse(app.isStateLoading)
    }

    func testRoutineStateReadKeepsFreshControlsAvailable() async throws {
        let api = FakeAPI(stateDelay: .milliseconds(100))
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(store: store, client: api)

        await app.fetchState()
        let refresh = Task { await app.fetchState() }
        try await Task.sleep(for: .milliseconds(25))

        XCTAssertTrue(app.isStateLoading)
        XCTAssertFalse(app.isAwaitingFreshState)
        XCTAssertEqual(app.lastState?.stale, false)
        await refresh.value
    }

    func testStateFetchConvergesBoundedStaleRefreshingSnapshot() async {
        let staleRefreshing = StateSnapshot(ok: true, refreshing: true, stale: true)
        let fresh = StateSnapshot(ok: true, refreshing: false, stale: false)
        let api = FakeAPI(stateResponses: [staleRefreshing, fresh])
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(
            store: store,
            client: api,
            staleConvergenceInterval: .zero,
            staleConvergenceAttempts: 2
        )

        await app.fetchState()

        XCTAssertEqual(api.stateCalls, 2)
        XCTAssertEqual(app.lastState?.stale, false)
        XCTAssertEqual(app.lastState?.refreshing, false)
        XCTAssertFalse(app.isAwaitingFreshState)
        XCTAssertFalse(app.isStateLoading)
    }

    func testStateFetchDoesNotRetryCompletedStaleSnapshot() async {
        let completedStale = StateSnapshot(ok: true, refreshing: false, stale: true)
        let fresh = StateSnapshot(ok: true, refreshing: false, stale: false)
        let api = FakeAPI(stateResponses: [completedStale, fresh])
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(
            store: store,
            client: api,
            staleConvergenceInterval: .zero,
            staleConvergenceAttempts: 2
        )

        await app.fetchState()

        XCTAssertEqual(api.stateCalls, 1)
        XCTAssertEqual(app.lastState?.stale, true)
        XCTAssertEqual(app.lastState?.refreshing, false)
        XCTAssertFalse(app.isAwaitingFreshState)
    }

    func testStateFetchBoundsStillRefreshingFollowUps() async {
        let staleRefreshing = StateSnapshot(ok: true, refreshing: true, stale: true)
        let api = FakeAPI(stateResponses: [staleRefreshing, staleRefreshing, staleRefreshing])
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        store.endpointURLString = "http://fake.jarvis:8790"
        let app = AppState(
            store: store,
            client: api,
            staleConvergenceInterval: .zero,
            staleConvergenceAttempts: 2
        )

        await app.fetchState()

        XCTAssertEqual(api.stateCalls, 3)
        XCTAssertEqual(app.lastState?.stale, true)
        XCTAssertEqual(app.lastState?.refreshing, true)
        XCTAssertFalse(app.isAwaitingFreshState, "routine convergence must not globally block usable controls")
        XCTAssertFalse(app.isStateLoading)
    }

    func testCachedStatePollingContinuesAcrossActiveTabsWhileServicesStayHomeOnly() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.appstate.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(
            store: store,
            client: api,
            activeRefreshInterval: .milliseconds(100),
            controlRefreshInterval: .milliseconds(100)
        )
        app.endpointDraft = "http://fake.jarvis:8790"

        app.sceneDidBecomeActive()
        for _ in 0..<40 where api.stateCalls < 2 || api.servicesCalls < 2 || api.scheduledJobsCalls < 2 || api.scheduledJobResultsCalls < 2 {
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertGreaterThanOrEqual(api.stateCalls, 2)
        XCTAssertGreaterThan(api.stateCalls, api.servicesCalls, "visible controls should poll faster than heavy Home resources")
        XCTAssertEqual(api.servicesCalls, api.scheduledJobsCalls)
        XCTAssertEqual(api.servicesCalls, api.scheduledJobResultsCalls)

        app.setActiveSection(.pi)
        try await Task.sleep(for: .milliseconds(50))
        let piCounts = (api.stateCalls, api.servicesCalls, api.scheduledJobsCalls, api.scheduledJobResultsCalls, api.healthCalls)
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertGreaterThan(api.stateCalls, piCounts.0)
        XCTAssertEqual(api.servicesCalls, piCounts.1)
        XCTAssertGreaterThan(api.scheduledJobsCalls, piCounts.2)
        XCTAssertGreaterThan(api.scheduledJobResultsCalls, piCounts.3)
        XCTAssertEqual(api.scheduledJobsCalls, api.scheduledJobResultsCalls)
        XCTAssertEqual(api.healthCalls, piCounts.4)

        app.setActiveSection(.settings)
        try await Task.sleep(for: .milliseconds(50))
        let settingsCounts = (api.stateCalls, api.servicesCalls, api.scheduledJobsCalls, api.scheduledJobResultsCalls, api.healthCalls)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertGreaterThan(api.stateCalls, settingsCounts.0)
        XCTAssertEqual(api.servicesCalls, settingsCounts.1)
        XCTAssertGreaterThan(api.scheduledJobsCalls, settingsCounts.2)
        XCTAssertGreaterThan(api.scheduledJobResultsCalls, settingsCounts.3)
        XCTAssertEqual(api.scheduledJobsCalls, api.scheduledJobResultsCalls)
        XCTAssertEqual(api.healthCalls, settingsCounts.4)

        app.setActiveSection(.home)
        for _ in 0..<20 where api.stateCalls == piCounts.0 {
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertGreaterThan(api.stateCalls, piCounts.0)

        app.sceneWillResignActive()
        try await Task.sleep(for: .milliseconds(50))
        let backgroundCounts = (api.stateCalls, api.servicesCalls, api.scheduledJobsCalls, api.scheduledJobResultsCalls, api.healthCalls)
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertEqual(api.stateCalls, backgroundCounts.0)
        XCTAssertEqual(api.servicesCalls, backgroundCounts.1)
        XCTAssertEqual(api.scheduledJobsCalls, backgroundCounts.2)
        XCTAssertEqual(api.scheduledJobResultsCalls, backgroundCounts.3)
        XCTAssertEqual(api.healthCalls, backgroundCounts.4)
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
        var deliveredSlot: JARVISTerminalSlot?
        var deliveredInput: WatchTerminalInput?

        let outcome = await JARVISSiriPromptRuntime.submit(
            "  inspect this\r\nonce  ",
            configurationLoader: { .configured(configuration) },
            slotLoader: { .three },
            delivery: { value, slot, input in
                deliveredConfiguration = value
                deliveredSlot = slot
                deliveredInput = input
            }
        )

        XCTAssertEqual(outcome, .sent)
        XCTAssertEqual(deliveredConfiguration, configuration)
        XCTAssertEqual(deliveredSlot, .three)
        XCTAssertEqual(deliveredInput?.sessionID, 3)
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
            delivery: { _, _, _ in attemptedDelivery = true }
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
            delivery: { _, _, _ in throw WatchTerminalClientError.submissionUnconfirmed }
        )
        XCTAssertEqual(uncertainOutcome, .unconfirmed)
    }

    func testScheduledResultFirstSyncBaselinesThenTracksAndPersistsUnread() async throws {
        let api = FakeAPI(scheduledJobResultSequence: 5)
        let defaults = UserDefaults(suiteName: "jarvis.results.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let cacheURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("jarvis-results-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: cacheURL) }
        let app = AppState(
            store: store,
            client: api,
            preferences: defaults,
            resultCacheURL: cacheURL
        )
        app.endpointDraft = "http://fake.jarvis:8790"

        await app.refresh()

        XCTAssertEqual(app.lastScheduledJobResults.map(\.sequence), [5])
        XCTAssertEqual(app.unreadScheduledJobResultCount, 0)

        api.scheduledJobResultSequence = 6
        await app.fetchScheduledJobResults()

        XCTAssertEqual(app.lastScheduledJobResults.map(\.sequence), [6, 5])
        XCTAssertEqual(app.unreadScheduledJobResultCount, 1)
        app.markScheduledJobResultsRead()
        XCTAssertEqual(app.unreadScheduledJobResultCount, 0)

        let restored = AppState(
            store: store,
            client: FakeAPI(),
            preferences: defaults,
            resultCacheURL: cacheURL
        )
        XCTAssertEqual(restored.lastScheduledJobResults.map(\.sequence), [6, 5])
        XCTAssertEqual(restored.unreadScheduledJobResultCount, 0)
    }

    func testJobsPollingRefreshesJobsWithoutPollingHomeState() async throws {
        let api = FakeAPI()
        let defaults = UserDefaults(suiteName: "jarvis.jobs-polling.\(UUID().uuidString)")!
        let store = EndpointStore(defaults: defaults)
        let app = AppState(
            store: store,
            client: api,
            activeRefreshInterval: .milliseconds(100),
            controlRefreshInterval: .milliseconds(100),
            preferences: defaults,
            resultCacheURL: FileManager.default.temporaryDirectory.appendingPathComponent("jarvis-jobs-polling-\(UUID().uuidString).json")
        )
        app.endpointDraft = "http://fake.jarvis:8790"
        app.sceneDidBecomeActive()
        for _ in 0..<40 where app.connectionState != .connected {
            try await Task.sleep(for: .milliseconds(25))
        }
        app.setActiveSection(.jobs)
        let stateCalls = api.stateCalls
        let serviceCalls = api.servicesCalls
        let initialJobCalls = api.scheduledJobsCalls
        for _ in 0..<20 where api.scheduledJobsCalls == initialJobCalls {
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertGreaterThan(api.scheduledJobsCalls, initialJobCalls)
        XCTAssertGreaterThan(api.scheduledJobResultsCalls, 0)
        XCTAssertEqual(api.stateCalls, stateCalls)
        XCTAssertEqual(api.servicesCalls, serviceCalls)
        app.sceneWillResignActive()
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
        XCTAssertEqual(
            PiTerminalConfiguration.remoteCommand(for: .one),
            PiTerminalConfiguration.remoteCommand + " --slot 1"
        )
        XCTAssertEqual(
            PiTerminalConfiguration.remoteCommand(for: .three),
            PiTerminalConfiguration.remoteCommand + " --slot 3"
        )
        XCTAssertEqual(
            PiTerminalConfiguration.remoteCommand(for: .six),
            PiTerminalConfiguration.remoteCommand + " --slot 6"
        )
        XCTAssertEqual(
            PiAttachmentProtocol.receiverCommand(for: .two),
            PiAttachmentProtocol.receiverCommand + " --slot 2"
        )
        XCTAssertEqual(
            PiAttachmentProtocol.receiverCommand(for: .six),
            PiAttachmentProtocol.receiverCommand + " --slot 6"
        )
    }

    func testTerminalSlotSelectionIsBoundedAndDeviceLocal() throws {
        let suite = "jarvis.terminal-slots.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        XCTAssertEqual(JARVISTerminalSlot.allCases.map(\.rawValue), [1, 2, 3, 4, 5, 6])
        XCTAssertEqual(JARVISTerminalSlot.load(from: defaults), .one)
        JARVISTerminalSlot.six.persist(to: defaults)
        XCTAssertEqual(JARVISTerminalSlot.load(from: defaults), .six)
        XCTAssertNil(JARVISTerminalSlot.one.previous)
        XCTAssertEqual(JARVISTerminalSlot.one.next, .two)
        XCTAssertEqual(JARVISTerminalSlot.three.next, .four)
        XCTAssertEqual(JARVISTerminalSlot.four.previous, .three)
        XCTAssertEqual(JARVISTerminalSlot.six.previous, .five)
        XCTAssertNil(JARVISTerminalSlot.six.next)
        XCTAssertNil(JARVISTerminalSlot(rawValue: 0))
        XCTAssertNil(JARVISTerminalSlot(rawValue: 7))
    }

    func testHomePiCardCanSelectAnExactDeviceLocalTerminalSlotBeforePresentation() throws {
        let suite = "jarvis.terminal-card-route.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let controller = PiTerminalController(
            settings: PiTerminalSettings(),
            slotDefaults: defaults
        )

        XCTAssertTrue(controller.selectSlot(.six))
        XCTAssertEqual(controller.selectedSlot, .six)
        XCTAssertEqual(JARVISTerminalSlot.load(from: defaults), .six)
        XCTAssertTrue(controller.selectSlot(.one))
        XCTAssertEqual(controller.selectedSlot, .one)
        XCTAssertEqual(JARVISTerminalSlot.load(from: defaults), .one)
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

    func testPiTerminalInputIsRearmedOnlyByTheExactFreshSession() {
        var state = PiTerminalInputTransitionState()
        XCTAssertFalse(state.acceptsInput(generation: 0))

        state.begin(generation: 1, keyboardWasFocused: true)
        XCTAssertNil(state.complete(generation: 0), "A stale PTY must not enable input or restore focus")
        XCTAssertFalse(state.acceptsInput(generation: 1))

        state.begin(generation: 2, keyboardWasFocused: false)
        XCTAssertNil(state.complete(generation: 1), "A superseded PTY must remain fail-closed")
        XCTAssertEqual(state.complete(generation: 2), false)
        XCTAssertTrue(state.acceptsInput(generation: 2))
        XCTAssertNil(state.complete(generation: 2), "Readiness completion is one-shot")

        state.invalidate()
        XCTAssertFalse(state.acceptsInput(generation: 2))
        state.begin(generation: 3, keyboardWasFocused: true)
        XCTAssertEqual(state.complete(generation: 3), true, "Only a previously focused keyboard is rearmed")
        XCTAssertTrue(state.acceptsInput(generation: 3))

        let terminalView = PiTerminalHostView(frame: .zero)
        var outboundBytes: [UInt8] = []
        terminalView.outboundBytesObserver = { outboundBytes.append(contentsOf: $0) }
        terminalView.sendAccessoryBytes([0x1b])
        XCTAssertTrue(outboundBytes.isEmpty, "No key may be queued or sent before exact PTY readiness")

        terminalView.beginTerminalInputTransition(generation: 0, restoreKeyboard: false)
        XCTAssertTrue(terminalView.completeTerminalInputTransition(generation: 0))
        terminalView.sendAccessoryBytes(PiTerminalKeyDeck.slashBytes)
        XCTAssertEqual(outboundBytes, PiTerminalKeyDeck.slashBytes)

        terminalView.beginTerminalInputTransition(generation: 0, restoreKeyboard: false)
        terminalView.sendAccessoryBytes([0x1b])
        XCTAssertEqual(
            outboundBytes,
            PiTerminalKeyDeck.slashBytes,
            "A session switch must not retain, replay, or require an Escape byte"
        )
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
        terminalView.beginTerminalInputTransition(generation: 0, restoreKeyboard: false)
        XCTAssertTrue(terminalView.completeTerminalInputTransition(generation: 0))
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
    let stateDelay: Duration?
    let scheduledJobsSucceeds: Bool
    var scheduledJobResultSequence: Int?
    var stateResponses: [StateSnapshot]
    var commands: [String] = []
    var commandParams: [[String: JSONValue]] = []
    var stateCalls = 0
    var codexRefreshCalls = 0
    var healthCalls = 0
    var servicesCalls = 0
    var scheduledJobsCalls = 0
    var scheduledJobResultsCalls = 0
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
        stateDelay: Duration? = nil,
        scheduledJobsSucceeds: Bool = true,
        scheduledJobResultSequence: Int? = nil,
        stateResponses: [StateSnapshot] = []
    ) {
        self.commandSucceeds = commandSucceeds
        self.commandDelay = commandDelay
        self.stateDelay = stateDelay
        self.scheduledJobsSucceeds = scheduledJobsSucceeds
        self.scheduledJobResultSequence = scheduledJobResultSequence
        self.stateResponses = stateResponses
    }

    func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse {
        healthCalls += 1
        return HealthResponse(ok: true, version: "test", uptimeSeconds: 2)
    }

    func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot {
        stateCalls += 1
        if let stateDelay { try await Task.sleep(for: stateDelay) }
        if !stateResponses.isEmpty { return stateResponses.removeFirst() }
        return state
    }

    func stateRefreshingCodexQuota(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot {
        codexRefreshCalls += 1
        return try await state(endpoint)
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

    func scheduledJobResults(
        _ endpoint: JarvisEndpoint,
        after: Int?,
        limit: Int,
        jobId: String?
    ) async throws -> ScheduledJobResultsResponse {
        scheduledJobResultsCalls += 1
        let result: String
        if let sequence = scheduledJobResultSequence, sequence > (after ?? 0) {
            result = #"{"sequence":\#(sequence),"id":"run_\#(sequence)","jobId":"job_demo","jobName":"demo","status":"success","outputKind":"direct","startedAt":"2026-08-30T00:00:00Z","finishedAt":"2026-08-30T00:00:01Z","durationSeconds":1.0,"exitCode":0,"title":"demo completed","summary":"Ready","output":"Ready","error":null,"truncated":false}"#
        } else {
            result = ""
        }
        let body = #"{"ok":true,"results":[\#(result)],"hasMore":false,"nextAfter":\#(scheduledJobResultSequence ?? after ?? 0)}"#
        return try! JSONDecoder().decode(ScheduledJobResultsResponse.self, from: Data(body.utf8))
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
