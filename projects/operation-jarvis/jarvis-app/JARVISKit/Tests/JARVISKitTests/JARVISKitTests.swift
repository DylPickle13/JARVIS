import XCTest
@testable import JARVISKit

final class JARVISKitTests: XCTestCase {
    func testNativeAppsShareFifteenSecondActiveRefreshPolicy() {
        XCTAssertEqual(JARVISRefreshPolicy.activeInterval, .seconds(15))
    }

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
            "network": {"ok": true, "macLanIp": "192.168.21.215", "tailscaleIp": "100.87.28.34"},
            "codexQuota": {"ok": true, "available": true, "planType": "prolite", "creditBalance": 1887.24,
              "weekly": {"usedPercent": 69, "remainingPercent": 31, "resetAfterSeconds": 360706, "resetAt": "2026-08-27T21:37:51Z"}}

          }
        }
        """
        let snapshot = try JSONDecoder().decode(StateSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(snapshot.ok, true)
        XCTAssertEqual(snapshot.summary?.plugsOn, 1)
        XCTAssertEqual(snapshot.subsystems?.plugs?.plugs?["lamp"]?.isOn, false)
        XCTAssertEqual(snapshot.subsystems?.network?.tailscaleIp, "100.87.28.34")
        XCTAssertEqual(snapshot.subsystems?.codexQuota?.weekly?.remainingPercent, 31)
        XCTAssertEqual(snapshot.subsystems?.codexQuota?.creditBalance, 1887.24)
    }

    func testDefaultEndpointsPreferMagicDNSBeforeTailscaleIPFallback() throws {
        let candidates = JarvisEndpoints.candidates(override: nil)
        XCTAssertEqual(candidates.count, 3)
        XCTAssertEqual(candidates[0].host, "192.168.21.215")
        XCTAssertEqual(candidates[1].host, "dylans-mac-mini-2.tailcba1e5.ts.net")
        XCTAssertEqual(candidates[2].host, "100.87.28.34")
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

    func testWidgetStateHelpersSortPlugsAndFailClosedWhenStale() throws {
        let state = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(#"{"ok":true,"subsystems":{"plugs":{"ok":true,"plugs":{"tv":{"ok":true,"isOn":false},"lamp":{"ok":true,"isOn":true}}}}}"#.utf8)
        )
        let savedAt = Date(timeIntervalSince1970: 1_000)
        let cached = CachedState(state: state, savedAt: savedAt)

        XCTAssertEqual(JARVISWidgetStateLoader.plugNames(from: cached), ["lamp", "tv"])
        XCTAssertFalse(JARVISWidgetStateLoader.isStale(cached, now: savedAt.addingTimeInterval(60)))
        XCTAssertTrue(
            JARVISWidgetStateLoader.isStale(
                cached,
                now: savedAt.addingTimeInterval(JARVISWidgetStateLoader.staleAfter + 1)
            )
        )
        XCTAssertTrue(JARVISWidgetStateLoader.isStale(nil))
    }

    func testConfirmedPlugStateUpdatesWidgetCacheImmediately() throws {
        let suite = "jarvis.tests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let store = SnapshotStore(suiteName: suite)
        let state = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(
                #"{"ok":true,"summary":{"plugsOn":1,"plugsTotal":2},"subsystems":{"plugs":{"ok":true,"stale":false,"count":2,"onCount":1,"plugs":{"lamp":{"ok":true,"isOn":false,"host":"192.0.2.1","alias":"Lamp"},"tv":{"ok":true,"isOn":true}}}}}"#.utf8
            )
        )
        store.save(state, at: Date(timeIntervalSince1970: 100))

        let updated = try XCTUnwrap(
            store.applyConfirmedPlugState(name: "lamp", isOn: true, at: Date(timeIntervalSince1970: 200))
        )
        XCTAssertEqual(updated.state.subsystems?.plugs?.plugs?["lamp"]?.isOn, true)
        XCTAssertEqual(updated.state.subsystems?.plugs?.plugs?["lamp"]?.host, "192.0.2.1")
        XCTAssertEqual(updated.state.subsystems?.plugs?.onCount, 2)
        XCTAssertEqual(updated.state.summary?.plugsOn, 2)
        XCTAssertEqual(updated.savedAt.timeIntervalSince1970, 200, accuracy: 0.01)
        defaults.removePersistentDomain(forName: suite)
    }

    func testWidgetControlStoreShowsPendingAndSuppressesDuplicateDesiredState() {
        let suite = "jarvis.tests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let controls = JARVISWidgetControlStore(suiteName: suite)
        let start = Date(timeIntervalSince1970: 1_000)

        XCTAssertEqual(controls.begin(name: "lamp", isOn: true, now: start), .execute)
        XCTAssertEqual(controls.pendingCommand(for: "lamp", now: start)?.isOn, true)
        XCTAssertEqual(controls.begin(name: "lamp", isOn: true, now: start.addingTimeInterval(1)), .alreadyPending)

        controls.complete(name: "lamp", isOn: true, succeeded: true, now: start.addingTimeInterval(2))
        XCTAssertNil(controls.pendingCommand(for: "lamp", now: start.addingTimeInterval(2)))
        XCTAssertEqual(
            controls.begin(name: "lamp", isOn: true, now: start.addingTimeInterval(3)),
            .recentlyCompleted
        )
        XCTAssertEqual(controls.begin(name: "lamp", isOn: false, now: start.addingTimeInterval(3)), .execute)
        controls.complete(name: "lamp", isOn: false, succeeded: false, now: start.addingTimeInterval(4))
        XCTAssertEqual(
            controls.begin(name: "lamp", isOn: true, now: start.addingTimeInterval(13)),
            .execute
        )
        controls.clear()
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

    func testWatchTerminalProvisioningRoundTripsAndValidates() throws {
        let configuration = WatchTerminalConfiguration(
            endpoint: "https://192.0.2.10:8792",
            token: String(repeating: "a", count: 64),
            certificateSHA256: String(repeating: "AB:", count: 31) + "AB"
        )
        XCTAssertTrue(configuration.isValid)
        XCTAssertEqual(configuration.certificateSHA256, String(repeating: "ab", count: 32))
        XCTAssertEqual(
            WatchTerminalConfiguration.fromProvisioningCode(try configuration.provisioningCode()),
            configuration
        )
        XCTAssertEqual(configuration.candidateBaseURLs.first?.host, "192.0.2.10")
        XCTAssertTrue(configuration.candidateBaseURLs.contains { $0.host == "dylans-mac-mini-2.tailcba1e5.ts.net" && $0.port == 8792 })
        XCTAssertTrue(configuration.candidateBaseURLs.contains { $0.host == "100.87.28.34" && $0.port == 8792 })
        XCTAssertNil(WatchTerminalConfiguration.fromProvisioningCode("not-a-provisioning-code"))
        XCTAssertFalse(
            WatchTerminalConfiguration(
                endpoint: "http://192.0.2.10:8792",
                token: String(repeating: "a", count: 64),
                certificateSHA256: String(repeating: "ab", count: 32)
            ).isValid
        )
    }

    func testWatchTerminalFrameFollowsCursorAndKeyBytesAreExact() {
        let frame = WatchTerminalFrame(
            sequence: 4,
            columns: 48,
            rows: 8,
            cursorColumn: 7,
            cursorRow: 6,
            alternateScreen: true,
            mouseMode: true,
            historySize: 20,
            lines: (0..<8).map { "line-\($0)" }
        )
        XCTAssertEqual(frame.visibleLines(maximumLines: 3), ["line-5", "line-6", "line-7"])
        XCTAssertEqual(frame.visibleText(maximumLines: 3), "line-5\nline-6\nline-7")
        let displayColumns = WatchTerminalLayout.displayColumns(availableWidth: 190)
        XCTAssertGreaterThanOrEqual(displayColumns, WatchTerminalLayout.minimumReadableColumns)
        XCTAssertLessThanOrEqual(displayColumns, WatchTerminalLayout.maximumReadableColumns)
        XCTAssertEqual(
            WatchTerminalLayout.lineHeight(fontSize: WatchTerminalLayout.readableFontSize),
            WatchTerminalLayout.readableFontSize * WatchTerminalLayout.lineHeightRatio,
            accuracy: 0.001
        )
        XCTAssertEqual(WatchTerminalKeyBytes.slash, Data([0x2f]))
        XCTAssertEqual(WatchTerminalKeyBytes.carriageReturn, Data([0x0d]))
        XCTAssertEqual(WatchTerminalKeyBytes.control(0x43), Data([0x03]))
        XCTAssertEqual(
            String(data: WatchTerminalKeyBytes.wheel(scrollingUp: true, column: 8, row: 12), encoding: .utf8),
            "\u{1b}[<64;8;12M"
        )
        let input = WatchTerminalInput(data: WatchTerminalKeyBytes.slash, appendReturn: false)
        XCTAssertEqual(input.data, Data([0x2f]))
        let stagedText = WatchTerminalInput(data: Data("hello Pi".utf8), appendReturn: false)
        XCTAssertEqual(stagedText.data, Data("hello Pi".utf8))
        XCTAssertFalse(stagedText.appendReturn)
        let explicitSubmit = WatchTerminalInput(data: WatchTerminalKeyBytes.carriageReturn, appendReturn: false)
        XCTAssertEqual(explicitSubmit.data, Data([0x0d]))
        XCTAssertFalse(explicitSubmit.appendReturn)
    }

    func testWatchTerminalReadableLayoutWrapsOutputAndPinsPrompt() {
        let frame = WatchTerminalFrame(
            sequence: 5,
            columns: 80,
            rows: 3,
            cursorColumn: 5,
            cursorRow: 1,
            alternateScreen: true,
            mouseMode: true,
            historySize: 0,
            lines: ["alpha beta  ", "input command", "status"]
        )

        XCTAssertEqual(
            frame.readableOutputLines(displayColumns: 5, maximumLines: 4),
            ["alpha", " beta", "statu", "s"]
        )
        XCTAssertEqual(frame.promptViewport(displayColumns: 8), "input▌ c")
        XCTAssertEqual(WatchTerminalLayout.wrapTerminalLine("🙂abc  ", displayColumns: 2), ["🙂a", "bc"])
        XCTAssertEqual(WatchTerminalLayout.wrapTerminalLine("hello world", displayColumns: 8), ["hello", "world"])
        XCTAssertEqual(WatchTerminalLayout.wrapTerminalLine("──────────", displayColumns: 4), ["────"])
        XCTAssertEqual(WatchTerminalLayout.wrapTerminalLine("   ", displayColumns: 2), [""])
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
