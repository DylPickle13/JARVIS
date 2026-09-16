import Foundation
import XCTest
@testable import JARVISKit

final class MultiPurifierTests: XCTestCase {
    let a = String(repeating: "a", count: 24)
    let b = String(repeating: "b", count: 24)

    func fixture() throws -> PurifierSubsystem {
        let data = try JSONSerialization.data(withJSONObject: [
            "name": "Dylan's Air Purifier", "deviceID": a, "defaultDeviceID": a,
            "devices": [a: ["deviceID": a, "name": "Dylan's Air Purifier", "isOn": true],
                        b: ["deviceID": b, "name": "Bran's Air Purifier", "isOn": false]]])
        return try JSONDecoder().decode(PurifierSubsystem.self, from: data)
    }

    func testWatchRowsKeepIndependentStatusesAndTargets() throws {
        let data = try JSONSerialization.data(withJSONObject: ["defaultDeviceID": a, "devices": [
            a: ["name": "Dylan's Air Purifier", "deviceID": a, "ok": true, "isOn": true, "mode": "auto", "pm25": 1],
            b: ["name": "Bran's Air Purifier", "deviceID": b, "ok": false]
        ]])
        let state = try JSONDecoder().decode(PurifierSubsystem.self, from: data)
        let rows = state.compactDevices.map { WatchPurifierRow(id: $0.id, state: $0.state, unavailable: false, busy: false) }
        XCTAssertEqual(rows.map(\.deviceID), [a, b])
        XCTAssertEqual(rows.map(\.shortName), ["Dylan's", "Bran's"])
        XCTAssertEqual(rows.map(\.status), ["Auto", "Offline"])
        XCTAssertEqual(rows.map(\.pm25), ["1", "—"])
        let stale = WatchPurifierRow(id: a, state: state.selected(a)!, unavailable: true, busy: false)
        XCTAssertEqual(stale.status, "Stale")
        let busy = WatchPurifierRow(id: b, state: state.selected(b)!, unavailable: false, busy: true)
        XCTAssertEqual(busy.status, "Working")
    }

    func testWatchRowMissingEmbeddedIDKeepsCollectionKeyNotDefault() throws {
        let value = try JSONDecoder().decode(PurifierSubsystem.self, from: Data("{\"name\":\"Renamed\"}".utf8))
        XCTAssertEqual(WatchPurifierRow(id: b, state: value, unavailable: false, busy: false).deviceID, b)
        XCTAssertNil(WatchPurifierRow(id: "legacy-default", state: value, unavailable: false, busy: false).deviceID)
    }

    func testSelectedDeviceNeverFallsBackToDefault() throws {
        let state = try fixture()
        XCTAssertEqual(state.selected(b)?.name, "Bran's Air Purifier")
        XCTAssertEqual(state.selected(nil)?.name, "Dylan's Air Purifier")
        XCTAssertNil(state.selected("removed"))
        XCTAssertEqual(state.compactDevices.map(\.id), [a,b])
    }

    func testLegacySingleDeviceDecodesWithoutCollection() throws {
        let state = try JSONDecoder().decode(PurifierSubsystem.self, from: Data("{\"name\":\"Existing\"}".utf8))
        XCTAssertNil(state.devices)
        XCTAssertEqual(state.compactDevices.count, 1)
        XCTAssertNil(state.selected(b))
    }

    func testTargetedWatchCommandUsesSeparateWireType() throws {
        let command = WatchPurifierCommand.power(false).targeting(b)
        XCTAssertTrue(command.isValid)
        XCTAssertEqual(command.relayMessageType, "purifierDeviceCommand")
        XCTAssertEqual(command.parameters["deviceID"], .string(b))
        XCTAssertEqual(WatchPurifierCommand.power(false).relayMessageType, "purifierCommand")
        XCTAssertEqual(try JSONDecoder().decode(WatchPurifierCommand.self, from: JSONEncoder().encode(command)), command)
    }

    func testTargetedWatchCommandCannotMatchOtherDevice() throws {
        let state = try fixture()
        let command = WatchPurifierCommand.power(false).targeting(b)
        XCTAssertTrue(command.matches(try XCTUnwrap(state.selected(b))))
        XCTAssertFalse(command.matches(try XCTUnwrap(state.selected(a))))
        XCTAssertFalse(WatchPurifierCommand.power(false).targeting(" ").isValid)
    }
}
