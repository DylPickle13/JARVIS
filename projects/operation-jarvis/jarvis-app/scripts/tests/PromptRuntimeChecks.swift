import Foundation
import XCTest
import JARVISKit

final class PromptRuntimeChecks: XCTestCase {
    func testNativeCompletionAcceptsOnlyOnce() {
        var gate = JARVISTalkInputCompletion()
        XCTAssertEqual(gate.consume(["hello"]), "hello")
        XCTAssertNil(gate.consume(["duplicate"]))
    }

    func testNativeCancellationCannotLaterSubmit() {
        var gate = JARVISTalkInputCompletion()
        XCTAssertNil(gate.consume(nil))
        XCTAssertNil(gate.consume(["late callback"]))
    }

    func testNativeBlankAndNonTextResultsDoNotSubmit() {
        let cases: [[Any]] = [[], ["  \n"], [42]]
        for results in cases {
            var gate = JARVISTalkInputCompletion()
            XCTAssertNil(gate.consume(results))
            XCTAssertTrue(gate.consumed)
        }
    }

    private var configuration: WatchTerminalConfiguration {
        .init(endpoint: "https://localhost:8792", token: "fixture-only", certificateSHA256: String(repeating: "a", count: 64))
    }

    func testTalkRouteIsDistinctFromTerminal() {
        XCTAssertTrue(JARVISPromptNavigation.isTalkURL(URL(string: "jarvis://talk")!))
        XCTAssertFalse(JARVISPromptNavigation.isTalkURL(URL(string: "jarvis://terminal")!))
        XCTAssertFalse(JARVISPromptNavigation.isTalkURL(URL(string: "https://talk")!))
        XCTAssertFalse(JARVISPromptNavigation.isTerminalURL(URL(string: "jarvis://talk")!))
    }

    func testConfirmedSubmissionUsesOneDeliveryAndReturnedSlot() async {
        var calls = 0
        let result = await JARVISPromptRuntime.submit("  test once  ", configurationLoader: { .configured(self.configuration) }, delivery: { _, prompt in
            calls += 1
            XCTAssertEqual(prompt, "test once")
            return .nine
        })
        XCTAssertEqual(result, .sent(.nine))
        XCTAssertEqual(calls, 1)
    }

    func testBlankPromptNeverLoadsCredentialsOrDelivers() async {
        let result = await JARVISPromptRuntime.submit(" \n ", configurationLoader: {
            XCTFail("Blank input must not load credentials")
            return .missing
        }, delivery: { _, _ in
            XCTFail("Blank input must not send")
            return .one
        })
        XCTAssertEqual(result, .empty)
    }

    func testLockedCredentialsNeverDeliver() async {
        let result = await JARVISPromptRuntime.submit("test", configurationLoader: { .locked }, delivery: { _, _ in
            XCTFail("Locked credentials must not send")
            return .one
        })
        XCTAssertEqual(result, .locked)
    }

    func testNoCapacityIsExplicitRefusalWithoutRetry() async {
        var calls = 0
        let result = await JARVISPromptRuntime.submit("test", configurationLoader: { .configured(self.configuration) }, delivery: { _, _ in
            calls += 1
            throw JARVISNewSessionError.noAvailableSession
        })
        XCTAssertEqual(result, .noNewSession)
        XCTAssertEqual(calls, 1)
    }

    func testUnconfirmedDeliveryIsNotRetried() async {
        var calls = 0
        let result = await JARVISPromptRuntime.submit("test", configurationLoader: { .configured(self.configuration) }, delivery: { _, _ in
            calls += 1
            throw WatchTerminalClientError.submissionUnconfirmed
        })
        XCTAssertEqual(result, .unconfirmed)
        XCTAssertEqual(calls, 1)
    }

    func testIdentityFailureDoesNotFallBack() async {
        var calls = 0
        let result = await JARVISPromptRuntime.submit("test", configurationLoader: { .configured(self.configuration) }, delivery: { _, _ in
            calls += 1
            throw WatchTerminalClientError.certificateRejected
        })
        XCTAssertEqual(result, .identityMismatch)
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testNavigationPersistsUntilSelectionSucceedsAndConsumesOnce() {
        let suite = "jarvis.prompt.test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        JARVISPromptNavigation.requestTerminalPresentation(slot: .nine, defaults: defaults, notificationCenter: NotificationCenter())
        XCTAssertFalse(JARVISPromptNavigation.consumeTerminalPresentationRequest(defaults: defaults, select: { _ in false }))
        XCTAssertTrue(JARVISPromptNavigation.consumeTerminalPresentationRequest(defaults: defaults, select: { $0 == .nine }))
        XCTAssertFalse(JARVISPromptNavigation.consumeTerminalPresentationRequest(defaults: defaults, select: { _ in XCTFail("Already consumed"); return true }))
    }
}
