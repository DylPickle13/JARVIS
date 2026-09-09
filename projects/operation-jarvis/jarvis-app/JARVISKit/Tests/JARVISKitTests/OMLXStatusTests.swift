import Foundation
import XCTest
@testable import JARVISKit

final class OMLXStatusTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }
    private let readyModel = #"{"id":"loaded","isLoading":false,"activeRequests":0,"queuedRequests":0,"requests":[]}"#

    func testSchemaVersionAndExactTwoServerIdentitiesFailClosed() throws {
        let good = #"{"ok":true,"version":1,"servers":[{"id":"mac-mini-64"},{"id":"mac-mini-16"}]}"#
        XCTAssertEqual(try decode(OMLXSnapshot.self, good).servers.count, 2)
        for bad in [good.replacingOccurrences(of: "\"version\":1", with: "\"version\":2"),
                    good.replacingOccurrences(of: "mac-mini-16", with: "mac-mini-64"),
                    good.replacingOccurrences(of: "mac-mini-16", with: "other-host"),
                    good.replacingOccurrences(of: "\"ok\":true", with: "\"ok\":false"),
                    #"{"ok":true,"version":1,"servers":[]}"#] {
            XCTAssertThrowsError(try decode(OMLXSnapshot.self, bad))
        }
    }

    func testLoadedIsReadyNotGeneratingAndMissingModelsAreUnknown() throws {
        let server = try decode(OMLXServerStatus.self, "{\"id\":\"mac-mini-64\",\"models\":[\(readyModel)]}")
        XCTAssertEqual(server.phase, .ready)
        XCTAssertEqual(server.idleModels.count, 1)
        XCTAssertTrue(server.busyModels.isEmpty)
        XCTAssertEqual(try decode(OMLXServerStatus.self, #"{"id":"mac-mini-16"}"#).phase, .unknown)
    }

    func testAllBusyModelsAndMixedRequestPhasesRemainVisible() throws {
        let mixed = #"{"id":"mixed","isLoading":false,"activeRequests":2,"queuedRequests":1,"requests":[{"id":"a","phase":"generating"},{"id":"b","phase":"prefill"},{"id":"c","phase":"queued"}]}"#
        let loading = #"{"id":"loading","isLoading":true,"activeRequests":0,"queuedRequests":0,"requests":[]}"#
        let server = try decode(OMLXServerStatus.self, "{\"id\":\"mac-mini-64\",\"models\":[\(mixed),\(readyModel),\(loading)]}")
        XCTAssertEqual(server.busyModels.map(\.id), ["mixed", "loading"])
        XCTAssertEqual(server.phase, .processing)
        XCTAssertEqual(server.busyModels[0].phase, .processing)
        XCTAssertEqual(server.busyModels[1].phase, .loading)
    }

    func testActiveWithoutRequestMetricsIsProcessingNeverIdle() throws {
        for (count, expected) in [(1, OMLXPhase.processing), (-1, .unknown)] {
            let value = readyModel.replacingOccurrences(of: "\"activeRequests\":0", with: "\"activeRequests\":\(count)")
            XCTAssertEqual(try decode(OMLXModelStatus.self, value).phase, expected)
        }
        let queued = readyModel.replacingOccurrences(of: "\"queuedRequests\":0", with: "\"queuedRequests\":1")
        XCTAssertEqual(try decode(OMLXModelStatus.self, queued).phase, .queued)
    }

    func testTruePrefillProgressIsClampedAndUnknownNeverInvented() throws {
        for (phase, done, total, expected) in [
            ("prefill", 25, 100, Optional(0.25)), ("prefill", 125, 100, Optional(1.0)),
            ("prefill", 1, 0, nil), ("prefill", -1, 100, nil),
            ("generating", 25, 100, nil), ("loading", 25, 100, nil), ("future", 25, 100, nil)
        ] {
            let json = "{\"id\":\"r\",\"phase\":\"\(phase)\",\"processedTokens\":\(done),\"totalTokens\":\(total)}"
            XCTAssertEqual(try decode(OMLXRequestStatus.self, json).prefillFraction, expected)
        }
        XCTAssertEqual(try decode(OMLXRequestStatus.self, #"{"id":"r","phase":"future"}"#).phase, .unknown)
    }

    func testSourceAgeExpiresEvenIfCachedHTTPPollKeepsSucceeding() throws {
        let server = try decode(OMLXServerStatus.self,
            #"{"id":"mac-mini-64","ok":true,"stale":false,"ageSeconds":4,"models":[]}"#)
        let received = Date(timeIntervalSince1970: 100)
        XCTAssertTrue(server.isFresh(requestStartedAt: received, now: received.addingTimeInterval(1)))
        XCTAssertFalse(server.isFresh(requestStartedAt: received, now: received.addingTimeInterval(3)))
        XCTAssertEqual(server.sourceAge(requestStartedAt: received, now: received.addingTimeInterval(3)), 7)
        XCTAssertFalse(server.isFresh(requestStartedAt: nil, now: received))
    }

    func testStaleMissingAgeOrFailedServerNeverLooksReady() throws {
        let base = #"{"id":"mac-mini-64","ok":true,"stale":false,"ageSeconds":0,"models":[]}"#
        let now = Date()
        for bad in [base.replacingOccurrences(of: "\"ok\":true", with: "\"ok\":false"),
                    base.replacingOccurrences(of: "\"stale\":false", with: "\"stale\":true"),
                    base.replacingOccurrences(of: "\"ageSeconds\":0", with: "\"ageSeconds\":null"),
                    base.replacingOccurrences(of: "\"ageSeconds\":0", with: "\"ageSeconds\":-1"),
                    base.replacingOccurrences(of: "\"models\":[]", with: "\"models\":null")] {
            XCTAssertFalse(try decode(OMLXServerStatus.self, bad).isFresh(requestStartedAt: now, now: now))
        }
    }
}
