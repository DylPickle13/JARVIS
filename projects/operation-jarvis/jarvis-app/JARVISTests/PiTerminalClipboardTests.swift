import XCTest
import UIKit
import SwiftTerm
@testable import JARVIS

@MainActor
final class PiTerminalClipboardTests: XCTestCase {
    func testPasteStyleMatchesAccentControlsWithoutReplacingNativePaste() {
        let configuration = PiTerminalPasteControl.buttonConfiguration()
        XCTAssertEqual(configuration.displayMode, .iconOnly)
        XCTAssertEqual(configuration.baseBackgroundColor, .clear)
        XCTAssertEqual(configuration.baseForegroundColor, UIColor(JarvisPalette.accent))
        let native = UIPasteControl(configuration: configuration)
        XCTAssertEqual(native.configuration.baseForegroundColor, UIColor(JarvisPalette.accent))
    }

    private func terminal() -> PiTerminalHostView {
        let view = PiTerminalHostView(frame: CGRect(x: 0, y: 0, width: 390, height: 300))
        view.layoutIfNeeded()
        view.beginTerminalInputTransition(generation: 0, restoreKeyboard: false)
        XCTAssertTrue(view.completeTerminalInputTransition(generation: 0))
        return view
    }

    func testPastePolicyRejectsControlsAndBoundsUTF8() throws {
        XCTAssertThrowsError(try PiTerminalPastePolicy.normalized(""))
        XCTAssertThrowsError(try PiTerminalPastePolicy.normalized(String(repeating: "😀", count: 16385)))
        XCTAssertEqual(try PiTerminalPastePolicy.normalized(String(repeating: "a", count: 65536)).count, 65536)
        for text in ["\u{1b}[201~danger", "a\u{0}b", "a\u{7f}", "\u{85}", "\u{3}"] {
            XCTAssertThrowsError(try PiTerminalPastePolicy.bytes(text, bracketed: true))
        }
        XCTAssertEqual(try PiTerminalPastePolicy.normalized("one\r\ntwo\rthree"), "one\ntwo\nthree")
    }

    func testPastePolicyDoesNotAppendEnterOrInterpretUnicode() throws {
        let text = "héllo 👩🏽‍💻"
        XCTAssertEqual(try PiTerminalPastePolicy.bytes(text, bracketed: false), Array(text.utf8))
        XCTAssertEqual(try PiTerminalPastePolicy.bytes(text, bracketed: true), Array(("\u{1b}[200~" + text + "\u{1b}[201~").utf8))
        XCTAssertThrowsError(try PiTerminalPastePolicy.bytes("one\ntwo", bracketed: false))
        XCTAssertThrowsError(try PiTerminalPastePolicy.bytes("one\ttwo", bracketed: false))
        XCTAssertEqual(try PiTerminalPastePolicy.bytes("one\ntwo\tthree", bracketed: false, singleLine: true), Array("one two three".utf8))
    }

    func testInlineSelectionKeepsPresentationInPlaceAndParsingLive() {
        let view = terminal()
        defer { view.dismissInlineSelection(); view.updateUiClosed() }
        var sent: [[UInt8]] = []
        var copied: [String] = []
        view.outboundBytesObserver = { sent.append($0) }
        view.clipboardWriter = { copied.append($0) }
        view.receiveTerminalOutput(Array("\u{1b}[?1049h\u{1b}[2J\u{1b}[Hhello world".utf8))
        let frame = view.frame
        view.selectInlineWord(at: CGPoint(x: 2, y: 2))
        XCTAssertEqual(view.selectedInlineText, "hello")
        XCTAssertFalse(view.isTerminalKeyboardFocused)
        view.receiveTerminalOutput(Array("\u{1b}[Hnewer words".utf8))
        XCTAssertEqual(view.getTerminal().getCharacter(col: 0, row: 0), Character("n"))
        XCTAssertEqual(view.selectedInlineText, "hello", "Incoming output must not change the highlighted/copyable text")
        XCTAssertEqual(view.frame, frame)
        view.copyInlineSelection()
        XCTAssertEqual(copied, ["hello"])
        XCTAssertNil(view.selectedInlineText)
        XCTAssertTrue(sent.isEmpty, "Selection/copy/dismissal cannot send bytes")
        XCTAssertFalse(view.isTerminalKeyboardFocused)
        XCTAssertNil(view.clipboardRead(source: view), "Remote clipboard reads stay disabled")
    }

    func testSelectionClearsOnConnectionTransitionAndResize() {
        let view = terminal()
        defer { view.dismissInlineSelection(); view.updateUiClosed() }
        view.receiveTerminalOutput(Array("hello".utf8))
        view.selectInlineWord(at: CGPoint(x: 2, y: 2))
        XCTAssertNotNil(view.selectedInlineText)
        view.beginTerminalInputTransition(generation: 0, restoreKeyboard: false)
        XCTAssertNil(view.selectedInlineText)
        view.selectInlineWord(at: CGPoint(x: 2, y: 2))
        view.frame.size.width = 320
        view.layoutIfNeeded()
        XCTAssertNil(view.selectedInlineText)
    }

    func testNativeProviderPasteIsBracketedAndOneShot() async {
        let view = terminal()
        defer { view.cancelPaste(); view.updateUiClosed() }
        view.receiveTerminalOutput(Array("\u{1b}[?2004h".utf8))
        var sent: [[UInt8]] = []
        view.outboundBytesObserver = { sent.append($0) }
        let reviewed = expectation(description: "Review")
        var request: PiTerminalPasteReview?
        view.pasteReviewChanged = { if let value = $0 { request = value; reviewed.fulfill() } }
        view.receivePasteProviders([NSItemProvider(object: "one\ntwo" as NSString)])
        await fulfillment(of: [reviewed], timeout: 3)
        guard let request else { return XCTFail("Missing review") }
        XCTAssertTrue(sent.isEmpty)
        view.confirmPaste(id: request.id, singleLine: false)
        view.confirmPaste(id: request.id, singleLine: false)
        XCTAssertEqual(sent, [Array("\u{1b}[200~one\ntwo\u{1b}[201~".utf8)])
    }

    func testPasteReviewCannotCrossTransition() async {
        let view = terminal()
        defer { view.cancelPaste(); view.updateUiClosed() }
        var sent: [[UInt8]] = []
        view.outboundBytesObserver = { sent.append($0) }
        let reviewed = expectation(description: "Review")
        var request: PiTerminalPasteReview?
        view.pasteReviewChanged = { if let value = $0 { request = value; reviewed.fulfill() } }
        view.receivePasteProviders([NSItemProvider(object: "one\ntwo" as NSString)])
        await fulfillment(of: [reviewed], timeout: 3)
        guard let request else { return XCTFail("Missing review") }
        view.beginTerminalInputTransition(generation: 0, restoreKeyboard: false)
        XCTAssertTrue(view.completeTerminalInputTransition(generation: 0))
        view.confirmPaste(id: request.id, singleLine: true)
        XCTAssertTrue(sent.isEmpty)
    }
    func testInlineHandlesCopyWideCharactersAndBlockRemoteScroll() {
        let view = terminal()
        defer { view.dismissInlineSelection(); view.updateUiClosed() }
        var sent: [[UInt8]] = []
        view.outboundBytesObserver = { sent.append($0) }
        view.receiveTerminalOutput(Array("\u{1b}[?1049h\u{1b}[?1002hhello 👩🏽‍💻 world".utf8))
        let cell = view.caretFrame.size
        XCTAssertGreaterThan(cell.width, 1)
        view.selectInlineWord(at: CGPoint(x: 2, y: 2))
        // Begin at the right handle, then extend over the full visible sentence.
        view.extendInlineSelection(to: CGPoint(x: 5 * cell.width, y: 2), startsDrag: true)
        view.extendInlineSelection(to: CGPoint(x: 14 * cell.width, y: 2), startsDrag: false)
        XCTAssertEqual(view.selectedInlineText, "hello 👩🏽‍💻 world")
        view.sendTouchScrollStep(scrollingUp: true, column: 1, row: 1)
        XCTAssertTrue(sent.isEmpty)
        view.dismissInlineSelection()
        view.sendTouchScrollStep(scrollingUp: true, column: 1, row: 1)
        XCTAssertEqual(sent.count, 1, "Normal remote scrolling resumes immediately")
    }

    func testPendingProviderCannotPasteAfterCancellation() async {
        let view = terminal()
        defer { view.cancelPaste(); view.updateUiClosed() }
        var sent: [[UInt8]] = []
        view.outboundBytesObserver = { sent.append($0) }
        view.receivePasteProviders([NSItemProvider(object: "must not arrive" as NSString)])
        view.cancelPaste()
        // Give the provider callback time to execute after cancellation.
        try? await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertTrue(sent.isEmpty)
    }

    func testKeyboardProxyUsesSafePasteAndCopiesSelectionNotSentinel() throws {
        let view = terminal()
        defer { view.dismissInlineSelection(); view.updateUiClosed() }
        let proxy = try XCTUnwrap(view.subviews.compactMap { $0 as? PiTerminalKeyboardResponder }.first)
        var sent: [[UInt8]] = []
        var copied: [String] = []
        view.outboundBytesObserver = { sent.append($0) }
        view.clipboardTextReader = { "pasted" }
        view.clipboardWriter = { copied.append($0) }
        proxy.paste(nil)
        XCTAssertEqual(sent, [Array("pasted".utf8)])
        view.receiveTerminalOutput(Array("hello".utf8))
        view.selectInlineWord(at: CGPoint(x: 2, y: 2))
        XCTAssertTrue(proxy.canPerformAction(#selector(UIResponderStandardEditActions.copy(_:)), withSender: nil))
        proxy.copy(nil)
        XCTAssertEqual(copied, ["hello"])
        XCTAssertEqual(sent.count, 1)
        XCTAssertFalse(proxy.canPerformAction(#selector(UIResponderStandardEditActions.copy(_:)), withSender: nil))
    }

    func testHeldInlinePresentationMatchesOriginalPixels() async throws {
        let view = terminal()
        defer { view.dismissInlineSelection(); view.updateUiClosed() }
        view.receiveTerminalOutput(Array("\u{1b}[?1049h\u{1b}[2J\u{1b}[Hhello 👩🏽‍💻\r\n\u{1b}[31mred\u{1b}[0m plain \u{1b}[1mbold\u{1b}[0m".utf8))
        func image() -> UIImage {
            view.layoutIfNeeded()
            view.layer.displayIfNeeded()
            for child in view.subviews { child.layer.displayIfNeeded() }
            return UIGraphicsImageRenderer(size: view.bounds.size).image { view.layer.render(in: $0.cgContext) }
        }
        try await Task.sleep(nanoseconds: 80_000_000)
        let before = image()
        view.selectInlineWord(at: CGPoint(x: 2, y: 2))
        let held = try XCTUnwrap(view.subviews.compactMap { $0 as? TerminalView }.first)
        // Remove only highlighting for the pixel comparison; actual selection
        // behavior is exercised separately. No sheet or layout replacement.
        held.clearSelection()
        try await Task.sleep(nanoseconds: 80_000_000)
        let after = image()
        let a = try XCTUnwrap(before.cgImage?.dataProvider?.data) as Data
        let b = try XCTUnwrap(after.cgImage?.dataProvider?.data) as Data
        XCTAssertEqual(a.count, b.count)
        guard a.count == b.count else { return }
        let meanDelta = zip(a, b).reduce(0.0) { $0 + abs(Double($1.0) - Double($1.1)) } / Double(a.count)
        XCTAssertLessThan(meanDelta, 0.1, "Holding selection must not visibly change the terminal")
        for (name, image) in [("terminal-before-selection", before), ("terminal-held-presentation", after)] {
            let attachment = XCTAttachment(image: image)
            attachment.name = name
            attachment.lifetime = .keepAlways
            add(attachment)
        }
    }

}
