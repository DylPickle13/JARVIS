import XCTest
@testable import JARVISKit

final class JARVISKitTests: XCTestCase {
    func testDecodeStateSnapshot() throws {
        let json = """
        {
          "ok": true,
          "generatedAt": "2026-08-18T11:40:00Z",
          "version": "0.1.0",
          "uptimeSeconds": 90.2,
          "summary": {"plugsOn": 1, "plugsTotal": 4, "purifierOn": true, "pm25": 1, "piActive": 1},
          "subsystems": {
            "plugs": {"ok": true, "count": 4, "onCount": 1,
              "plugs": {"lamp": {"ok": true, "isOn": false, "host": "192.168.21.80", "rssi": -56, "alias": "Plug 3"}}},
            "purifier": {"ok": true, "isOn": true, "mode": "auto", "pm25": 1},
            "pi": {"ok": true, "active": 1, "localActive": 1, "localTotal": 2, "rpcActive": 0},
            "network": {"ok": true, "macLanIp": "192.168.21.215", "tailscaleIp": "100.96.55.86"}
          }
        }
        """
        let snapshot = try JSONDecoder().decode(StateSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(snapshot.ok, true)
        XCTAssertEqual(snapshot.summary?.plugsOn, 1)
        XCTAssertEqual(snapshot.subsystems?.plugs?.plugs?["lamp"]?.isOn, false)
        XCTAssertEqual(snapshot.subsystems?.network?.tailscaleIp, "100.96.55.86")
    }

    func testDecodeCommandResultPlug() throws {
        let json = """
        {"ok": true, "action": "plug-status",
         "plug": {"name": "lamp", "is_on": false, "host": "192.168.21.80", "rssi": -56, "alias": "Plug 3"}}
        """
        let result = try JSONDecoder().decode(CommandResult.self, from: Data(json.utf8))
        XCTAssertEqual(result.ok, true)
        XCTAssertEqual(result.plug?.is_on, false)
    }

    func testSnapshotStoreRoundTripsState() throws {
        let suite = "jarvis.tests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let store = SnapshotStore(suiteName: suite)
        let state = StateSnapshot(ok: true, summary: Summary(plugsOn: 1, plugsTotal: 2, purifierOn: nil, pm25: nil, piActive: nil))
        store.save(state, at: Date(timeIntervalSince1970: 123))
        XCTAssertEqual(store.load()?.state, state)
        XCTAssertEqual(try XCTUnwrap(store.load()?.savedAt.timeIntervalSince1970), 123, accuracy: 0.01)
        defaults.removePersistentDomain(forName: suite)
    }

    func testWatchCommandErrorRoundTrips() throws {
        let payload = WatchCommandError(message: "The relay timed out.")
        let decoded = try JSONDecoder().decode(
            WatchCommandError.self,
            from: JSONEncoder().encode(payload)
        )
        XCTAssertEqual(decoded, payload)
    }

    func testCommandRequestEncodesDesiredPlugState() throws {
        let request = CommandRequest(action: "plug-on", params: ["plug": .string("family-room-light")])
        let data = try JSONEncoder().encode(request)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["action"] as? String, "plug-on")
        XCTAssertEqual((object["params"] as? [String: Any])?["plug"] as? String, "family-room-light")
        XCTAssertFalse(String(data: data, encoding: .utf8)?.contains("cast") == true)
    }
}
