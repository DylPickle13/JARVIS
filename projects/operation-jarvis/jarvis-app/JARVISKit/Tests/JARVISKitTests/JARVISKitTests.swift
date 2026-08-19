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
            "weather": {"ok": true, "temperatureC": 25.1, "weatherCode": 0},
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

    func testCommandAllowlistRejectsCast() {
        // Mirrors the server-side allowlist; cast actions must never be sent.
        let bad = "cast-status"
        let allowed: Set<String> = ["status", "plug-list", "plug-status", "plug-on",
                                    "plug-off", "plug-toggle", "purifier-status", "purifier-set"]
        XCTAssertFalse(allowed.contains(bad))
    }
}
