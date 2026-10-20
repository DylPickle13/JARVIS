import Foundation
import XCTest
@testable import JARVISKit

final class DeviceCommandRecoveryTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_700_000_000)
    private func plug(on: Bool = true, stale: Bool = false, updatedAt: String = "2023-11-14T22:13:21Z") throws -> StateSnapshot {
        try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: [
            "ok": true, "subsystems": ["plugs": ["ok": true, "stale": false, "updatedAt": updatedAt,
                "plugs": ["lamp": ["ok": true, "stale": stale, "isOn": on]]]]]))
    }

    func testOnlyFreshPostDispatchMatchingDesiredStateCanConfirm() throws {
        let params: [String: JSONValue] = ["plug": .string("lamp")]
        XCTAssertNotNil(DeviceCommandRecovery.confirmation(action: "plug-on", params: params, state: try plug(), notBefore: start))
        for state in [try plug(on: false), try plug(stale: true), try plug(updatedAt: "2023-11-14T22:13:19Z"), try plug(updatedAt: ""), try plug(updatedAt: "2099-01-01T00:00:00Z")] {
            XCTAssertNil(DeviceCommandRecovery.confirmation(action: "plug-on", params: params, state: state, notBefore: start))
        }
        XCTAssertNil(DeviceCommandRecovery.confirmation(action: "plug-toggle", params: params, state: try plug(), notBefore: start))
        XCTAssertNil(DeviceCommandRecovery.confirmation(action: "plug-on", params: ["plug": .string("other")], state: try plug(), notBefore: start))
    }

    func testRecoveryPerformsOnePassiveReadNoCommandAndNoRetry() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel(); MockURLProtocol.handler = nil }
        let client = JarvisClient(session: session)
        let body = String(data: try JSONEncoder().encode(plug()), encoding: .utf8)!
        var calls = 0
        MockURLProtocol.handler = { request in
            calls += 1
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/v1/state")
            XCTAssertEqual(request.url?.query, "mode=cached")
            return MockURLProtocol.response(request, status: 200, body: body)
        }
        let endpoint = JarvisEndpoint(baseURL: URL(string: "http://fixture.invalid")!, token: "fixture")
        let result = await DeviceCommandRecovery.observe(client: client, endpoint: endpoint,
            action: "plug-on", params: ["plug": .string("lamp")], notBefore: start)
        XCTAssertNotNil(result?.confirmation)
        XCTAssertEqual(calls, 1)
        MockURLProtocol.handler = { _ in calls += 1; throw URLError(.timedOut) }
        let failed = await DeviceCommandRecovery.observe(client: client, endpoint: endpoint,
            action: "plug-on", params: ["plug": .string("lamp")], notBefore: start)
        XCTAssertNil(failed)
        XCTAssertEqual(calls, 2, "One failed read, no retry loop")
        let unsupported = await DeviceCommandRecovery.observe(client: client, endpoint: endpoint,
            action: "service-restart", params: [:], notBefore: start)
        XCTAssertNil(unsupported); XCTAssertEqual(calls, 2)
    }

    func testPurifierRequiresMatchingTargetAndCompletedFreshVerification() throws {
        let id = String(repeating: "a", count: 24)
        for pending in [false, true] {
            let device: [String: Any] = ["ok": true, "stale": false, "deviceID": id,
                "updatedAt": "2023-11-14T22:13:21Z", "verificationPending": pending,
                "isOn": true, "mode": "manual", "fanSetLevel": 3]
            let data = try JSONSerialization.data(withJSONObject: ["ok": true, "subsystems": [
                "purifier": ["ok": true, "devices": [id: device]]]])
            let state = try JSONDecoder().decode(StateSnapshot.self, from: data)
            let params: [String: JSONValue] = ["setting": .string("speed"), "level": .number(3), "deviceID": .string(id)]
            XCTAssertEqual(DeviceCommandRecovery.confirmation(action: "purifier-set", params: params, state: state, notBefore: start) != nil, !pending)
            XCTAssertNil(DeviceCommandRecovery.confirmation(action: "purifier-set", params: ["setting": .string("power"), "value": .string("toggle")], state: state, notBefore: start))
        }
    }
}
