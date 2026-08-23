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
                headerFields: ["Content-Type": "application/json"]
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
