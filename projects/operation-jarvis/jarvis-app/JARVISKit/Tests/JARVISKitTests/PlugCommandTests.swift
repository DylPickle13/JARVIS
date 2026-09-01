import Foundation
import XCTest
@testable import JARVISKit

final class PlugCommandTests: XCTestCase {
    func testCatalogueUsesRuntimeIdentifiersAndGenericDisplayFormatting() throws {
        let snapshot = try makeState([
            "reading_lamp": false,
            "studio-tv": true,
        ])

        let plugs = JARVISPlugCatalog.descriptors(from: snapshot)

        XCTAssertEqual(plugs.map(\.id), ["reading_lamp", "studio-tv"])
        XCTAssertEqual(plugs.map(\.displayName), ["Reading Lamp", "Studio TV"])
        XCTAssertTrue(plugs.allSatisfy { !$0.stale })
    }

    func testEntityMatchingNormalizesNamesAndReturnsAmbiguity() throws {
        let plugs = JARVISPlugCatalog.descriptors(
            from: try makeState(["desk-lamp": false, "floor_lamp": true, "tv": false])
        )

        XCTAssertEqual(JARVISPlugCatalog.matching("DESK lamp", in: plugs).map(\.id), ["desk-lamp"])
        XCTAssertEqual(
            Set(JARVISPlugCatalog.matching("lamp", in: plugs).map(\.id)),
            Set(["desk-lamp", "floor_lamp"])
        )
        XCTAssertTrue(JARVISPlugCatalog.matching("unknown", in: plugs).isEmpty)
    }

    func testCatalogueRenameIsRemoveAndAddWithoutCompiledChoices() throws {
        let before = JARVISPlugCatalog.descriptors(from: try makeState(["desk-lamp": false]))
        let after = JARVISPlugCatalog.descriptors(from: try makeState(["reading-lamp": false]))

        XCTAssertEqual(before.map(\.id), ["desk-lamp"])
        XCTAssertEqual(after.map(\.id), ["reading-lamp"])
        XCTAssertEqual(after.first?.displayName, "Reading Lamp")
    }

    func testUnrelatedOverallStalenessDoesNotDisableFreshPlugSubsystem() throws {
        let partial = try makeState(["reading-lamp": false], overallStale: true)

        let descriptor = try JARVISPlugCatalog.freshPlug(id: "reading-lamp", in: partial)

        XCTAssertFalse(descriptor.stale)
        XCTAssertEqual(descriptor.isOn, false)
    }

    func testFreshPlugFailsClosedForStaleAndUnknownState() throws {
        let stale = try makeState(["reading-lamp": false], subsystemStale: true)
        XCTAssertThrowsError(try JARVISPlugCatalog.freshPlug(id: "reading-lamp", in: stale)) {
            XCTAssertEqual($0 as? JARVISPlugCatalogError, .stale)
        }

        let fresh = try makeState(["reading-lamp": false])
        XCTAssertThrowsError(try JARVISPlugCatalog.freshPlug(id: "removed-lamp", in: fresh)) {
            XCTAssertEqual($0 as? JARVISPlugCatalogError, .unknownPlug("removed-lamp"))
        }
    }

    func testAlreadyDesiredStateDoesNotPost() async throws {
        let api = PlugCommandFakeAPI(state: try makeState(["reading-lamp": true]))
        let fixture = makeController(api: api)
        defer { fixture.cleanup() }

        let outcome = try await fixture.controller.setPlug(id: "reading-lamp", isOn: true)

        XCTAssertEqual(outcome.disposition, .alreadyInDesiredState)
        XCTAssertTrue(api.commands.isEmpty)
    }

    func testCommandUsesExplicitDesiredActionAndConfirmedResult() async throws {
        let api = PlugCommandFakeAPI(state: try makeState(["reading-lamp": false]))
        let fixture = makeController(api: api)
        defer { fixture.cleanup() }

        let outcome = try await fixture.controller.setPlug(id: "reading-lamp", isOn: true)

        XCTAssertEqual(outcome.disposition, .changed)
        XCTAssertEqual(api.commands.count, 1)
        XCTAssertEqual(api.commands.first?.action, "plug-on")
        XCTAssertEqual(api.commands.first?.plug, "reading-lamp")
        XCTAssertEqual(fixture.snapshotStore.load()?.state.subsystems?.plugs?.plugs?["reading-lamp"]?.isOn, true)
    }

    func testUncertainPostFailureIsNotRelayEligible() async throws {
        let api = PlugCommandFakeAPI(
            state: try makeState(["reading-lamp": false]),
            commandError: .transport("response lost")
        )
        let fixture = makeController(api: api)
        defer { fixture.cleanup() }

        do {
            _ = try await fixture.controller.setPlug(id: "reading-lamp", isOn: true)
            XCTFail("expected an unconfirmed delivery error")
        } catch let error as JARVISPlugCommandError {
            guard case .deliveryUnconfirmed = error else {
                return XCTFail("unexpected error: \(error)")
            }
            XCTAssertFalse(error.allowsWatchRelayFallback)
        }
    }

    private func makeController(api: PlugCommandFakeAPI) -> (
        controller: JARVISDirectPlugController,
        snapshotStore: SnapshotStore,
        cleanup: () -> Void
    ) {
        let suite = "jarvis.plug-command-tests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let endpointStore = EndpointStore(defaults: defaults)
        endpointStore.endpointURLString = "http://jarvis.test:8790"
        let snapshotStore = SnapshotStore(suiteName: suite)
        return (
            JARVISDirectPlugController(
                client: api,
                endpointStore: endpointStore,
                snapshotStore: snapshotStore,
                discoveryTimeout: 0.2
            ),
            snapshotStore,
            { defaults.removePersistentDomain(forName: suite) }
        )
    }

    private func makeState(
        _ values: [String: Bool],
        subsystemStale: Bool = false,
        overallStale: Bool = false
    ) throws -> StateSnapshot {
        let plugs: [String: Any] = Dictionary(uniqueKeysWithValues: values.map { key, value in
            (key, ["ok": true, "stale": false, "isOn": value] as [String: Any])
        })
        let object: [String: Any] = [
            "ok": true,
            "stale": overallStale,
            "subsystems": [
                "plugs": [
                    "ok": true,
                    "stale": subsystemStale,
                    "plugs": plugs,
                ] as [String: Any],
            ],
        ]
        return try JSONDecoder().decode(
            StateSnapshot.self,
            from: JSONSerialization.data(withJSONObject: object)
        )
    }
}

private final class PlugCommandFakeAPI: JarvisAPI, @unchecked Sendable {
    struct RecordedCommand: Equatable {
        let action: String
        let plug: String?
    }

    var stateValue: StateSnapshot
    let commandError: JarvisError?
    var commands: [RecordedCommand] = []

    init(state: StateSnapshot, commandError: JarvisError? = nil) {
        self.stateValue = state
        self.commandError = commandError
    }

    func health(_ endpoint: JarvisEndpoint) async throws -> HealthResponse { HealthResponse(ok: true) }
    func state(_ endpoint: JarvisEndpoint) async throws -> StateSnapshot { stateValue }

    func command(
        _ endpoint: JarvisEndpoint,
        action: String,
        params: [String: JSONValue]?
    ) async throws -> CommandResult {
        let plug: String?
        if case .string(let value) = params?["plug"] { plug = value } else { plug = nil }
        commands.append(RecordedCommand(action: action, plug: plug))
        if let commandError { throw commandError }
        let desired = action == "plug-on"
        return CommandResult(
            ok: true,
            action: action,
            plug: PlugCommandData(name: plug, is_on: desired)
        )
    }

    func events(_ endpoint: JarvisEndpoint, since: Int?, limit: Int) async throws -> EventsResponse {
        EventsResponse(ok: true, count: 0, events: [])
    }

    func services(_ endpoint: JarvisEndpoint) async throws -> ServicesListResponse {
        try JSONDecoder().decode(ServicesListResponse.self, from: Data(#"{"ok":true,"services":{}}"#.utf8))
    }

    func scheduledJobs(_ endpoint: JarvisEndpoint) async throws -> ScheduledJobsResponse {
        try JSONDecoder().decode(
            ScheduledJobsResponse.self,
            from: Data(#"{"ok":true,"summary":{"total":0,"enabled":0,"running":0,"errors":0},"jobs":[]}"#.utf8)
        )
    }

    func scheduledJobResults(
        _ endpoint: JarvisEndpoint,
        after: Int?,
        limit: Int,
        jobId: String?
    ) async throws -> ScheduledJobResultsResponse {
        try JSONDecoder().decode(
            ScheduledJobResultsResponse.self,
            from: Data(#"{"ok":true,"results":[],"hasMore":false,"nextAfter":0}"#.utf8)
        )
    }

    func serviceAction(
        _ endpoint: JarvisEndpoint,
        name: String,
        action: String
    ) async throws -> ServiceActionResult {
        try JSONDecoder().decode(
            ServiceActionResult.self,
            from: Data(#"{"ok":true,"service":"test","action":"status"}"#.utf8)
        )
    }

    func signingRenewalStatus(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus {
        SigningRenewalStatus(ok: true, available: true, phase: "idle", running: false)
    }

    func startSigningRenewal(_ endpoint: JarvisEndpoint) async throws -> SigningRenewalStatus {
        SigningRenewalStatus(ok: true, available: true, phase: "queued", running: true)
    }

    func discover(_ candidates: [URL], timeout: TimeInterval) async -> URL? { candidates.first }
}
