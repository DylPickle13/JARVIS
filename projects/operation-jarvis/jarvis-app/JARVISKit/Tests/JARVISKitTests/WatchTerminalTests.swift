import Foundation
import XCTest
@testable import JARVISKit

final class WatchTerminalTests: XCTestCase {
    override func tearDown() {
        TerminalURLProtocol.handler = nil
        super.tearDown()
    }

    func testANSIParserMirrorsPiStylesWithoutSemanticReconstruction() {
        let lines = [
            "\u{1b}[3m\u{1b}[38;2;128;128;128mThinking\u{1b}[0m",
            "\u{1b}[48;2;40;50;40m\u{1b}[1m$ tool",
            "continued tool block\u{1b}[0m",
            "\u{1b}[7m cursor \u{1b}[0m",
        ]
        let parsed = WatchTerminalANSIParser.parse(lines: lines)

        XCTAssertEqual(parsed[0].map(\.text).joined(), "Thinking")
        XCTAssertTrue(parsed[0][0].style.italic)
        XCTAssertEqual(
            parsed[0][0].style.foreground,
            .rgb(WatchTerminalRGBColor(red: 128, green: 128, blue: 128))
        )
        XCTAssertEqual(parsed[1].map(\.text).joined(), "$ tool")
        XCTAssertTrue(parsed[1][0].style.bold)
        XCTAssertEqual(
            parsed[1][0].style.background,
            .rgb(WatchTerminalRGBColor(red: 40, green: 50, blue: 40))
        )
        XCTAssertEqual(
            parsed[2][0].style.background,
            .rgb(WatchTerminalRGBColor(red: 40, green: 50, blue: 40))
        )
        XCTAssertTrue(parsed[3][0].style.inverse)
    }

    func testWrappedOutputPreservesANSIStyles() {
        let parsed = WatchTerminalANSIParser.parse(lines: [
            "\u{1b}[38;2;128;200;255malpha beta gamma\u{1b}[0m      ",
            "────────────────────────────────────────────────",
        ])
        let wrapped = WatchTerminalANSIParser.wrapped(lines: parsed, displayColumns: 10)

        XCTAssertEqual(wrapped[0].map(\.text).joined(), "alpha")
        XCTAssertEqual(wrapped[1].map(\.text).joined(), "beta gamma")
        XCTAssertEqual(
            wrapped[0][0].style.foreground,
            .rgb(WatchTerminalRGBColor(red: 128, green: 200, blue: 255))
        )
        XCTAssertEqual(wrapped[2].map(\.text).joined().count, 10)
        let editor = WatchTerminalANSIParser.viewport(
            line: parsed[0],
            start: 6,
            columns: 4
        )
        XCTAssertEqual(editor.map(\.text).joined(), "beta")
        XCTAssertEqual(editor[0].style.foreground, parsed[0][0].style.foreground)
    }

    func testFrameFindsUnwrappedPiEditorAndMapsAbsoluteHistory() {
        let divider = String(repeating: "─", count: 48)
        let lines = [
            "history-0", "history-1", "response", divider,
            "prompt", divider, "~/JARVIS", "tokens", "",
        ]
        let frame = WatchTerminalFrame(
            sequence: 4,
            paneID: "%7",
            columns: 48,
            rows: 7,
            cursorColumn: 2,
            cursorRow: 2,
            alternateScreen: false,
            mouseMode: false,
            historySize: 2,
            screenStart: 2,
            lines: lines,
            ansiLines: lines
        )

        XCTAssertEqual(frame.liveEditorRange, 3..<8)
        XCTAssertEqual(frame.liveOutputEndIndex, 3)
        XCTAssertEqual(frame.capturedAbsoluteStart, 0)
        XCTAssertEqual(frame.absoluteOutputEnd, 3)
        XCTAssertEqual(frame.maximumOutputScrollOffset(maximumSourceRows: 2), 1)
        XCTAssertEqual(frame.localANSILines(inAbsoluteRange: 0..<2), ["history-0", "history-1"])
    }

    func testHistoryPageIsBoundedAndSlicesAbsoluteRows() throws {
        let page = WatchTerminalHistoryPage(
            paneID: "%7",
            historySize: 100_000,
            start: 9_700,
            lines: (0..<256).map { "line-\($0)" }
        )
        XCTAssertEqual(page.end, 9_956)
        XCTAssertTrue(page.contains(9_800..<9_810))
        XCTAssertEqual(page.ansiLines(in: 9_800..<9_802), ["line-100", "line-101"])
        XCTAssertFalse(page.contains(9_600..<9_601))

        let oversized = Data(
            "{\"paneID\":\"%7\",\"historySize\":100000,\"start\":0,\"lines\":["
                .utf8
        ) + Data((0...WatchTerminalHistoryPage.maximumRows).map { _ in "\"x\"" }.joined(separator: ",").utf8)
            + Data("]}".utf8)
        XCTAssertThrowsError(try JSONDecoder().decode(WatchTerminalHistoryPage.self, from: oversized))
    }

    func testCrownHistoryClampsTheLiveEdgeInsteadOfReboundingToOne() {
        XCTAssertEqual(
            WatchTerminalCrownHistory.scrollOffset(crownPosition: 0, maximumOffset: 20),
            0
        )
        XCTAssertEqual(
            WatchTerminalCrownHistory.scrollOffset(crownPosition: 0.8, maximumOffset: 20),
            0
        )
        XCTAssertEqual(
            WatchTerminalCrownHistory.scrollOffset(crownPosition: -1, maximumOffset: 20),
            1
        )
        XCTAssertEqual(
            WatchTerminalCrownHistory.scrollOffset(crownPosition: -8, maximumOffset: 3),
            3
        )
        XCTAssertEqual(WatchTerminalCrownHistory.crownPosition(scrollOffset: 0), 0)
        XCTAssertEqual(WatchTerminalCrownHistory.crownPosition(scrollOffset: 3), -3)
    }

    func testFrameCrownViewportMovesThroughCapturedHistoryWithoutInput() {
        let lines = ["history-0", "history-1", "screen-0", "screen-1", "prompt", "footer"]
        let frame = WatchTerminalFrame(
            sequence: 9,
            columns: 48,
            rows: 4,
            cursorColumn: 3,
            cursorRow: 2,
            alternateScreen: false,
            mouseMode: false,
            historySize: 2,
            screenStart: 2,
            lines: lines,
            ansiLines: lines
        )

        XCTAssertEqual(frame.liveCursorLineIndex, 4)
        XCTAssertEqual(frame.visibleLines(maximumLines: 3), ["screen-1", "prompt", "footer"])
        XCTAssertEqual(
            frame.visibleLines(maximumLines: 3, scrollOffset: 2),
            ["history-1", "screen-0", "screen-1"]
        )
        XCTAssertEqual(frame.maximumScrollOffset(maximumLines: 3), 3)
        XCTAssertEqual(frame.promptViewport(displayColumns: 10), "pro▌mpt")
    }

    func testLegacyFrameWithoutANSIFieldsStillDecodes() throws {
        let data = Data(#"{"sequence":1,"columns":2,"rows":2,"cursorColumn":0,"cursorRow":1,"alternateScreen":false,"mouseMode":false,"historySize":0,"lines":["a","b"]}"#.utf8)
        let frame = try JSONDecoder().decode(WatchTerminalFrame.self, from: data)
        XCTAssertEqual(frame.screenStart, 0)
        XCTAssertEqual(frame.ansiLines, frame.lines)
    }

    func testSpeechMetadataDecodesAdditivelyWithoutExposingResponseText() throws {
        let data = Data(#"{"sequence":3,"columns":2,"rows":2,"cursorColumn":0,"cursorRow":1,"alternateScreen":false,"mouseMode":false,"historySize":0,"speech":{"available":true,"generating":false,"responseID":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"lines":["a","b"]}"#.utf8)
        let frame = try JSONDecoder().decode(WatchTerminalFrame.self, from: data)
        XCTAssertEqual(
            frame.speech,
            WatchTerminalSpeechState(
                available: true,
                generating: false,
                responseID: String(repeating: "a", count: 64)
            )
        )
        XCTAssertFalse(String(data: try JSONEncoder().encode(frame), encoding: .utf8)!.contains("responseText"))
    }

    func testBuild39DecodesAdditiveHistoryWhileLiveLinesRemainCompatible() throws {
        let data = Data(#"{"sequence":2,"columns":2,"rows":2,"cursorColumn":0,"cursorRow":1,"alternateScreen":false,"mouseMode":false,"historySize":2,"screenStart":2,"lines":["live-a","live-b"],"ansiLines":["live-a","live-b"],"capturedLines":["old-a","old-b","live-a","live-b"],"capturedANSILines":["old-a","old-b","live-a","\u001b[1mlive-b\u001b[0m"]}"#.utf8)
        let frame = try JSONDecoder().decode(WatchTerminalFrame.self, from: data)
        XCTAssertEqual(frame.lines, ["old-a", "old-b", "live-a", "live-b"])
        XCTAssertEqual(frame.screenStart, 2)
        XCTAssertEqual(frame.liveCursorLineIndex, 3)
        XCTAssertTrue(frame.ansiLines[3].contains("\u{1b}[1m"))
    }

    func testSpokenPromptNormalizesOneLineAndRejectsControlsAndOversize() throws {
        XCTAssertEqual(
            try JARVISSpokenPrompt.normalize("  hello\r\nworld\n\n🙂  "),
            "hello world 🙂"
        )
        XCTAssertEqual(try JARVISSpokenPrompt.normalize("don’t change punctuation!"), "don’t change punctuation!")
        XCTAssertThrowsError(try JARVISSpokenPrompt.normalize(" \r\n ")) { error in
            XCTAssertEqual(error as? JARVISSpokenPromptError, .empty)
        }
        XCTAssertThrowsError(try JARVISSpokenPrompt.normalize("unsafe\tcommand")) { error in
            XCTAssertEqual(error as? JARVISSpokenPromptError, .containsControlCharacters)
        }
        XCTAssertThrowsError(try JARVISSpokenPrompt.normalize(String(repeating: "x", count: 3_501))) { error in
            XCTAssertEqual(error as? JARVISSpokenPromptError, .tooLong)
        }
    }

    func testSpeechRetryPolicyIsBoundedAndNeverRetriesTrustOrAudioFailures() {
        XCTAssertTrue(WatchTerminalSpeechRetryPolicy.shouldRetry(.offline))
        XCTAssertTrue(WatchTerminalSpeechRetryPolicy.shouldRetry(.notConnected))
        XCTAssertFalse(WatchTerminalSpeechRetryPolicy.shouldRetry(.certificateRejected))
        XCTAssertFalse(WatchTerminalSpeechRetryPolicy.shouldRetry(.invalidAudio))
        XCTAssertFalse(WatchTerminalSpeechRetryPolicy.shouldRetry(.rejected("no")))
        XCTAssertEqual(WatchTerminalSpeechRetryPolicy.maximumAttempts, 6)
        XCTAssertEqual(WatchTerminalSpeechRetryPolicy.delaySeconds(afterFailure: 1), 1)
        XCTAssertEqual(WatchTerminalSpeechRetryPolicy.delaySeconds(afterFailure: 4), 8)
        XCTAssertEqual(WatchTerminalSpeechRetryPolicy.delaySeconds(afterFailure: 20), 12)
    }

    func testSharedClientSeedsOnlyAnAllowlistedPreferredRoute() {
        let configuration = WatchTerminalConfiguration(
            endpoint: "https://192.168.21.215:8792",
            token: String(repeating: "a", count: 64),
            certificateSHA256: String(repeating: "ab", count: 32)
        )
        let preferred = URL(string: "https://100.87.28.34:8792")!
        let preferredClient = WatchTerminalClient(
            configuration: configuration,
            preferredBaseURL: preferred
        )
        XCTAssertEqual(preferredClient.selectedBaseURL, preferred)
        preferredClient.close()

        let rejected = URL(string: "https://untrusted.invalid:8792")!
        let rejectedClient = WatchTerminalClient(
            configuration: configuration,
            preferredBaseURL: rejected
        )
        XCTAssertNil(rejectedClient.selectedBaseURL)
        rejectedClient.close()
    }

    func testSharedClientPreflightsThenSubmitsExactlyOnceWithReturn() async throws {
        let postInputs = LockedBox<[WatchTerminalInput]>([])
        let frame = fixtureFrame()
        TerminalURLProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, try JSONEncoder().encode(frame))
            }
            let input = try JSONDecoder().decode(WatchTerminalInput.self, from: request.bodyData)
            postInputs.update { $0.append(input) }
            return (200, Data(#"{"ok":true}"#.utf8))
        }
        let client = fixtureClient()
        defer { client.close() }

        _ = try await client.preflight()
        try await client.send(WatchTerminalInput(data: Data("hello Pi".utf8), appendReturn: true))

        let captured = postInputs.snapshot()
        XCTAssertEqual(captured.count, 1)
        XCTAssertEqual(captured[0].data, Data("hello Pi".utf8))
        XCTAssertTrue(captured[0].appendReturn)
    }

    func testSharedClientFetchesOneBoundedReadOnlyHistoryPage() async throws {
        let requestedURL = LockedBox<URL?>(nil)
        let page = WatchTerminalHistoryPage(
            paneID: "%7",
            historySize: 100_000,
            start: 9_700,
            lines: ["old-a", "old-b"],
            ansiLines: ["\u{1b}[1mold-a\u{1b}[0m", "old-b"]
        )
        TerminalURLProtocol.handler = { request in
            requestedURL.update { $0 = request.url }
            XCTAssertEqual(request.httpMethod, "GET")
            return (200, try JSONEncoder().encode(page))
        }
        let client = fixtureClient()
        defer { client.close() }

        let loaded = try await client.historyPage(start: 9_700, limit: 200)

        XCTAssertEqual(loaded, page)
        let components = URLComponents(url: try XCTUnwrap(requestedURL.snapshot()), resolvingAgainstBaseURL: false)
        XCTAssertEqual(components?.path, "/v1/terminal/history")
        XCTAssertEqual(components?.queryItems?.first(where: { $0.name == "start" })?.value, "9700")
        XCTAssertEqual(components?.queryItems?.first(where: { $0.name == "limit" })?.value, "200")
    }

    func testSharedClientDownloadsCurrentSpeechOnceWithoutSendingText() async throws {
        let responseID = String(repeating: "c", count: 64)
        let speechPosts = LockedBox(0)
        TerminalURLProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, try JSONEncoder().encode(self.fixtureFrame()))
            }
            XCTAssertEqual(request.url?.path, "/v1/terminal/speech")
            let payload = try JSONSerialization.jsonObject(with: request.bodyData) as? [String: String]
            XCTAssertEqual(payload, ["responseID": responseID])
            speechPosts.update { $0 += 1 }
            var wav = Data("RIFF".utf8)
            wav.append(contentsOf: [36, 0, 0, 0])
            wav.append(Data("WAVEfmt ".utf8))
            wav.append(Data(repeating: 0, count: 28))
            return (200, wav)
        }
        let client = fixtureClient()
        defer { client.close() }
        _ = try await client.preflight()

        let url = try await client.speechAudio(responseID: responseID)
        defer { try? FileManager.default.removeItem(at: url) }

        XCTAssertEqual(speechPosts.snapshot(), 1)
        XCTAssertEqual(try Data(contentsOf: url).prefix(4), Data("RIFF".utf8))
    }

    func testSharedClientNeverRetriesAmbiguousPost() async throws {
        let postCount = LockedBox(0)
        let frame = fixtureFrame()
        TerminalURLProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, try JSONEncoder().encode(frame))
            }
            postCount.update { $0 += 1 }
            throw URLError(.timedOut)
        }
        let client = fixtureClient()
        defer { client.close() }
        _ = try await client.preflight()

        do {
            try await client.send(WatchTerminalInput(data: Data("once".utf8), appendReturn: true))
            XCTFail("Expected an unconfirmed submission")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .submissionUnconfirmed)
        }
        XCTAssertEqual(postCount.snapshot(), 1)
    }

    private func fixtureClient() -> WatchTerminalClient {
        let configuration = WatchTerminalConfiguration(
            endpoint: "https://fixture.invalid:8792",
            token: String(repeating: "a", count: 64),
            certificateSHA256: String(repeating: "ab", count: 32)
        )
        let sessionConfiguration = URLSessionConfiguration.ephemeral
        sessionConfiguration.protocolClasses = [TerminalURLProtocol.self]
        return WatchTerminalClient(
            configuration: configuration,
            injectedSession: URLSession(configuration: sessionConfiguration)
        )
    }

    private func fixtureFrame() -> WatchTerminalFrame {
        WatchTerminalFrame(
            sequence: 1,
            columns: 2,
            rows: 2,
            cursorColumn: 0,
            cursorRow: 1,
            alternateScreen: false,
            mouseMode: false,
            historySize: 0,
            lines: ["a", "b"]
        )
    }
}

private final class TerminalURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            guard let handler = Self.handler else { throw URLError(.resourceUnavailable) }
            let (status, data) = try handler(request)
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: [
                    "Content-Type": request.url?.path.hasSuffix("/speech") == true
                        ? "audio/wav"
                        : "application/json"
                ]
            )!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private final class LockedBox<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) {
        self.value = value
    }

    func update(_ operation: (inout Value) -> Void) {
        lock.lock()
        defer { lock.unlock() }
        operation(&value)
    }

    func snapshot() -> Value {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

private extension URLRequest {
    var bodyData: Data {
        if let httpBody { return httpBody }
        guard let stream = httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var result = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4_096)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let count = stream.read(buffer, maxLength: 4_096)
            guard count > 0 else { break }
            result.append(buffer, count: count)
        }
        return result
    }
}
