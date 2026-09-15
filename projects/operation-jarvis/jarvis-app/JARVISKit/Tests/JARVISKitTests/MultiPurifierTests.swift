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
