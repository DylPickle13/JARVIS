import XCTest
@testable import JARVISKit

final class SystemDeviceGroupingTests: XCTestCase {
    private let ids = ["keyboard-watcher", "keyboard", "mouse", "led-strip", "room-audio-mac",
                       "hub", "door-sensor", "motion-sensor", "sensor-reader", "front-doorbell",
                       "indoor-camera", "room-audio-pi", "family-room-tv", "family-room-speaker",
                       "webcam", "headset", "iphone-usb", "watch", "master-chief"]
    private let timestamp = "2026-10-01T01:00:00Z"
    private var now: Date { SystemHistoryDates.parse(timestamp)! }
    private func presentation(failed: String? = nil, omit: String? = nil,
                              elapsed: Double = 1, connected: Bool = true) throws -> SystemDashboardPresentation {
        let devices: [[String: Any]] = ids.filter { $0 != omit }.map { id in
            ["id": id, "name": id, "scope": "tcp_reachability", "expectation": "always",
             "coverage": "background", "state": id == failed ? "unavailable" : "available",
             "reason": id == failed ? "connection_refused" : "current", "ageSeconds": 0,
             "lastAttemptAt": timestamp, "lastSuccessAt": timestamp, "freshnessLimitSeconds": 150,
             "dependsOn": [], "blockedBy": [], "incidentOpen": false]
        }
        let object: [String: Any] = ["ok": true, "deviceHealth": [
            "version": 1, "scope": "device_check_coverage", "devices": devices]]
        let snapshot = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        return .init(snapshot: snapshot, requestStartedAt: now, isConnected: connected,
                     now: now.addingTimeInterval(elapsed))
    }
    func testOwnerCategoriesAndSpeakerMembership() throws {
        let groups = try presentation().visualGroups
        XCTAssertEqual(groups.map(\.title), ["Services", "Pi", "Network", "Computer", "Security", "Cast playback", "Devices"])
        let computer = try XCTUnwrap(groups.first { $0.id == "computer" })
        XCTAssertTrue(computer.rows.contains { $0.id == "device:led-strip" })
        XCTAssertTrue(computer.rows.contains { $0.id == "device:room-audio-mac" })
        let security = try XCTUnwrap(groups.first { $0.id == "security" })
        XCTAssertTrue(security.rows.contains { $0.id == "device:room-audio-pi" })
        XCTAssertTrue(security.rows.contains { $0.id == "device:indoor-camera" })
        XCTAssertFalse(security.rows.contains { $0.id == "device:led-strip" })
        XCTAssertEqual(computer.state, .healthy)
        XCTAssertEqual(security.state, .healthy)
    }
    func testFailuresReachCorrectGroupAndOverall() throws {
        for (device, group) in [("led-strip", "computer"), ("room-audio-mac", "computer"),
                                ("room-audio-pi", "security"), ("front-doorbell", "security"),
                                ("family-room-speaker", "cast")] {
            let p = try presentation(failed: device)
            XCTAssertEqual(p.visualGroups.first { $0.id == group }?.state, .issue)
            XCTAssertEqual(p.state, .issue)
            if group == "computer" { XCTAssertEqual(p.visualGroups.first { $0.id == "security" }?.state, .healthy) }
        }
    }
    func testMissingStaleAndOfflineNeverGreen() throws {
        XCTAssertEqual(try presentation(omit: "room-audio-mac").visualGroups.first { $0.id == "computer" }?.state, .unknown)
        for p in [try presentation(elapsed: 151), try presentation(connected: false)] {
            for id in ["computer", "security", "cast"] {
                XCTAssertEqual(p.visualGroups.first { $0.id == id }?.state, .unknown)
            }
        }
    }
    func testRemainingDevicesPreservedAndExclusionsIgnored() throws {
        let p = try presentation(failed: "iphone-usb")
        let rows = p.visualGroups.flatMap(\.rows).map(\.id)
        XCTAssertTrue(rows.contains("device:webcam"))
        XCTAssertTrue(rows.contains("device:headset"))
        for id in ["iphone-usb", "watch", "master-chief"] { XCTAssertFalse(rows.contains("device:\(id)")) }
        XCTAssertFalse(p.health.rows.contains { $0.state == .issue })
    }
    func testLegacyHostRetainsAggregateFallback() {
        let p = SystemDashboardPresentation(snapshot: nil, requestStartedAt: nil)
        XCTAssertEqual(p.visualGroups.map(\.id), ["services", "pi", "network", "devices", "security"])
        XCTAssertFalse(p.visualGroups.contains { $0.state == .healthy })
    }
}
