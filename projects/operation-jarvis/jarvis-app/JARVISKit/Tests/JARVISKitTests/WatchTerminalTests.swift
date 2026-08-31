import Foundation
import XCTest
@testable import JARVISKit

final class WatchTerminalTests: XCTestCase {
    override func tearDown() {
        TerminalURLProtocol.handler = nil
        TerminalURLProtocol.terminalSessionHeader = "1"
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
        let invalidSession = Data(#"{"sessionID":0,"paneID":"%7","historySize":1,"start":0,"lines":["x"]}"#.utf8)
        XCTAssertThrowsError(try JSONDecoder().decode(WatchTerminalHistoryPage.self, from: invalidSession))
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
        XCTAssertEqual(frame.sessionID, 1)
        XCTAssertEqual(frame.screenStart, 0)
        XCTAssertEqual(frame.ansiLines, frame.lines)

        let invalid = Data(#"{"sessionID":4,"sequence":1,"columns":2,"rows":2,"cursorColumn":0,"cursorRow":1,"alternateScreen":false,"mouseMode":false,"historySize":0,"lines":["a","b"]}"#.utf8)
        XCTAssertThrowsError(try JSONDecoder().decode(WatchTerminalFrame.self, from: invalid))
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

    func testSpeechFileStoreRemovesOnlyStrictRegularOrphanDownloads() throws {
        try withSpeechFileStore { store, _, _, temporaryDirectory, _ in
            let orphan = temporaryDirectory
                .appendingPathComponent("jarvis-watch-speech-\(UUID().uuidString).wav")
            let unrelated = temporaryDirectory.appendingPathComponent("jarvis-watch-speech-not-a-uuid.wav")
            let target = temporaryDirectory.appendingPathComponent("target.wav")
            let symlink = temporaryDirectory
                .appendingPathComponent("jarvis-watch-speech-\(UUID().uuidString).wav")
            let nestedDirectory = temporaryDirectory.appendingPathComponent("nested", isDirectory: true)
            let nested = nestedDirectory
                .appendingPathComponent("jarvis-watch-speech-\(UUID().uuidString).wav")
            try fixtureWAV().write(to: orphan)
            try fixtureWAV().write(to: unrelated)
            try fixtureWAV().write(to: target)
            try FileManager.default.createSymbolicLink(at: symlink, withDestinationURL: target)
            try FileManager.default.createDirectory(at: nestedDirectory, withIntermediateDirectories: true)
            try fixtureWAV().write(to: nested)

            XCTAssertEqual(store.removeOrphanedDownloads(), 1)
            XCTAssertFalse(FileManager.default.fileExists(atPath: orphan.path))
            XCTAssertTrue(FileManager.default.fileExists(atPath: unrelated.path))
            XCTAssertTrue(FileManager.default.fileExists(atPath: symlink.path))
            XCTAssertTrue(FileManager.default.fileExists(atPath: nested.path))
        }
    }

    func testSpeechFileStoreClearsInvalidCacheFileAndMetadataTogether() throws {
        try withSpeechFileStore { store, defaults, cacheDirectory, _, responseIDKey in
            let responseID = String(repeating: "a", count: 64)
            let prepared = try XCTUnwrap(store.preparedFileURL)
            try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
            defaults.set(responseID, forKey: responseIDKey)
            try Data("not-wave-audio".utf8).write(to: prepared)

            XCTAssertNil(store.restorePreparedSpeech())
            XCTAssertNil(defaults.string(forKey: responseIDKey))
            XCTAssertFalse(FileManager.default.fileExists(atPath: prepared.path))

            try fixtureWAV().write(to: prepared)
            XCTAssertNil(store.restorePreparedSpeech())
            XCTAssertFalse(FileManager.default.fileExists(atPath: prepared.path))
        }
    }

    func testSpeechFileStoreRetainsExactlyOneValidatedPreparedResponse() throws {
        try withSpeechFileStore { store, defaults, _, temporaryDirectory, responseIDKey in
            let responseID = String(repeating: "b", count: 64)
            let source = temporaryDirectory
                .appendingPathComponent("jarvis-watch-speech-\(UUID().uuidString).wav")
            try fixtureWAV().write(to: source)

            let retainedURL = try store.retainPreparedSpeech(from: source, responseID: responseID)
            XCTAssertFalse(FileManager.default.fileExists(atPath: source.path))
            XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))
            XCTAssertEqual(defaults.string(forKey: responseIDKey), responseID)
            XCTAssertEqual(
                store.restorePreparedSpeech(),
                PreparedWatchTerminalSpeech(responseID: responseID, fileURL: retainedURL)
            )

            store.discardPreparedSpeech()
            XCTAssertFalse(FileManager.default.fileExists(atPath: retainedURL.path))
            XCTAssertNil(defaults.string(forKey: responseIDKey))
        }
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
            return (200, Data("{\"ok\":true,\"requestID\":\"\(input.requestID)\",\"sessionID\":\(input.sessionID)}".utf8))
        }
        let client = fixtureClient()
        defer { client.close() }

        _ = try await client.preflight()
        try await client.send(WatchTerminalInput(data: Data("hello Pi".utf8), appendReturn: true))

        let captured = postInputs.snapshot()
        XCTAssertEqual(captured.count, 1)
        XCTAssertEqual(captured[0].sessionID, 1)
        XCTAssertEqual(captured[0].data, Data("hello Pi".utf8))
        XCTAssertTrue(captured[0].appendReturn)
    }

    func testSharedClientRejectsInvalidInputAcknowledgementsWithoutRetry() async throws {
        let postCount = LockedBox(0)
        TerminalURLProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, try JSONEncoder().encode(self.fixtureFrame(session: .two)))
            }
            postCount.update { $0 += 1 }
            let input = try JSONDecoder().decode(WatchTerminalInput.self, from: request.bodyData)
            XCTAssertEqual(input.sessionID, 2)
            return (200, Data("{\"ok\":true,\"requestID\":\"\(input.requestID)\",\"sessionID\":1}".utf8))
        }
        let client = fixtureClient()
        defer { client.close() }
        _ = try await client.preflight(slot: .two)

        do {
            try await client.send(WatchTerminalInput(session: .two, data: Data("once".utf8), appendReturn: true))
            XCTFail("Expected a mismatched acknowledgement")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }
        XCTAssertEqual(postCount.snapshot(), 1)

        TerminalURLProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, try JSONEncoder().encode(self.fixtureFrame(session: .two)))
            }
            postCount.update { $0 += 1 }
            let input = try JSONDecoder().decode(WatchTerminalInput.self, from: request.bodyData)
            return (200, Data("{\"ok\":false,\"requestID\":\"\(input.requestID)\",\"sessionID\":2}".utf8))
        }
        let rejected = fixtureClient()
        defer { rejected.close() }
        _ = try await rejected.preflight(slot: .two)
        do {
            try await rejected.send(WatchTerminalInput(session: .two, data: Data("once".utf8), appendReturn: true))
            XCTFail("Expected a negative acknowledgement to fail closed")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }
        XCTAssertEqual(postCount.snapshot(), 2)

        TerminalURLProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, try JSONEncoder().encode(self.fixtureFrame(session: .two)))
            }
            postCount.update { $0 += 1 }
            let input = try JSONDecoder().decode(WatchTerminalInput.self, from: request.bodyData)
            return (200, Data("{\"ok\":true,\"requestID\":\"\(input.requestID)\",\"sessionID\":2.0}".utf8))
        }
        let nonCanonical = fixtureClient()
        defer { nonCanonical.close() }
        _ = try await nonCanonical.preflight(slot: .two)
        do {
            try await nonCanonical.send(WatchTerminalInput(session: .two, data: Data("once".utf8), appendReturn: true))
            XCTFail("Expected a non-canonical floating-point identity to fail closed")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }
        XCTAssertEqual(postCount.snapshot(), 3)
    }

    func testSharedClientRoutesASelectedSlotAndRejectsMismatchedFrameIdentity() async throws {
        let requestedURLs = LockedBox<[URL]>([])
        TerminalURLProtocol.handler = { request in
            requestedURLs.update { if let url = request.url { $0.append(url) } }
            return (200, try JSONEncoder().encode(self.fixtureFrame(session: .three)))
        }
        let client = fixtureClient()
        defer { client.close() }

        let frame = try await client.preflight(slot: .three)
        XCTAssertEqual(frame.sessionID, 3)
        let firstURL = try XCTUnwrap(requestedURLs.snapshot().first)
        let firstComponents = URLComponents(url: firstURL, resolvingAgainstBaseURL: false)
        XCTAssertEqual(firstComponents?.path, "/v2/terminal/frame")
        XCTAssertEqual(firstComponents?.queryItems?.first(where: { $0.name == "sessionID" })?.value, "3")

        let mismatchedRequests = LockedBox(0)
        TerminalURLProtocol.handler = { _ in
            mismatchedRequests.update { $0 += 1 }
            return (200, try JSONEncoder().encode(self.fixtureFrame(session: .one)))
        }
        let mismatched = fixtureClient()
        defer { mismatched.close() }
        do {
            _ = try await mismatched.preflight(slot: .two)
            XCTFail("Expected the frame identity mismatch to fail closed")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }
        XCTAssertGreaterThanOrEqual(mismatchedRequests.snapshot(), 1)

        let encodedSelectedFrame = try JSONEncoder().encode(fixtureFrame(session: .three))
        let encodedSelectedFrameText = try XCTUnwrap(String(data: encodedSelectedFrame, encoding: .utf8))
        let floatingIdentityText = encodedSelectedFrameText.replacingOccurrences(
            of: "\"sessionID\":3",
            with: "\"sessionID\":3.0"
        )
        XCTAssertNotEqual(floatingIdentityText, encodedSelectedFrameText)
        TerminalURLProtocol.handler = { _ in (200, Data(floatingIdentityText.utf8)) }
        let nonCanonical = fixtureClient()
        defer { nonCanonical.close() }
        do {
            _ = try await nonCanonical.preflight(slot: .three)
            XCTFail("Expected a non-canonical floating-point frame identity to fail closed")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }

        let encodedLegacyFrame = try JSONEncoder().encode(fixtureFrame(session: .one))
        var legacyFrameObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encodedLegacyFrame) as? [String: Any]
        )
        legacyFrameObject.removeValue(forKey: "sessionID")
        let legacyFrameData = try JSONSerialization.data(withJSONObject: legacyFrameObject)
        TerminalURLProtocol.handler = { _ in (200, legacyFrameData) }
        let missingIdentity = fixtureClient()
        defer { missingIdentity.close() }
        do {
            _ = try await missingIdentity.preflight(slot: .one)
            XCTFail("Expected a v2 frame without an explicit identity to fail closed")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }
    }

    func testSharedClientFetchesOneBoundedReadOnlyHistoryPage() async throws {
        let requestedURL = LockedBox<URL?>(nil)
        let page = WatchTerminalHistoryPage(
            session: .two,
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

        let loaded = try await client.historyPage(start: 9_700, limit: 200, slot: .two)

        XCTAssertEqual(loaded, page)
        let components = URLComponents(url: try XCTUnwrap(requestedURL.snapshot()), resolvingAgainstBaseURL: false)
        XCTAssertEqual(components?.path, "/v2/terminal/history")
        XCTAssertEqual(components?.queryItems?.first(where: { $0.name == "start" })?.value, "9700")
        XCTAssertEqual(components?.queryItems?.first(where: { $0.name == "limit" })?.value, "200")
        XCTAssertEqual(components?.queryItems?.first(where: { $0.name == "sessionID" })?.value, "2")

        TerminalURLProtocol.handler = { _ in
            (200, try JSONEncoder().encode(WatchTerminalHistoryPage(
                session: .one,
                paneID: "%1",
                historySize: 0,
                start: 0,
                lines: []
            )))
        }
        do {
            _ = try await client.historyPage(start: 0, slot: .two)
            XCTFail("Expected history from another session to be rejected")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }

        let encodedLegacyPage = try JSONEncoder().encode(WatchTerminalHistoryPage(
            session: .one,
            paneID: "%1",
            historySize: 0,
            start: 0,
            lines: []
        ))
        var legacyPageObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encodedLegacyPage) as? [String: Any]
        )
        legacyPageObject.removeValue(forKey: "sessionID")
        let legacyPageData = try JSONSerialization.data(withJSONObject: legacyPageObject)
        TerminalURLProtocol.handler = { _ in (200, legacyPageData) }
        do {
            _ = try await client.historyPage(start: 0, slot: .one)
            XCTFail("Expected v2 history without an explicit identity to fail closed")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidResponse)
        }
    }

    func testSharedClientDownloadsCurrentSpeechOnceWithoutSendingText() async throws {
        let responseID = String(repeating: "c", count: 64)
        let speechPosts = LockedBox(0)
        TerminalURLProtocol.terminalSessionHeader = "2"
        TerminalURLProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, try JSONEncoder().encode(self.fixtureFrame(session: .two)))
            }
            XCTAssertEqual(request.url?.path, "/v2/terminal/speech")
            let payload = try JSONSerialization.jsonObject(with: request.bodyData) as? [String: Any]
            XCTAssertEqual(payload?["responseID"] as? String, responseID)
            XCTAssertEqual(payload?["sessionID"] as? Int, 2)
            speechPosts.update { $0 += 1 }
            var wav = Data("RIFF".utf8)
            wav.append(contentsOf: [36, 0, 0, 0])
            wav.append(Data("WAVEfmt ".utf8))
            wav.append(Data(repeating: 0, count: 28))
            return (200, wav)
        }
        let client = fixtureClient()
        defer { client.close() }
        _ = try await client.preflight(slot: .two)

        let url = try await client.speechAudio(responseID: responseID, slot: .two)
        defer { try? FileManager.default.removeItem(at: url) }

        XCTAssertEqual(speechPosts.snapshot(), 1)
        XCTAssertEqual(try Data(contentsOf: url).prefix(4), Data("RIFF".utf8))

        TerminalURLProtocol.terminalSessionHeader = "1"
        do {
            _ = try await client.speechAudio(responseID: responseID, slot: .two)
            XCTFail("Expected speech from another session to be rejected")
        } catch {
            XCTAssertEqual(error as? WatchTerminalClientError, .invalidAudio)
        }
        XCTAssertEqual(speechPosts.snapshot(), 2)
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

    private func withSpeechFileStore(
        _ body: (
            WatchTerminalSpeechFileStore,
            UserDefaults,
            URL,
            URL,
            String
        ) throws -> Void
    ) throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("jarvis-speech-store-tests-\(UUID().uuidString)", isDirectory: true)
        let cacheDirectory = root.appendingPathComponent("cache", isDirectory: true)
        let temporaryDirectory = root.appendingPathComponent("tmp", isDirectory: true)
        let suite = "jarvis.speech-store-tests.\(UUID().uuidString)"
        let responseIDKey = "prepared-response"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
        defer {
            defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: root)
        }
        let store = WatchTerminalSpeechFileStore(
            defaults: defaults,
            cacheDirectory: cacheDirectory,
            temporaryDirectory: temporaryDirectory,
            responseIDKey: responseIDKey
        )
        try body(store, defaults, cacheDirectory, temporaryDirectory, responseIDKey)
    }

    private func fixtureWAV() -> Data {
        var data = Data("RIFF".utf8)
        data.append(contentsOf: [20, 0, 0, 0])
        data.append(Data("WAVE".utf8))
        data.append(Data(repeating: 0, count: 16))
        return data
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

    private func fixtureFrame(session: JARVISTerminalSlot = .one) -> WatchTerminalFrame {
        WatchTerminalFrame(
            session: session,
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
    static var terminalSessionHeader = "1"

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
                        : "application/json",
                    "X-JARVIS-Terminal-Session": Self.terminalSessionHeader,
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
