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
                          stale: Bool = false, omitting: Set<String> = [],
                          background: [String: [String: Any]] = [:],
                          collectorFailed: Bool = false, overall: String? = nil) throws -> StateSnapshot {
        var inventory = background
        if !omitting.contains("minecraft-server") { inventory["minecraft-server"] = server ?? self.server }
        if !omitting.contains("minecraft-jarvis-bot") { inventory["minecraft-jarvis-bot"] = bot ?? self.bot }
        var metadata = Dictionary(uniqueKeysWithValues: ["services", "pi", "plugs", "purifier", "network", "codexQuota"].map {
            ($0, ["ok": true, "stale": false, "ageSeconds": 0] as [String: Any])
        })
        metadata["services"] = ["ok": !collectorFailed, "stale": stale, "ageSeconds": 0]
        var object: [String: Any] = ["ok": true,
            "generatedAt": now.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true)),
            "subsystemsMeta": metadata,
            "subsystems": ["services": ["ok": true, "services": inventory],
                           "plugs": ["ok": true, "stale": false, "plugs": [:]],
                           "purifier": ["ok": true, "stale": false]]]
        if let overall {
            func evidence(_ state: String, _ reason: String) -> [String: Any] {
                ["state": state, "reason": reason,
                 "sourceObservedAt": now.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true)),
                 "validUntil": now.addingTimeInterval(120).formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true))]
            }
            object["health"] = ["scope": "cached_status_health", "components": [
                "security": evidence("healthy", "current"),
                "overall": evidence(overall, overall == "degraded" ? "service_not_ready" : "not_checked")]]
        }
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

    func testInformationalBotRetainsDiagnosticsWithoutAnIssueInMinecraftOrOverall() throws {
        var bot = self.bot
        bot["healthPolicy"] = "informational"
        bot["running"] = true; bot["ready"] = false; bot["readinessReason"] = "bot_disconnected"
        let result = dashboard(try snapshot(bot: bot))
        let row = try XCTUnwrap(result.services.first { $0.id == "minecraft-jarvis-bot" })
        XCTAssertEqual(row.row.state, .inactive)
        XCTAssertEqual(row.row.detail, "Running · disconnected from Minecraft")
        XCTAssertTrue(row.technicalDetails.contains("Health: Informational · excluded from overall health"))
        XCTAssertEqual(result.visualGroups.first { $0.id == "minecraft" }?.state, .healthy)
        XCTAssertEqual(result.state, .healthy)
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

    func testMinecraftHasItsOwnHealthCardCheckAndDoesNotPolluteServicesEvidence() throws {
        let result = dashboard(try snapshot())
        XCTAssertEqual(result.visualGroups.map(\.id), ["services", "minecraft", "pi", "network", "devices", "security"])
        let minecraft = try XCTUnwrap(result.visualGroups.first { $0.id == "minecraft" })
        XCTAssertEqual(minecraft.title, "Minecraft")
        XCTAssertEqual(minecraft.rows.map(\.id), ["service:minecraft-server", "service:minecraft-jarvis-bot"])
        XCTAssertEqual(minecraft.state, .healthy)
        XCTAssertTrue(minecraft.accessibilityText.contains("Minecraft Server: Running"))
        XCTAssertTrue(minecraft.accessibilityText.contains("Minecraft JARVIS Bot: Stopped"))
        let services = try XCTUnwrap(result.visualGroups.first { $0.id == "services" })
        XCTAssertEqual(services.state, .healthy)
        XCTAssertFalse(services.rows.contains { $0.id.contains("minecraft") })
        XCTAssertFalse(services.accessibilityText.contains("Minecraft"))
    }

    func testMinecraftFailureAndUnknownReachOnlyDedicatedCheckAndOverall() throws {
        for (ready, expected) in [(false, SystemHealthState.issue), (nil, .unknown)] {
            var bot = self.bot
            bot["running"] = true
            bot["ready"] = ready.map { $0 as Any } ?? NSNull()
            bot["readinessReason"] = ready == false ? "bot_disconnected" : "health_unavailable"
            let result = dashboard(try snapshot(bot: bot))
            XCTAssertEqual(result.visualGroups.first { $0.id == "minecraft" }?.state, expected)
            XCTAssertEqual(result.visualGroups.first { $0.id == "services" }?.state, .healthy)
            XCTAssertEqual(result.state, expected)
            XCTAssertTrue(result.visualException?.hasPrefix("Minecraft ·") == true)
        }
    }

    func testStoppedMinecraftPairIsInactiveNotAServiceFailure() throws {
        var server = self.server
        server["running"] = false; server["ready"] = NSNull(); server["readinessReason"] = NSNull()
        let result = dashboard(try snapshot(server: server))
        XCTAssertEqual(result.visualGroups.first { $0.id == "minecraft" }?.state, .inactive)
        XCTAssertEqual(result.visualGroups.first { $0.id == "services" }?.state, .healthy)
        XCTAssertEqual(result.state, .healthy)
    }

    func testMissingMemberRemainsVisibleAndCannotLeaveHealthyHeader() throws {
        for id in SystemDashboardPresentation.minecraftServiceIDs {
            let result = dashboard(try snapshot(omitting: [id]))
            XCTAssertEqual(result.minecraftServices.count, 2)
            let missing = try XCTUnwrap(result.minecraftServices.first { $0.id == id })
            XCTAssertEqual(missing.row.state, .unknown)
            XCTAssertEqual(missing.row.detail, "No cached service evidence")
            XCTAssertFalse(missing.technicalDetails.contains { $0.contains("running:") || $0.contains("PID:") })
            XCTAssertEqual(result.visualGroups.first { $0.id == "minecraft" }?.state, .unknown)
            XCTAssertEqual(result.state, .unknown)
            XCTAssertEqual(result.summary, "Status unknown")
        }
    }

    func testOlderHostsDoNotInventAConfiguredMinecraftCheck() throws {
        let result = dashboard(try snapshot(omitting: Set(SystemDashboardPresentation.minecraftServiceIDs)))
        XCTAssertFalse(result.hasMinecraftServices)
        XCTAssertFalse(result.visualGroups.contains { $0.id == "minecraft" })
        XCTAssertEqual(result.visualGroups.count, 5)
    }

    func testServicesAndMinecraftScopesAreDisjointWithoutDroppingInventoryEvidence() throws {
        let legacy: [String: Any] = ["ok": true, "displayName": "Legacy daemon", "critical": true,
                                    "running": true, "executionMode": "continuous"]
        let result = dashboard(try snapshot(background: ["legacy": legacy]))
        let services = SystemServicesScope.services.services(in: result)
        let minecraft = SystemServicesScope.minecraft.services(in: result)
        XCTAssertEqual(services.map(\.id), ["legacy"])
        XCTAssertEqual(minecraft.map(\.id), SystemDashboardPresentation.minecraftServiceIDs)
        XCTAssertEqual(minecraft.map(\.row.state), [.healthy, .inactive])
        XCTAssertTrue(Set(services.map(\.id)).isDisjoint(with: minecraft.map(\.id)))
        XCTAssertEqual(Set(services.map(\.id) + minecraft.map(\.id)), Set(result.services.map(\.id)))
        XCTAssertEqual(result.services.count, 3, "Keep complete cached evidence for overall health")
        XCTAssertEqual(SystemServicesScope.minecraft.title, "Minecraft")
        XCTAssertEqual(SystemServicesScope.services.title, "Services")
    }

    func testMissingMinecraftCounterpartStaysOnlyInMinecraftScope() throws {
        for missing in SystemDashboardPresentation.minecraftServiceIDs {
            let result = dashboard(try snapshot(omitting: [missing]))
            XCTAssertTrue(SystemServicesScope.services.services(in: result).isEmpty)
            let minecraft = SystemServicesScope.minecraft.services(in: result)
            XCTAssertEqual(minecraft.map(\.id), SystemDashboardPresentation.minecraftServiceIDs)
            XCTAssertEqual(minecraft.first { $0.id == missing }?.row.state, .unknown)
        }
    }

    func testScopePartitionRemainsDisjointForStaleOfflineExpiredAndFailedCollectors() throws {
        let legacy: [String: Any] = ["ok": true, "displayName": "Legacy daemon", "critical": true,
                                    "running": true, "executionMode": "continuous"]
        for result in [dashboard(try snapshot(stale: true, background: ["legacy": legacy])),
                       dashboard(try snapshot(background: ["legacy": legacy]), connected: false),
                       dashboard(try snapshot(background: ["legacy": legacy]), elapsed: 661),
                       dashboard(try snapshot(background: ["legacy": legacy], collectorFailed: true))] {
            let services = SystemServicesScope.services.services(in: result)
            let minecraft = SystemServicesScope.minecraft.services(in: result)
            XCTAssertEqual(services.map(\.id), ["legacy"])
            XCTAssertEqual(minecraft.map(\.id), SystemDashboardPresentation.minecraftServiceIDs)
            XCTAssertTrue(services.allSatisfy { $0.row.state == .unknown })
            XCTAssertTrue(minecraft.allSatisfy { $0.row.state == .unknown })
            XCTAssertTrue(Set(services.map(\.id)).isDisjoint(with: minecraft.map(\.id)))
        }
    }

    func testOlderHostsKeepAllNonMinecraftServicesIncludingLookalikeNamesAndIDs() throws {
        let legacy: [String: Any] = ["ok": true, "displayName": "Minecraft Server", "critical": true,
                                    "running": true, "executionMode": "continuous"]
        let result = dashboard(try snapshot(omitting: Set(SystemDashboardPresentation.minecraftServiceIDs),
            background: ["legacy": legacy, "minecraft-server-backup": legacy]))
        XCTAssertFalse(result.hasMinecraftServices)
        XCTAssertEqual(SystemServicesScope.services.services(in: result), result.services)
        XCTAssertEqual(Set(result.services.map(\.id)), ["legacy", "minecraft-server-backup"])
    }

    func testDedicatedCheckAndScopeNeverRejuvenateOfflineExpiredOrFailedCollectorEvidence() throws {
        for result in [dashboard(try snapshot(stale: true)), dashboard(try snapshot(), connected: false),
                       dashboard(try snapshot(), elapsed: 661), dashboard(try snapshot(collectorFailed: true))] {
            XCTAssertEqual(result.visualGroups.first { $0.id == "minecraft" }?.state, .unknown)
            XCTAssertTrue(SystemServicesScope.minecraft.services(in: result).allSatisfy { $0.row.state == .unknown })
            XCTAssertTrue(result.minecraftServices[0].technicalDetails.contains("Cached running: Yes"))
        }
    }

    func testUnknownBackendOverallStillConstrainsHeaderWithoutBeingAttributedToServices() throws {
        for (overall, expected) in [("degraded", SystemHealthState.issue), ("unknown", .unknown)] {
            let result = dashboard(try snapshot(overall: overall))
            XCTAssertEqual(result.state, expected)
            XCTAssertEqual(result.visualGroups.first { $0.id == "minecraft" }?.state, .healthy)
            XCTAssertEqual(result.visualGroups.first { $0.id == "services" }?.state, .healthy)
            XCTAssertEqual(result.visualException, "Backend summary · \(expected == .issue ? "issue" : "unverified")")
            XCTAssertTrue(result.health.rows.contains { $0.id == "backendHealth" && $0.state == expected })
        }
    }

    func testMinecraftNameOnAnUnrelatedServiceDoesNotChangeCheckOwnership() throws {
        var legacy = self.server
        legacy["displayName"] = "Minecraft Server"
        let result = dashboard(try snapshot(omitting: Set(SystemDashboardPresentation.minecraftServiceIDs),
                                            background: ["legacy": legacy]))
        XCTAssertFalse(result.hasMinecraftServices)
        XCTAssertEqual(result.backgroundServices.map(\.id), ["legacy"])
    }

    func testLegacyContinuousServiceDoesNotRequireReadinessFields() throws {
        var legacy = server
        legacy.removeValue(forKey: "ready"); legacy.removeValue(forKey: "readinessReason")
        XCTAssertEqual(dashboard(try snapshot(server: legacy)).services.first?.row.state, .healthy)
    }
}
