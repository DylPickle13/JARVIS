import XCTest
@testable import JARVISKit

final class JARVISKitTests: XCTestCase {
    func testAirQualityGaugeIsFullForOneAndDrainsAsPollutionRises() {
        XCTAssertEqual(AirQualityGauge.cleanlinessProgress(pm25: nil), 0)
        XCTAssertEqual(AirQualityGauge.cleanlinessProgress(pm25: 0), 1)
        XCTAssertEqual(AirQualityGauge.cleanlinessProgress(pm25: 1), 1)
        XCTAssertEqual(AirQualityGauge.cleanlinessProgress(pm25: 38), 0.5, accuracy: 0.0001)
        XCTAssertEqual(AirQualityGauge.cleanlinessProgress(pm25: 75), 0)
        XCTAssertEqual(AirQualityGauge.cleanlinessProgress(pm25: 100), 0)
    }

    func testCodexQuotaBecomesCriticalOnlyBelowThirtyPercent() {
        XCTAssertTrue(CodexQuotaPresentationPolicy.isCritical(remainingPercent: 29.999))
        XCTAssertTrue(CodexQuotaPresentationPolicy.isCritical(remainingPercent: 0))
        XCTAssertFalse(CodexQuotaPresentationPolicy.isCritical(remainingPercent: 30))
        XCTAssertFalse(CodexQuotaPresentationPolicy.isCritical(remainingPercent: 100))
    }

    func testPiMobileSessionsDecodeIndividuallyAndRemainBackwardCompatible() throws {
        let state = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(
                #"{"ok":true,"subsystems":{"pi":{"ok":true,"active":2,"mobileSessions":[{"sessionID":1,"active":true},{"sessionID":2,"active":false},{"sessionID":3,"active":null}]}}}"#.utf8
            )
        )
        let sessions = try XCTUnwrap(state.subsystems?.pi?.mobileSessions)
        XCTAssertEqual(
            sessions,
            [
                PiMobileSession(sessionID: 1, active: true),
                PiMobileSession(sessionID: 2, active: false),
                PiMobileSession(sessionID: 3, active: nil),
            ]
        )

        let legacy = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(#"{"ok":true,"subsystems":{"pi":{"ok":true,"active":3}}}"#.utf8)
        )
        XCTAssertNil(legacy.subsystems?.pi?.mobileSessions)
    }

    func testNeuralCoreMapsOnlyUsableCachedTelemetry() throws {
        let state = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(
                #"{"ok":true,"summary":{"pm25":3},"subsystems":{"pi":{"ok":true,"stale":false,"active":3},"plugs":{"ok":true,"stale":false,"plugs":{"family-room-light":{"ok":true,"isOn":true},"lamp":{"ok":true,"isOn":false},"pedalboard":{"ok":false,"isOn":true},"tv":{"ok":true,"stale":true,"isOn":true}}},"purifier":{"ok":true,"stale":false,"pm25":3},"network":{"ok":true,"stale":false,"macLanIp":"192.168.21.215"},"codexQuota":{"ok":true,"available":true,"stale":false,"weekly":{"remainingPercent":30}}}}"#.utf8
            )
        )
        let now = Date(timeIntervalSince1970: 1_000)
        let telemetry = JARVISNeuralCoreTelemetry(
            cached: CachedState(state: state, savedAt: now),
            now: now.addingTimeInterval(60)
        )

        XCTAssertFalse(telemetry.signalLost)
        XCTAssertEqual(telemetry.piSessions, 3)
        XCTAssertEqual(telemetry.illuminatedSpokes, 6)
        XCTAssertEqual(telemetry.plugStates, [.on, .off, .unknown, .unknown])
        XCTAssertEqual(telemetry.codexRemainingPercent, 30)
        XCTAssertFalse(telemetry.codexIsCritical, "Exactly 30 percent remains electric blue")
        XCTAssertEqual(telemetry.pm25, 3)
        XCTAssertEqual(telemetry.linkLabel, "LAN")
    }

    func testNeuralCoreFailsClosedWhenSnapshotIsMissingOrStale() throws {
        let missing = JARVISNeuralCoreTelemetry(cached: nil)
        XCTAssertTrue(missing.signalLost)
        XCTAssertEqual(missing.illuminatedSpokes, 0)
        XCTAssertEqual(missing.plugStates, Array(repeating: .unknown, count: 4))

        let state = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(#"{"ok":true,"subsystems":{"pi":{"ok":true,"active":4},"codexQuota":{"ok":true,"available":true,"weekly":{"remainingPercent":12}},"purifier":{"ok":true,"pm25":2}}}"#.utf8)
        )
        let savedAt = Date(timeIntervalSince1970: 1_000)
        let stale = JARVISNeuralCoreTelemetry(
            cached: CachedState(state: state, savedAt: savedAt),
            now: savedAt.addingTimeInterval(JARVISWidgetStateLoader.staleAfter + 1)
        )
        XCTAssertTrue(stale.signalLost)
        XCTAssertNil(stale.piSessions)
        XCTAssertEqual(stale.illuminatedSpokes, 0)
        XCTAssertNil(stale.codexRemainingPercent)
        XCTAssertFalse(stale.codexIsCritical)
        XCTAssertNil(stale.pm25)
        XCTAssertNil(stale.linkLabel)
    }

    func testNeuralCorePlaceholderIsExplicitlyIllustrative() {
        let placeholder = JARVISNeuralCoreTelemetry(cached: nil, placeholder: true)
        XCTAssertFalse(placeholder.signalLost)
        XCTAssertEqual(placeholder.piSessions, 2)
        XCTAssertEqual(placeholder.illuminatedSpokes, 4)
        XCTAssertEqual(placeholder.codexRemainingPercent, 82)
        XCTAssertEqual(placeholder.pm25, 3)
        XCTAssertEqual(placeholder.linkLabel, "LAN")
    }

    func testNeuralCoreMotionAdvancesByQuarterCycleAtWidgetCadence() {
        let start = Date(timeIntervalSinceReferenceDate: 0)
        XCTAssertEqual(JARVISNeuralCoreMotion.phase(for: start), 0, accuracy: 0.000_001)
        XCTAssertEqual(
            JARVISNeuralCoreMotion.phase(for: start.addingTimeInterval(15 * 60)),
            0.25,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            JARVISNeuralCoreMotion.phase(for: start.addingTimeInterval(30 * 60)),
            0.50,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            JARVISNeuralCoreMotion.phase(for: start.addingTimeInterval(45 * 60)),
            0.75,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            JARVISNeuralCoreMotion.phase(for: start.addingTimeInterval(60 * 60)),
            0,
            accuracy: 0.000_001
        )
        XCTAssertLessThanOrEqual(JARVISNeuralCoreMotion.transitionDuration, 2)
    }

    func testNeuralCoreContinuousMotionDoesNotDependOnTelemetryFreshness() {
        let unavailableTelemetry = JARVISNeuralCoreTelemetry(cached: nil)
        XCTAssertTrue(unavailableTelemetry.signalLost)
        XCTAssertEqual(
            JARVISNeuralCoreContinuousMotionPolicy.decision(
                allowsMotion: true,
                isLuminanceReduced: false,
                accessibilityReduceMotion: false,
                fontAvailable: true
            ),
            .animate
        )
    }

    func testNeuralCoreArtworkKeepsDistinctWatchPhasesWhenTelemetryIsUnavailable() {
        let unavailableTelemetry = JARVISNeuralCoreTelemetry(cached: nil)
        XCTAssertTrue(unavailableTelemetry.signalLost)
        XCTAssertTrue(
            JARVISNeuralCoreArtworkMotionPolicy.isMotionEnabled(
                allowsMotion: true,
                isLuminanceReduced: false,
                accessibilityReduceMotion: false
            )
        )

        let phases = (0..<JARVISNeuralCoreMotion.watchContinuousFrameCount).map {
            JARVISNeuralCoreMotion.continuousPhase(
                basePhase: JARVISNeuralCoreMotion.continuousSynchronizedBasePhase,
                frameIndex: $0,
                frameCount: JARVISNeuralCoreMotion.watchContinuousFrameCount
            )
        }
        XCTAssertEqual(Set(phases).count, JARVISNeuralCoreMotion.watchContinuousFrameCount)
    }

    func testNeuralCoreArtworkMotionPreservesSystemGates() {
        XCTAssertFalse(
            JARVISNeuralCoreArtworkMotionPolicy.isMotionEnabled(
                allowsMotion: false,
                isLuminanceReduced: false,
                accessibilityReduceMotion: false
            )
        )
        XCTAssertFalse(
            JARVISNeuralCoreArtworkMotionPolicy.isMotionEnabled(
                allowsMotion: true,
                isLuminanceReduced: true,
                accessibilityReduceMotion: false
            )
        )
        XCTAssertFalse(
            JARVISNeuralCoreArtworkMotionPolicy.isMotionEnabled(
                allowsMotion: true,
                isLuminanceReduced: false,
                accessibilityReduceMotion: true
            )
        )
    }

    func testNeuralCoreContinuousMotionPreservesSystemAndFontGates() {
        XCTAssertEqual(
            JARVISNeuralCoreContinuousMotionPolicy.decision(
                allowsMotion: false,
                isLuminanceReduced: false,
                accessibilityReduceMotion: false,
                fontAvailable: true
            ),
            .hostDisallowed
        )
        XCTAssertEqual(
            JARVISNeuralCoreContinuousMotionPolicy.decision(
                allowsMotion: true,
                isLuminanceReduced: true,
                accessibilityReduceMotion: false,
                fontAvailable: true
            ),
            .luminanceReduced
        )
        XCTAssertEqual(
            JARVISNeuralCoreContinuousMotionPolicy.decision(
                allowsMotion: true,
                isLuminanceReduced: false,
                accessibilityReduceMotion: true,
                fontAvailable: true
            ),
            .reduceMotion
        )
        XCTAssertEqual(
            JARVISNeuralCoreContinuousMotionPolicy.decision(
                allowsMotion: true,
                isLuminanceReduced: false,
                accessibilityReduceMotion: false,
                fontAvailable: false
            ),
            .fontUnavailable
        )
    }

    func testNeuralCoreWidgetReloadPolicyIsBoundedAndClockSafe() {
        let now = Date(timeIntervalSinceReferenceDate: 10_000)
        let interval = JARVISNeuralCoreWidgetReloadPolicy.minimumInterval
        XCTAssertTrue(
            JARVISNeuralCoreWidgetReloadPolicy.shouldRequestReload(
                lastRequestedAt: nil,
                now: now
            )
        )
        XCTAssertFalse(
            JARVISNeuralCoreWidgetReloadPolicy.shouldRequestReload(
                lastRequestedAt: now.addingTimeInterval(-(interval - 1)),
                now: now
            )
        )
        XCTAssertTrue(
            JARVISNeuralCoreWidgetReloadPolicy.shouldRequestReload(
                lastRequestedAt: now.addingTimeInterval(-interval),
                now: now
            )
        )
        XCTAssertTrue(
            JARVISNeuralCoreWidgetReloadPolicy.shouldRequestReload(
                lastRequestedAt: now.addingTimeInterval(1),
                now: now
            )
        )
    }

    func testWidgetRefreshDeadlineReturnsCompletedOperation() async throws {
        let value = try await JARVISWidgetRefreshDeadline.run(seconds: 1) {
            "complete"
        }
        XCTAssertEqual(value, "complete")
    }

    func testWidgetRefreshDeadlineExpiresAndCancelsOperation() async {
        do {
            _ = try await JARVISWidgetRefreshDeadline.run(seconds: 0.05) {
                try await Task.sleep(nanoseconds: 5_000_000_000)
                return "late"
            }
            XCTFail("Expected the widget refresh deadline to expire")
        } catch {
            XCTAssertEqual(error as? JARVISWidgetRefreshDeadlineError, .exceeded)
        }
    }

    func testNeuralCoreMotionNormalizesDatesBeforeReferenceEpoch() {
        let date = Date(timeIntervalSinceReferenceDate: -15 * 60)
        XCTAssertEqual(JARVISNeuralCoreMotion.phase(for: date), 0.75, accuracy: 0.000_001)
    }

    func testNeuralCoreContinuousFramesCoverOneNormalizedCycle() {
        XCTAssertEqual(JARVISNeuralCoreMotion.phoneContinuousFrameCount, 48)
        XCTAssertEqual(JARVISNeuralCoreMotion.watchContinuousFrameCount, 48)
        XCTAssertEqual(JARVISNeuralCoreMotion.continuousLoopDuration, 2)
        XCTAssertEqual(
            JARVISNeuralCoreMotion.continuousFrameDuration(
                frameCount: JARVISNeuralCoreMotion.phoneContinuousFrameCount
            ),
            1.0 / 24.0,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            JARVISNeuralCoreMotion.continuousFrameDuration(
                frameCount: JARVISNeuralCoreMotion.watchContinuousFrameCount
            ),
            1.0 / 24.0,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            JARVISNeuralCoreMotion.continuousReferenceDate.timeIntervalSinceReferenceDate,
            0,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            JARVISNeuralCoreMotion.continuousSynchronizedBasePhase,
            0,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            JARVISNeuralCoreMotion.continuousPhase(
                basePhase: JARVISNeuralCoreMotion.continuousSynchronizedBasePhase,
                frameIndex: 12,
                frameCount: JARVISNeuralCoreMotion.phoneContinuousFrameCount
            ),
            JARVISNeuralCoreMotion.continuousPhase(
                basePhase: JARVISNeuralCoreMotion.continuousSynchronizedBasePhase,
                frameIndex: 12,
                frameCount: JARVISNeuralCoreMotion.watchContinuousFrameCount
            ),
            accuracy: 0.000_001
        )

        for frameCount in [
            JARVISNeuralCoreMotion.phoneContinuousFrameCount,
            JARVISNeuralCoreMotion.watchContinuousFrameCount
        ] {
            let phases = (0..<frameCount).map {
                JARVISNeuralCoreMotion.continuousPhase(
                    basePhase: 0.9,
                    frameIndex: $0,
                    frameCount: frameCount
                )
            }
            XCTAssertEqual(Set(phases).count, frameCount)
            XCTAssertTrue(phases.allSatisfy { $0 >= 0 && $0 < 1 })
            XCTAssertEqual(phases[0], 0.9, accuracy: 0.000_001)
            XCTAssertEqual(phases[frameCount / 2], 0.4, accuracy: 0.000_001)
            XCTAssertEqual(
                JARVISNeuralCoreMotion.continuousPhase(
                    basePhase: 0.1,
                    frameIndex: -1,
                    frameCount: frameCount
                ),
                0.1 + Double(frameCount - 1) / Double(frameCount) - 1,
                accuracy: 0.000_001
            )
        }
    }

    func testWatchTerminalBrightensDarkForegroundsWithoutChangingBlackOrBrightCells() {
        XCTAssertEqual(
            WatchTerminalLayout.brightenedForeground(WatchTerminalRGBColor(red: 102, green: 102, blue: 102)),
            WatchTerminalRGBColor(red: 188, green: 188, blue: 188)
        )
        XCTAssertEqual(
            WatchTerminalLayout.brightenedForeground(WatchTerminalRGBColor(red: 178, green: 148, blue: 187)),
            WatchTerminalRGBColor(red: 205, green: 175, blue: 214)
        )
        XCTAssertEqual(
            WatchTerminalLayout.brightenedForeground(WatchTerminalRGBColor(red: 229, green: 229, blue: 229)),
            WatchTerminalRGBColor(red: 229, green: 229, blue: 229)
        )
        XCTAssertEqual(
            WatchTerminalLayout.brightenedForeground(WatchTerminalRGBColor(red: 0, green: 0, blue: 0)),
            WatchTerminalRGBColor(red: 0, green: 0, blue: 0)
        )
    }

    func testNativeAppsUseFastVisibleControlsAndModestBackgroundPages() {
        XCTAssertEqual(JARVISRefreshPolicy.activeInterval, .seconds(15))
        XCTAssertEqual(JARVISRefreshPolicy.controlActiveInterval, .seconds(5))
        XCTAssertEqual(JARVISRefreshPolicy.visibleCodexRefreshInterval, 60)
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

    func testEndpointURLPolicyNormalizesApprovedHTTPAndHTTPSRoots() throws {
        XCTAssertEqual(
            JarvisEndpointURLPolicy.parse(" 192.168.21.215:8790 ")?.absoluteString,
            "http://192.168.21.215:8790"
        )
        XCTAssertEqual(
            JarvisEndpointURLPolicy.parse("HTTPS://Example.COM:8790/")?.absoluteString,
            "https://example.com:8790"
        )
        XCTAssertEqual(
            JarvisEndpointURLPolicy.parse("[::1]:8790")?.absoluteString,
            "http://[::1]:8790"
        )
        XCTAssertTrue(JarvisEndpoints.defaults.allSatisfy { JarvisEndpointURLPolicy.parse($0) != nil })
    }

    func testEndpointURLPolicyRejectsUnsupportedOrAmbiguousAuthorities() {
        let rejected = [
            "ftp://jarvis.test:8790",
            "ftp:8790",
            "file:///tmp/jarvis.sock",
            "https://user:password@jarvis.test:8790",
            "https://jarvis.test:8790/api",
            "https://jarvis.test:8790?token=leak",
            "https://jarvis.test:8790#fragment",
            "https://:8790",
            "https://jarvis.test:",
            "https://jarvis.test:0",
            "https://jarvis.test:65536",
            "https://jarvis.test:not-a-port",
        ]
        for value in rejected {
            XCTAssertNil(JarvisEndpointURLPolicy.parse(value), value)
        }
    }

    func testEndpointStorePersistsOnlyNormalizedValidEndpoints() {
        let suite = "jarvis.endpoint-policy.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = EndpointStore(defaults: defaults)

        store.endpointURLString = " HTTPS://Example.COM:8790/ "
        XCTAssertEqual(store.endpointURLString, "https://example.com:8790")
        XCTAssertEqual(store.endpointURL?.absoluteString, "https://example.com:8790")

        store.endpointURLString = "ftp://untrusted.test:8790"
        XCTAssertEqual(store.endpointURLString, "https://example.com:8790")

        defaults.set("file:///tmp/legacy", forKey: "jarvis.endpoint.url")
        XCTAssertNil(store.endpointURL)
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

    func testPurifierPendingVerificationDecodesAsProgressNotGenericStaleness() throws {
        let commandResult = try JSONDecoder().decode(
            CommandResult.self,
            from: Data(
                #"{"ok":true,"action":"purifier-set","airPurifier":{"ok":true,"data":{"mode":"sleep","verification_pending":true}}}"#.utf8
            )
        )
        XCTAssertTrue(commandResult.purifierVerificationPending)

        let snapshot = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(
                #"{"ok":true,"stale":true,"subsystems":{"purifier":{"ok":true,"stale":true,"verificationPending":true,"pendingCommand":{"setting":"mode","value":"auto"},"isOn":true,"mode":"sleep"}}}"#.utf8
            )
        )
        XCTAssertEqual(snapshot.subsystems?.purifier?.verificationPending, true)
        XCTAssertEqual(snapshot.subsystems?.purifier?.pendingCommand?.setting, "mode")
        XCTAssertEqual(snapshot.subsystems?.purifier?.pendingCommand?.value, "auto")
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

    func testWidgetStateHelperFailsClosedWhenStale() throws {
        let state = try JSONDecoder().decode(
            StateSnapshot.self,
            from: Data(#"{"ok":true,"subsystems":{"plugs":{"ok":true,"plugs":{"tv":{"ok":true,"isOn":false},"lamp":{"ok":true,"isOn":true}}}}}"#.utf8)
        )
        let savedAt = Date(timeIntervalSince1970: 1_000)
        let cached = CachedState(state: state, savedAt: savedAt)

        XCTAssertFalse(JARVISWidgetStateLoader.isStale(cached, now: savedAt.addingTimeInterval(60)))
        XCTAssertTrue(
            JARVISWidgetStateLoader.isStale(
                cached,
                now: savedAt.addingTimeInterval(JARVISWidgetStateLoader.staleAfter + 1)
            )
        )
        XCTAssertTrue(JARVISWidgetStateLoader.isStale(nil))
    }

    func testConfirmedPlugStateUpdatesSnapshotCacheImmediately() throws {
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

    func testWatchCommandErrorRoundTrips() throws {
        let payload = WatchCommandError(message: "The relay timed out.")
        let decoded = try JSONDecoder().decode(
            WatchCommandError.self,
            from: JSONEncoder().encode(payload)
        )
        XCTAssertEqual(decoded, payload)
    }

    func testWatchRelayCommandDeliveryRejectsExpiredMalformedAndFutureMessages() {
        let sent = Date(timeIntervalSince1970: 2_000)
        let timestamp = ISO8601DateFormatter().string(from: sent)

        XCTAssertTrue(WatchRelayCommandPolicy.isFresh(sentAt: timestamp, now: sent))
        XCTAssertTrue(
            WatchRelayCommandPolicy.isFresh(
                sentAt: timestamp,
                now: sent.addingTimeInterval(WatchRelayCommandPolicy.maximumDeliveryAge)
            )
        )
        XCTAssertFalse(
            WatchRelayCommandPolicy.isFresh(
                sentAt: timestamp,
                now: sent.addingTimeInterval(WatchRelayCommandPolicy.maximumDeliveryAge + 0.001)
            )
        )
        XCTAssertTrue(
            WatchRelayCommandPolicy.isFresh(
                sentAt: timestamp,
                now: sent.addingTimeInterval(-WatchRelayCommandPolicy.maximumFutureClockSkew)
            )
        )
        XCTAssertFalse(
            WatchRelayCommandPolicy.isFresh(
                sentAt: timestamp,
                now: sent.addingTimeInterval(-WatchRelayCommandPolicy.maximumFutureClockSkew - 0.001)
            )
        )
        XCTAssertFalse(WatchRelayCommandPolicy.isFresh(sentAt: nil, now: sent))
        XCTAssertFalse(WatchRelayCommandPolicy.isFresh(sentAt: "not-a-date", now: sent))
    }

    func testWatchRelayCommandDeliveryAcceptsFractionalISO8601Timestamp() {
        let sentAt = "2026-08-29T12:34:56.250Z"
        let now = ISO8601DateFormatter().date(from: "2026-08-29T12:35:00Z")!
        XCTAssertTrue(WatchRelayCommandPolicy.isFresh(sentAt: sentAt, now: now))
    }

    func testWatchStatePublicationAcceptsOnlyNewerTimestampedSnapshots() {
        let current = StateSnapshot(
            ok: true,
            generatedAt: "2026-08-29T12:34:56.100Z",
            summary: Summary(plugsOn: 1, plugsTotal: 2, purifierOn: true, pm25: 3, piActive: 1)
        )
        let older = StateSnapshot(ok: true, generatedAt: "2026-08-29T12:34:55Z")
        let sameGenerationChanged = StateSnapshot(ok: false, generatedAt: "2026-08-29T12:34:56.100Z")
        let newer = StateSnapshot(ok: true, generatedAt: "2026-08-29T12:34:56.250Z")

        XCTAssertFalse(WatchStatePublicationPolicy.shouldAccept(current, over: current))
        XCTAssertFalse(WatchStatePublicationPolicy.shouldAccept(older, over: current))
        XCTAssertFalse(WatchStatePublicationPolicy.shouldAccept(sameGenerationChanged, over: current))
        XCTAssertTrue(WatchStatePublicationPolicy.shouldAccept(newer, over: current))
    }

    func testWatchStatePublicationFailsClosedWhenOnlyIncomingTimestampIsMalformed() {
        let timestamped = StateSnapshot(ok: true, generatedAt: "2026-08-29T12:34:56Z")
        let malformed = StateSnapshot(ok: false, generatedAt: "not-a-date")

        XCTAssertFalse(WatchStatePublicationPolicy.shouldAccept(malformed, over: timestamped))
        XCTAssertTrue(WatchStatePublicationPolicy.shouldAccept(timestamped, over: malformed))
        XCTAssertTrue(WatchStatePublicationPolicy.shouldAccept(timestamped, over: nil))
    }

    func testWatchStatePublicationRetainsLegacyUntimestampedCompatibility() {
        let current = StateSnapshot(ok: true)
        let changed = StateSnapshot(ok: false)

        XCTAssertFalse(WatchStatePublicationPolicy.shouldAccept(current, over: current))
        XCTAssertTrue(WatchStatePublicationPolicy.shouldAccept(changed, over: current))
    }

    func testWatchPurifierCommandsAreClosedValidatedAndMatchConfirmedState() throws {
        let purifier = try JSONDecoder().decode(
            PurifierSubsystem.self,
            from: Data(#"{"ok":true,"stale":false,"isOn":true,"mode":"manual","fanLevel":3}"#.utf8)
        )
        let power = WatchPurifierCommand.power(true)
        let mode = try XCTUnwrap(WatchPurifierCommand.mode("MANUAL"))
        let speed = try XCTUnwrap(WatchPurifierCommand.speed(3))

        XCTAssertTrue(power.isValid)
        XCTAssertTrue(mode.isValid)
        XCTAssertTrue(speed.isValid)
        XCTAssertTrue(power.matches(purifier))
        XCTAssertTrue(mode.matches(purifier))
        XCTAssertTrue(speed.matches(purifier))
        XCTAssertEqual(power.parameters, ["setting": .string("power"), "value": .string("on")])
        XCTAssertEqual(speed.parameters, ["setting": .string("speed"), "level": .number(3)])
        XCTAssertNil(WatchPurifierCommand.mode("turbo"))
        XCTAssertNil(WatchPurifierCommand.speed(5))

        let decoded = try JSONDecoder().decode(
            WatchPurifierCommand.self,
            from: JSONEncoder().encode(speed)
        )
        XCTAssertEqual(decoded, speed)

        let invalid = try JSONDecoder().decode(
            WatchPurifierCommand.self,
            from: Data(#"{"setting":"speed","level":5}"#.utf8)
        )
        XCTAssertFalse(invalid.isValid)
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
        XCTAssertEqual(WatchTerminalKeyBytes.backspace, Data([0x7f]))
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

    func testSigningRenewalProgressOrdersAllSevenSteps() {
        let status = SigningRenewalStatus(
            ok: true,
            available: true,
            phase: "auditing",
            running: true
        )

        XCTAssertEqual(SigningRenewalStep.allCases.count, 7)
        XCTAssertEqual(status.activeStep, .auditing)
        XCTAssertEqual(status.completedStepCount, 3)
        XCTAssertEqual(status.displayedStepNumber, 4)
        XCTAssertEqual(status.state(for: .preparing), .completed)
        XCTAssertEqual(status.state(for: .auditing), .current)
        XCTAssertEqual(status.state(for: .installingIPhone), .pending)
    }

    func testSigningRenewalFailureRetainsExactFailedStep() {
        let status = SigningRenewalStatus(
            ok: false,
            available: true,
            phase: "failed",
            running: false,
            failedPhase: "installingWatch"
        )

        XCTAssertEqual(status.activeStep, .installingWatch)
        XCTAssertEqual(status.displayedStepNumber, 6)
        XCTAssertEqual(status.state(for: .installingIPhone), .completed)
        XCTAssertEqual(status.state(for: .installingWatch), .failed)
        XCTAssertEqual(status.state(for: .verifying), .pending)
    }

    func testSigningRenewalSuccessCompletesEveryStep() {
        let status = SigningRenewalStatus(
            ok: true,
            available: true,
            phase: "succeeded",
            running: false
        )

        XCTAssertEqual(status.completedStepCount, 7)
        XCTAssertEqual(status.displayedStepNumber, 7)
        XCTAssertTrue(SigningRenewalStep.allCases.allSatisfy { status.state(for: $0) == .completed })
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
