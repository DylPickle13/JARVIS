import Foundation
import XCTest
@testable import JARVISKit

final class MinecraftServiceTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_000)
    private var server: [String: Any] {
        ["ok": true, "service": "minecraft-server", "displayName": "Minecraft Server",
         "configured": true, "critical": false, "executionMode": "continuous", "sortOrder": 40,
         "running": true, "ready": true, "readinessReason": "java_listening", "pid": 10,
         "allowedActions": []]
    }
    private var bot: [String: Any] {
        ["ok": true, "service": "minecraft-jarvis-bot", "displayName": "Minecraft JARVIS Bot",
         "configured": true, "critical": false, "executionMode": "continuous", "sortOrder": 50,
         "running": false, "ready": NSNull(), "readinessReason": NSNull(), "allowedActions": []]
    }

    private func snapshot(server: [String: Any]? = nil, bot: [String: Any]? = nil,
                          stale: Bool = false) throws -> StateSnapshot {
        let object: [String: Any] = ["ok": true,
            "generatedAt": now.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true)),
            "subsystemsMeta": ["services": ["ok": true, "stale": stale, "ageSeconds": 0]],
            "subsystems": ["services": ["ok": true, "services": [
                "minecraft-server": server ?? self.server, "minecraft-jarvis-bot": bot ?? self.bot]]]]
        return try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
    }

    private func dashboard(_ snapshot: StateSnapshot, connected: Bool = true,
                           elapsed: Double = 0) -> SystemDashboardPresentation {
        .init(snapshot: snapshot, requestStartedAt: now, isConnected: connected,
              now: now.addingTimeInterval(elapsed))
    }

    func testNamedServicesAreGenericSortedReadOnlyRows() throws {
        let result = dashboard(try snapshot())
        XCTAssertEqual(result.services.map(\.id), ["minecraft-server", "minecraft-jarvis-bot"])
        XCTAssertEqual(result.services.map(\.row.title), ["Minecraft Server", "Minecraft JARVIS Bot"])
        XCTAssertEqual(result.services.map(\.row.state), [.healthy, .inactive])
        XCTAssertEqual(result.services.first?.row.detail, "Running")
        XCTAssertEqual(result.services.last?.row.detail, "Stopped · not marked required")
        XCTAssertTrue(result.services.allSatisfy { $0.requirement == "Optional" && $0.executionMode == "Continuous" })
        XCTAssertTrue(result.services[0].technicalDetails.contains("PID: 10"))
        XCTAssertTrue(result.services[0].technicalDetails.contains("readiness: Running · Java listener verified"))
    }

    func testRunningButDisconnectedOrMissingAgentIsNotStoppedOrHealthy() throws {
        for (reason, detail) in [("bot_disconnected", "Running · disconnected from Minecraft"),
                                 ("agent_unavailable", "Running · Pi agent unavailable"),
                                 ("bot_quarantined", "Running · bot action quarantined") ] {
            var bot = self.bot
            bot["running"] = true; bot["ready"] = false; bot["readinessReason"] = reason
            let row = try XCTUnwrap(dashboard(try snapshot(bot: bot)).services.first { $0.id == "minecraft-jarvis-bot" })
            XCTAssertEqual(row.row.state, .issue)
            XCTAssertEqual(row.row.detail, detail)
        }
    }

    func testReadinessFailureKeepsKnownRunningStateButIsUnverified() throws {
        var bot = self.bot
        bot["running"] = true; bot["readinessReason"] = "health_unavailable"
        let value = try snapshot(bot: bot)
        let row = try XCTUnwrap(dashboard(value).services.first { $0.id == "minecraft-jarvis-bot" })
        XCTAssertEqual(row.row.state, .unknown)
        XCTAssertEqual(row.row.detail, "Running · readiness unverified")
        XCTAssertEqual(value.subsystems?.services?.services?["minecraft-jarvis-bot"]?.running, true)
    }

    func testProcessObservationFailureIsNotPresentedAsStopped() throws {
        var bot = self.bot
        bot["ok"] = false; bot["running"] = NSNull()
        let row = try XCTUnwrap(dashboard(try snapshot(bot: bot)).services.first { $0.id == "minecraft-jarvis-bot" })
        XCTAssertEqual(row.row.state, .issue)
        XCTAssertEqual(row.row.detail, "Service status read failed")
        XCTAssertFalse(row.technicalDetails.contains { $0.contains("running:") })
    }

    func testStaleAndOfflineSnapshotsCannotClaimCurrentProcessOrReadiness() throws {
        for result in [dashboard(try snapshot(stale: true)), dashboard(try snapshot(), connected: false),
                       dashboard(try snapshot(), elapsed: 661)] {
            XCTAssertTrue(result.services.allSatisfy { $0.row.state == .unknown })
            XCTAssertTrue(result.services[0].technicalDetails.contains("Cached running: Yes"))
            XCTAssertFalse(result.services[0].technicalDetails.contains("PID: 10"))
        }
    }

    func testWatchBridgeAndDiskRoundTripPreserveServiceFieldsWithoutRejuvenation() throws {
        let value = try snapshot()
        let received = try JSONDecoder().decode(StateSnapshot.self, from: JSONEncoder().encode(value))
        XCTAssertEqual(received, value)
        XCTAssertEqual(received.subsystems?.services?.services?["minecraft-server"]?.ready, true)
        XCTAssertEqual(received.subsystems?.services?.services?["minecraft-jarvis-bot"]?.allowedActions, [])
        let generated = SystemDashboardPresentation.snapshotGeneratedAt(received)
        XCTAssertEqual(generated, now)
        let expired = SystemDashboardPresentation(snapshot: received, requestStartedAt: generated,
                                                  now: now.addingTimeInterval(661))
        XCTAssertTrue(expired.services.allSatisfy { $0.row.state == .unknown })
    }

    func testLegacyContinuousServiceDoesNotRequireReadinessFields() throws {
        var legacy = server
        legacy.removeValue(forKey: "ready"); legacy.removeValue(forKey: "readinessReason")
        XCTAssertEqual(dashboard(try snapshot(server: legacy)).services.first?.row.state, .healthy)
    }
}
