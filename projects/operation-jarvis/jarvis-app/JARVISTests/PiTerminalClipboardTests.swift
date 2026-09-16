import XCTest
import UIKit
import SwiftUI
import SwiftTerm
import JARVISKit
@testable import JARVIS

@MainActor
final class PiTerminalClipboardTests: XCTestCase {
    func testKeyboardIntersectionDoesNotCollapseOrDoubleInsetTerminal() {
        let bounds = CGRect(x: 0, y: 0, width: 390, height: 800)
        func bottom(_ keyboard: CGRect?, _ height: CGFloat = 800) -> CGFloat {
            PiTerminalViewportController.contentBottom(bounds: CGRect(x: 0, y: 0, width: 390, height: height),
                safeAreaBottom: 34, keyboard: keyboard)
        }
        XCTAssertEqual(bottom(nil), 766)
        XCTAssertEqual(bottom(.zero), 766)
        XCTAssertEqual(bottom(bounds), 766, "Reject invalid full-screen keyboard frames rather than collapse the terminal")
        XCTAssertEqual(bottom(CGRect(x: 0, y: 540, width: 390, height: 300)), 540)
        XCTAssertEqual(bottom(CGRect(x: 0, y: 540, width: 390, height: 300), 540), 506,
            "Already resized parent must not subtract the keyboard again")
        XCTAssertEqual(bottom(CGRect(x: 0, y: 800, width: 390, height: 300)), 766)
        XCTAssertEqual(bottom(CGRect(x: 40, y: 450, width: 250, height: 240)), 766, "Floating keyboard")
        XCTAssertEqual(bottom(CGRect(x: 0, y: 0, width: 390, height: 0)), 766, "Hidden guide-like zero frame")
    }

    func testTerminalViewportTracksSafeAreaAndKeepsExistingTerminal() async throws {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "keyboard-layout-\(UUID())"))
        let controller = PiTerminalController(settings: PiTerminalSettings(defaults: defaults), slotDefaults: defaults)
        let viewport = PiTerminalViewportController(controller: controller)
        let window = UIWindow(windowScene: scene)
        window.frame = CGRect(x: 0, y: 0, width: 390, height: 844)
        window.rootViewController = viewport
        window.makeKeyAndVisible()
        defer { viewport.disconnectView(); window.isHidden = true }
        let terminal = viewport.terminalView
        var bytes: [[UInt8]] = []
        terminal.outboundBytesObserver = { bytes.append($0) }
        for size in [CGSize(width: 390, height: 844), CGSize(width: 844, height: 390)] {
            window.frame.size = size
            viewport.additionalSafeAreaInsets.bottom = 0
            window.layoutIfNeeded(); viewport.view.layoutIfNeeded()
            let fullHeight = terminal.bounds.height
            let fullRows = terminal.getTerminal().rows
            for inset: CGFloat in [160, 220, 0] {
                viewport.additionalSafeAreaInsets.bottom = inset
                window.layoutIfNeeded(); viewport.view.layoutIfNeeded()
                XCTAssertEqual(terminal.bounds.height, fullHeight - inset, accuracy: 1)
                XCTAssertEqual(viewport.toolbar.view.frame.height, 46, accuracy: 0.5)
                XCTAssertEqual(terminal.frame.maxY, viewport.toolbar.view.frame.minY, accuracy: 0.5)
                XCTAssertEqual(viewport.toolbar.view.frame.maxY, viewport.view.bounds.height - viewport.view.safeAreaInsets.bottom, accuracy: 0.5)
                XCTAssertTrue(terminal === viewport.terminalView)
                if inset > 0 { XCTAssertLessThan(terminal.getTerminal().rows, fullRows) }
                else { XCTAssertEqual(terminal.getTerminal().rows, fullRows) }
            }
        }
        XCTAssertTrue(bytes.isEmpty, "Layout cannot emit terminal input")
        XCTAssertEqual(controller.selectedSlot, .one)
    }

    func testTerminalViewportFollowsProxyKeyboardAndRestoresOnHide() async throws {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "keyboard-proxy-layout-\(UUID())"))
        let controller = PiTerminalController(settings: PiTerminalSettings(defaults: defaults), slotDefaults: defaults)
        let host = UIHostingController(rootView: TabView {
            ZStack {
                Color.black.ignoresSafeArea()
                PiTerminalContainer(controller: controller)
                    .background(Color.black)
            }
            .tabItem { Label("JARVIS", systemImage: "terminal.fill") }
        })
        let window = UIWindow(windowScene: scene)
        window.rootViewController = host; window.makeKeyAndVisible()
        try await Task.sleep(for: .milliseconds(300))
        func findViewport(_ parent: UIViewController) -> PiTerminalViewportController? {
            if let viewport = parent as? PiTerminalViewportController { return viewport }
            return parent.children.compactMap { findViewport($0) }.first
        }
        let viewport = try XCTUnwrap(findViewport(host))
        defer { window.endEditing(true); viewport.disconnectView(); window.isHidden = true }
        window.layoutIfNeeded(); viewport.view.layoutIfNeeded()
        let terminal = viewport.terminalView
        terminal.feed(text: "JARVIS local layout fixture — no SSH connection\r\nTerminal must remain above the purple toolbar.\r\n")
        let originalHeight = terminal.bounds.height
        let originalRows = terminal.getTerminal().rows
        XCTAssertGreaterThan(originalHeight, 500, "Terminal must fill the tab, not collapse to toolbar intrinsic height")
        let proxy = try XCTUnwrap(terminal.subviews.compactMap { $0 as? PiTerminalKeyboardResponder }.first)
        // Exercise the real responder/keyboard guide without enabling SSH input,
        // configuring credentials or connecting to any live terminal session.
        let input = UIInputView(frame: CGRect(x: 0, y: 0, width: window.bounds.width, height: 260), inputViewStyle: .keyboard)
        input.allowsSelfSizing = true
        input.heightAnchor.constraint(equalToConstant: 260).isActive = true
        proxy.inputView = input
        for cycle in 0..<2 {
            // A fixed input view keeps this deterministic even when the
            // simulator routes normal typing to a connected hardware keyboard.
            XCTAssertTrue(proxy.becomeFirstResponder())
            try await Task.sleep(for: .milliseconds(700))
            viewport.view.layoutIfNeeded()
            XCTAssertGreaterThan(terminal.bounds.height, 200)
            XCTAssertLessThan(terminal.bounds.height, originalHeight - 100)
            XCTAssertLessThan(terminal.getTerminal().rows, originalRows)
            XCTAssertTrue(findViewport(host) === viewport)
            XCTAssertEqual(terminal.frame.maxY, viewport.toolbar.view.frame.minY, accuracy: 1)
            XCTAssertEqual(viewport.toolbar.view.frame.height, 46, accuracy: 0.5)
            let image = UIGraphicsImageRenderer(size: window.bounds.size).image { _ in
                window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
            }
            let attachment = XCTAttachment(image: image)
            attachment.name = "terminal-keyboard-tabview-cycle-\(cycle)"
            attachment.lifetime = .keepAlways; add(attachment)
            XCTAssertTrue(proxy.resignFirstResponder())
            try await Task.sleep(for: .milliseconds(700))
            viewport.view.layoutIfNeeded()
            XCTAssertEqual(terminal.bounds.height, originalHeight, accuracy: 1)
            XCTAssertEqual(terminal.getTerminal().rows, originalRows)
        }
    }

    func testWatchTwoPurifierRowsKeep68PointFootprint() async throws {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let a = String(repeating: "a", count: 24), b = String(repeating: "b", count: 24)
        for width: CGFloat in [162, 184, 208] {
            for large in [false, true] {
                for scenario in 0..<4 {
                    let data = try JSONSerialization.data(withJSONObject: ["defaultDeviceID": a, "devices": [
                        a: ["name": "Dylan's Air Purifier", "deviceID": a, "ok": true, "isOn": scenario != 2, "mode": "manual", "pm25": scenario == 2 ? 150 : 1, "stale": scenario == 1],
                        b: ["name": "Bran's Air Purifier", "deviceID": b, "ok": scenario != 3, "isOn": true, "mode": "auto", "pm25": 2, "verificationPending": scenario == 1]
                    ]])
                    let state = try JSONDecoder().decode(PurifierSubsystem.self, from: data)
                    let card = CompactWatchPurifierCard(purifier: state, unavailable: false, busyDeviceID: nil,
                        accent: Color(red: 209/255, green: 131/255, blue: 232/255), surface: Color.white.opacity(0.075)) { _ in }
                        .environment(\.dynamicTypeSize, large ? .accessibility5 : .large)
                    let measurement = UIHostingController(rootView: card)
                    XCTAssertEqual(measurement.sizeThatFits(in: CGSize(width: width - 16, height: 1000)).height, 68, accuracy: 0.5)
                    let window = UIWindow(windowScene: scene)
                    window.frame = CGRect(x: 0, y: 0, width: width, height: 88)
                    let host = UIHostingController(rootView: card.padding(.horizontal, 8).padding(.top, 10)
                        .frame(width: width, height: 88, alignment: .top).background(Color.black).ignoresSafeArea())
                    host.overrideUserInterfaceStyle = .dark
                    window.rootViewController = host; window.makeKeyAndVisible(); host.view.layoutIfNeeded()
                    try await Task.sleep(for: .milliseconds(50))
                    let image = UIGraphicsImageRenderer(size: window.bounds.size).image { _ in
                        window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
                    }
                    let attachment = XCTAttachment(image: image)
                    attachment.name = "watch-purifier-rows-width-\(Int(width))-large-\(large)-scenario-\(scenario)"
                    attachment.lifetime = .keepAlways; add(attachment); window.isHidden = true
                }
            }
        }
    }

    func testFullFilterPercentageFitsCompactColumn() {
        let font = UIFont.monospacedDigitSystemFont(ofSize: 10, weight: .medium)
        for percent in 0...100 {
            XCTAssertLessThanOrEqual(("\(percent)%" as NSString).size(withAttributes: [.font: font]).width, 36)
        }
    }

    func testTwoPurifiersFitOriginalCardFootprint() async throws {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let a = String(repeating: "a", count: 24), b = String(repeating: "b", count: 24)
        for width: CGFloat in [320, 375, 414] {
            for dark in [false, true] {
                for large in [false, true] {
                  for scenario in 0..<3 {
                    let data = try JSONSerialization.data(withJSONObject: ["defaultDeviceID": a, "devices": [
                        a: ["name": "Dylan's Air Purifier", "deviceID": a, "ok": true, "isOn": scenario != 2, "mode": "auto", "pm25": scenario == 2 ? 150 : 1, "filterLife": scenario == 2 ? 9 : 69, "stale": scenario == 1],
                        b: ["name": "Bran's Air Purifier", "deviceID": b, "ok": true, "isOn": true, "mode": "auto", "pm25": scenario == 2 ? 45 : 2, "filterLife": 100, "verificationPending": scenario == 1]
                    ]])
                    let purifier = try JSONDecoder().decode(PurifierSubsystem.self, from: data)
                    let card = CompactPurifierCard(purifier: purifier) { _ in }
                        .environment(\.dynamicTypeSize, large ? .accessibility5 : .large)
                    let measurement = UIHostingController(rootView: card)
                    XCTAssertEqual(measurement.sizeThatFits(in: CGSize(width: width - 28, height: 1000)).height, 54, accuracy: 0.5)
                    let window = UIWindow(windowScene: scene)
                    window.frame = CGRect(x: 0, y: 0, width: width, height: 90)
                    let host = UIHostingController(rootView: card.padding(.horizontal, 14).padding(.top, 16)
                        .frame(width: width, height: 90, alignment: .top).background(Color(uiColor: .systemBackground)).ignoresSafeArea())
                    host.overrideUserInterfaceStyle = dark ? .dark : .light
                    window.rootViewController = host
                    window.makeKeyAndVisible()
                    host.view.layoutIfNeeded()
                    try await Task.sleep(for: .milliseconds(50))
                    let image = UIGraphicsImageRenderer(size: window.bounds.size).image { _ in
                        window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
                    }
                    // Sample empty top padding, away from the purple icons/border.
                    // The shared card surface is neutral (at most a tiny system blue bias).
                    let sample = try XCTUnwrap(image.cgImage?.cropping(to: CGRect(
                        x: (width / 2 * image.scale).rounded(), y: (19 * image.scale).rounded(), width: 1, height: 1)))
                    var rgba = [UInt8](repeating: 0, count: 4)
                    try rgba.withUnsafeMutableBytes { bytes in
                        let context = try XCTUnwrap(CGContext(data: bytes.baseAddress, width: 1, height: 1,
                            bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue))
                        context.draw(sample, in: CGRect(x: 0, y: 0, width: 1, height: 1))
                    }
                    let rgb = rgba.prefix(3).map(Int.init)
                    XCTAssertLessThanOrEqual(rgb.max()! - rgb.min()!, 3, "Card surface must not have a purple tint")
                    let attachment = XCTAttachment(image: image)
                    attachment.name = "two-purifiers-width-\(Int(width))-dark-\(dark)-accessibility-\(large)-scenario-\(scenario)"
                    attachment.lifetime = .keepAlways
                    add(attachment)
                    window.isHidden = true
                  }
                }
            }
        }
    }

    func testPasteIconExists() {
        XCTAssertNotNil(UIImage(systemName: "doc.on.clipboard"))
    }

    func testPlainPasteButtonRendersWithoutBlackPlatter() async throws {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        for dark in [false, true] {
            for enabled in [false, true] {
                let window = UIWindow(windowScene: scene)
                window.frame = CGRect(x: 0, y: 0, width: 160, height: 100)
                let configuration = UIPasteControl.Configuration()
                configuration.displayMode = .iconOnly
                configuration.baseForegroundColor = UIColor(JarvisPalette.accent)
                configuration.baseBackgroundColor = .clear
                let old = UIPasteControl(configuration: configuration)
                old.backgroundColor = .clear
                old.isOpaque = false
                let receiver = UIView(frame: .zero)
                receiver.pasteConfiguration = UIPasteConfiguration(forAccepting: NSString.self)
                old.target = receiver
                var taps = 0
                let host = UIHostingController(rootView:
                    HStack(spacing: 24) {
                        PasteRenderFixture(control: old).frame(width: 46, height: 46)
                        PiTerminalPasteControl { taps += 1 }
                            .disabled(!enabled)
                    }.padding(.leading, 16).padding(.top, 20)
                     .frame(width: 160, height: 100, alignment: .topLeading)
                     .background(Color(white: 0.25)).ignoresSafeArea()
                )
                host.overrideUserInterfaceStyle = dark ? .dark : .light
                window.rootViewController = host
                window.makeKeyAndVisible()
                defer { window.isHidden = true }
                host.view.layoutIfNeeded()
                try await Task.sleep(nanoseconds: 100_000_000)
                let format = UIGraphicsImageRendererFormat()
                format.scale = 1
                format.preferredRange = .standard
                let image = UIGraphicsImageRenderer(size: window.bounds.size, format: format).image { _ in
                    window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
                }
                let attachment = XCTAttachment(image: image)
                attachment.name = "native-left-plain-right-dark-\(dark)-enabled-\(enabled)"
                attachment.lifetime = .keepAlways
                add(attachment)
                let cg = try XCTUnwrap(image.cgImage)
                XCTAssertEqual(cg.bitsPerPixel, 32)
                let bytes = try XCTUnwrap(cg.dataProvider?.data) as Data
                func pixel(_ x: Int, _ y: Int) -> [UInt8] {
                    Array(bytes[(y * cg.bytesPerRow + x * 4)..<(y * cg.bytesPerRow + x * 4 + 4)])
                }
                // All perimeter pixels, not just a rounded corner, must expose
                // the unchanged toolbar. The centre must contain a real glyph.
                for y in 20..<66 {
                    XCTAssertEqual(pixel(88, y), pixel(4, y))
                    XCTAssertEqual(pixel(129, y), pixel(4, y))
                }
                for x in 86..<132 {
                    XCTAssertEqual(pixel(x, 22), pixel(4, 22))
                    XCTAssertEqual(pixel(x, 63), pixel(4, 63))
                }
                let changed = (20..<66).reduce(0) { count, y in
                    count + (86..<132).filter { pixel($0, y) != pixel(4, y) }.count
                }
                XCTAssertGreaterThan(changed, 20, "Reject an empty render")
                XCTAssertLessThan(changed, 500, "Only the icon should be drawn, not a filled platter")
                XCTAssertEqual(taps, 0, "Rendering cannot read or paste clipboard contents")
            }
        }
    }

    func testToolbarAccentContrastOnOpaqueSurface() {
        func rgb(_ color: UIColor, traits: UITraitCollection) -> [Double] {
            var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
            XCTAssertTrue(color.resolvedColor(with: traits).getRed(&r, green: &g, blue: &b, alpha: &a))
            return [Double(r), Double(g), Double(b)]
        }
        func luminance(_ rgb: [Double]) -> Double {
            let linear = rgb.map { $0 <= 0.04045 ? $0 / 12.92 : pow(($0 + 0.055) / 1.055, 2.4) }
            return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722
        }
        for style: UIUserInterfaceStyle in [.light, .dark] {
            let traits = UITraitCollection(userInterfaceStyle: style)
            let accent = rgb(UIColor(JarvisPalette.accent), traits: traits)
            let surface = rgb(.secondarySystemBackground, traits: traits)
            let keySurface = zip(accent, surface).map { $0 * 0.10 + $1 * 0.90 }
            for background in [surface, keySurface] {
                let a = luminance(accent), b = luminance(background)
                XCTAssertGreaterThanOrEqual((max(a, b) + 0.05) / (min(a, b) + 0.05), 4.5)
            }
        }
    }

    func testCompactToolbarWidthBudgetKeepsEveryControlVisible() {
        for width: CGFloat in [320, 375, 390, 414, 768, 844] {
            for attachments in [false, true] {
                let metrics = PiTerminalToolbarMetrics(availableWidth: width, showsAttachments: attachments)
                XCTAssertEqual(metrics.actions.count, attachments ? 9 : 8)
                let total = metrics.actions.reduce(CGFloat.zero) { $0 + metrics.width(for: $1) }
                    + CGFloat(metrics.actions.count - 1) * PiTerminalToolbarMetrics.spacing
                    + 2 * PiTerminalToolbarMetrics.inset
                XCTAssertEqual(total, width, accuracy: 0.001)
                for action in metrics.actions {
                    XCTAssertGreaterThanOrEqual(metrics.width(for: action), 26)
                }
                XCTAssertGreaterThan(metrics.width(for: .control), 37)
            }
        }
        XCTAssertEqual(PiTerminalToolbarMetrics.height, 46)
    }

    func testCompactToolbarRendersAllNineControlsInOneRow() async throws {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        for width in [320, 375, 414, 768] {
            for dark in [false, true] {
                for state in 0..<4 {
                    let enabled = state != 2
                    let latched = state == 1
                    let shown = state == 1 || state == 3
                    var actions: [PiTerminalToolbarAction] = []
                    let window = UIWindow(windowScene: scene)
                    window.frame = CGRect(x: 0, y: 0, width: width, height: 100)
                    let host = UIHostingController(rootView:
                        PiTerminalToolbarContent(showsAttachments: true, canSend: enabled,
                            canAttach: enabled && state != 3, controlLatched: latched, keyboardShown: shown) {
                                actions.append($0)
                            }
                            .frame(width: CGFloat(width), height: 46)
                            .frame(width: CGFloat(width), height: 100, alignment: .topLeading)
                            .background(Color.black).ignoresSafeArea()
                    )
                    host.overrideUserInterfaceStyle = dark ? .dark : .light
                    window.rootViewController = host
                    window.makeKeyAndVisible()
                    defer { window.isHidden = true }
                    host.view.layoutIfNeeded()
                    try await Task.sleep(nanoseconds: 100_000_000)
                    let format = UIGraphicsImageRendererFormat()
                    format.scale = 1
                    format.preferredRange = .standard
                    let image = UIGraphicsImageRenderer(size: window.bounds.size, format: format).image { _ in
                        window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
                    }
                    let attachment = XCTAttachment(image: image)
                    attachment.name = "compact-toolbar-\(width)-dark-\(dark)-state-\(state)"
                    attachment.lifetime = .keepAlways
                    add(attachment)
                    let cg = try XCTUnwrap(image.cgImage)
                    XCTAssertEqual(cg.bitsPerPixel, 32)
                    let bytes = try XCTUnwrap(cg.dataProvider?.data) as Data
                    func pixel(_ x: Int, _ y: Int) -> [Int] {
                        let start = y * cg.bytesPerRow + x * 4
                        return bytes[start..<(start + 3)].map(Int.init)
                    }
                    let metrics = PiTerminalToolbarMetrics(availableWidth: CGFloat(width), showsAttachments: true)
                    var x = PiTerminalToolbarMetrics.inset
                    for action in metrics.actions {
                        let cellWidth = metrics.width(for: action)
                        let baseline = pixel(Int(x + cellWidth / 2), 9)
                        var glyphPixels = 0
                        for px in Int(x + 4)..<Int(x + cellWidth - 4) {
                            for py in 14..<33 {
                                let color = pixel(px, py)
                                if zip(color, baseline).reduce(0, { $0 + abs($1.0 - $1.1) }) > 25 {
                                    glyphPixels += 1
                                }
                            }
                        }
                        XCTAssertGreaterThan(glyphPixels, 10, "Missing/clipped \(action) at \(width), dark=\(dark), state=\(state)")
                        x += cellWidth + PiTerminalToolbarMetrics.spacing
                    }
                    XCTAssertTrue(actions.isEmpty, "Layout must never activate a terminal action")
                }
            }
        }
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

private struct PasteRenderFixture: UIViewRepresentable {
    let control: UIPasteControl
    func makeUIView(context: Context) -> UIPasteControl { control }
    func updateUIView(_ uiView: UIPasteControl, context: Context) {}
}
