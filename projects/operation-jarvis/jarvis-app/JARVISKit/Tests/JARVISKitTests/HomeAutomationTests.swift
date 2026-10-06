import Foundation
import XCTest
@testable import JARVISKit

final class HomeAutomationTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_700_000_000)

    private func state(enabled: Bool = false, revision: String = String(repeating: "a", count: 32),
                       expires: TimeInterval = 30, operation: HomeAutomationReceipt? = nil) -> HomeAutomationState {
        .init(available: true, enabled: enabled, revision: revision, observedAt: now.formatted(.iso8601),
              validUntil: now.addingTimeInterval(expires).formatted(.iso8601), operation: operation)
    }

    func testCompactPresentationRenamesVoiceWithoutChangingCommandIdentity() {
        XCTAssertEqual(HomeAutomationControl.automaticVoice.title, "Voice")
        XCTAssertEqual(HomeAutomationControl.automaticVoice.rawValue, "automatic-voice")
        XCTAssertEqual(HomeAutomationControl.barnDoor.title, "Barn Door Protocol")
        XCTAssertEqual(HomeAutomationControl.compactStatus("On"), "ON")
        XCTAssertEqual(HomeAutomationControl.compactStatus("Off"), "OFF")
        XCTAssertEqual(HomeAutomationControl.compactStatus("Unavailable"), "—")
        XCTAssertEqual(HomeAutomationControl.compactStatus("Changing…"), "…")
        XCTAssertEqual(HomeAutomationControl.compactStatus("Refreshing…"), "…")
        XCTAssertEqual(HomeAutomationControl.compactStatus("Unconfirmed"), "?")
        XCTAssertEqual(HomeAutomationControl.compactStatus("On", warning: true), "!")
    }

    func testOffIsAnAvailableConfigurationNotAnError() {
        let value = state()
        XCTAssertTrue(value.canChange(.automaticVoice, connected: true, now: now))
        XCTAssertEqual(value.label(connected: true, now: now), "Off")
        XCTAssertNil(value.outcomeWarning)
    }

    func testStaleOfflineUnsupportedAndMalformedStatesCannotAuthorizeWrites() {
        XCTAssertFalse(state(expires: -1).canChange(.automaticVoice, connected: true, now: now))
        XCTAssertFalse(state().canChange(.automaticVoice, connected: false, now: now))
        XCTAssertFalse(state(revision: "bad").canChange(.automaticVoice, connected: true, now: now))
        XCTAssertFalse(HomeAutomationState().canChange(.automaticVoice, connected: true, now: now))
        XCTAssertFalse(state(expires: 120).isFresh(now: now))
        XCTAssertEqual(state().label(connected: false, now: now), "Unavailable")
    }

    func testPendingIsNotOptimisticSuccessAndUnknownRetainsWarning() throws {
        let data = #"{"requestID":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","control":"automatic-voice","enabled":false,"status":"pending"}"#.data(using: .utf8)!
        let pending = try JSONDecoder().decode(HomeAutomationReceipt.self, from: data)
        let value = state(enabled: true, operation: pending)
        XCTAssertEqual(value.label(connected: true, now: now), "Changing…")
        XCTAssertFalse(value.canChange(.automaticVoice, connected: true, now: now))
        let unknown = try JSONDecoder().decode(HomeAutomationReceipt.self,
            from: String(data: data, encoding: .utf8)!.replacingOccurrences(of: "pending", with: "unknown").data(using: .utf8)!)
        XCTAssertNotNil(state(operation: unknown).outcomeWarning)
    }

    func testBarnDoorEnableRequiresExplicitConfirmation() {
        let revision = String(repeating: "b", count: 64)
        XCTAssertFalse(HomeAutomationCommand(control: .barnDoor, enabled: true, revision: revision).isValid)
        XCTAssertTrue(HomeAutomationCommand(control: .barnDoor, enabled: true, revision: revision, confirmed: true).isValid)
        XCTAssertTrue(HomeAutomationCommand(control: .barnDoor, enabled: false, revision: revision).isValid)
        XCTAssertFalse(HomeAutomationCommand(control: .automaticVoice, enabled: false, revision: revision).isValid)
    }

    func testOldSnapshotAndMalformedCardDoNotBreakExistingHealthDecode() throws {
        let decoder = JSONDecoder()
        XCTAssertNil(try decoder.decode(StateSnapshot.self, from: Data(#"{"ok":true}"#.utf8)).homeAutomations)
        let data = Data(#"{"ok":true,"homeAutomations":{"automaticVoice":{"enabled":"bad"},"barnDoor":{"available":false}}}"#.utf8)
        let value = try decoder.decode(StateSnapshot.self, from: data)
        XCTAssertTrue(value.ok)
        XCTAssertNil(value.homeAutomations?.automaticVoice)
        XCTAssertEqual(value.homeAutomations?.barnDoor?.available, false)
    }

    func testRelayRoundTripPreservesIdentityDesiredStateAndConfirmation() throws {
        let command = HomeAutomationCommand(control: .barnDoor, enabled: true,
            revision: String(repeating: "c", count: 64), confirmed: true)
        let encoded = try JSONEncoder().encode(command)
        XCTAssertEqual(try JSONDecoder().decode(HomeAutomationCommand.self, from: encoded), command)
        XCTAssertEqual(command.requestID.count, 32)
        XCTAssertTrue(command.isValid)
    }

    func testNativeTransportUsesOneGuardedRequestAndMatchesReceipt() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel(); MockURLProtocol.handler = nil }
        let client = JarvisClient(session: session)
        let command = HomeAutomationCommand(control: .automaticVoice, enabled: false,
            revision: String(repeating: "d", count: 32))
        var calls = 0
        MockURLProtocol.handler = { request in
            calls += 1
            XCTAssertEqual(request.url?.path, "/api/v1/home-automation-command")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "x-jarvis-request-id"), command.requestID)
            XCTAssertEqual(request.value(forHTTPHeaderField: "x-jarvis-token"), "test")
            return MockURLProtocol.response(request, status: 202,
                body: "{\"ok\":true,\"action\":\"home-automation-set\",\"homeAutomation\":{\"requestID\":\"\(command.requestID)\",\"control\":\"automatic-voice\",\"enabled\":false,\"status\":\"pending\"}}")
        }
        let result = try await client.setHomeAutomation(.init(baseURL: URL(string: "http://fixture.invalid")!, token: "test"), command: command)
        XCTAssertEqual(result.homeAutomation?.status, "pending")
        XCTAssertEqual(calls, 1)
    }

    func testTransportFailureNeverFallsBackOrRetries() async {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel(); MockURLProtocol.handler = nil }
        var calls = 0
        MockURLProtocol.handler = { _ in calls += 1; throw URLError(.timedOut) }
        let command = HomeAutomationCommand(control: .automaticVoice, enabled: false,
            revision: String(repeating: "d", count: 32))
        do {
            _ = try await JarvisClient(session: session).setHomeAutomation(.init(baseURL: URL(string: "http://fixture.invalid")!, token: ""), command: command)
            XCTFail("Expected uncertainty")
        } catch {}
        XCTAssertEqual(calls, 1)
    }
}
