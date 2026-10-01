import XCTest
@testable import JARVISKit

final class WatchTerminalANSIParseCacheTests: XCTestCase {
    func testStreamingOnlyParsesChangedSuffix() {
        var cache = WatchTerminalANSIParseCache()
        let original = ["\u{1b}[31mred", "still red", "generating"]
        XCTAssertEqual(cache.parse(lines: original), WatchTerminalANSIParser.parse(lines: original))
        XCTAssertEqual(cache.lastParsedRowCount, 3)
        XCTAssertEqual(cache.parse(lines: original), WatchTerminalANSIParser.parse(lines: original))
        XCTAssertEqual(cache.lastParsedRowCount, 0)
        let updated = [original[0], original[1], "generating text", "\u{1b}[0mnormal"]
        XCTAssertEqual(cache.parse(lines: updated), WatchTerminalANSIParser.parse(lines: updated))
        XCTAssertEqual(cache.lastParsedRowCount, 2)
    }

    func testChangedStyleInvalidatesUnchangedFollowingText() {
        var cache = WatchTerminalANSIParseCache()
        _ = cache.parse(lines: ["\u{1b}[31mred", "same text"])
        let changed = ["\u{1b}[32mgreen", "same text"]
        XCTAssertEqual(cache.parse(lines: changed), WatchTerminalANSIParser.parse(lines: changed))
        XCTAssertEqual(cache.lastParsedRowCount, 2)
    }

    func testTruncationEmptyAndReappendRestoreCorrectStyle() {
        var cache = WatchTerminalANSIParseCache()
        let frames = [
            ["\u{1b}[31mred", "\u{1b}[34mblue"],
            ["\u{1b}[31mred"],
            ["\u{1b}[31mred", "inherits red"],
            [],
            ["default again"]
        ]
        for frame in frames {
            XCTAssertEqual(cache.parse(lines: frame), WatchTerminalANSIParser.parse(lines: frame))
        }
    }

    func testScrollingUnicodeAndStyleOnlyRowsMatchFullParser() {
        var cache = WatchTerminalANSIParseCache()
        let lines = ["\u{1b}[1;38;2;20;40;60m", "hello 👩🏽‍💻", "\u{1b}[7minverse", "\u{1b}[0m", "normal"]
        for start in lines.indices {
            let frame = Array(lines.dropFirst(start))
            XCTAssertEqual(cache.parse(lines: frame), WatchTerminalANSIParser.parse(lines: frame))
        }
    }
}
