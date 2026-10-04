import XCTest
import SwiftUI
import UIKit
import CoreText
import JARVISKit
@testable import JARVIS

@MainActor
final class PiSessionGlyphViewTests: XCTestCase {
    func testDashboardUsesOneLargerScaledSizeForCardsAndRoomAudio() throws {
        XCTAssertEqual(PiSessionGlyphs.dashboardSize, 22)
        XCTAssertEqual(PiSessionGlyph(lifecycle: .running, active: false).size, 22)
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let dashboard = try String(contentsOf: root.appendingPathComponent("JARVIS/Views/HomeView.swift"))
        XCTAssertTrue(dashboard.contains("@ScaledMetric(relativeTo: .body) private var iconSize = PiSessionGlyphs.dashboardSize"))
        XCTAssertTrue(dashboard.contains("@ScaledMetric(relativeTo: .body) private var roomAudioIconSize = PiSessionGlyphs.dashboardSize"))
    }

    func testEveryFrameAndStaticGlyphHasRealFontCoverage() {
        let glyphs = PiSessionGlyphs.busyFrames + ["●", "○", "×", "?"]
        let font = UIFont.monospacedSystemFont(ofSize: PiSessionGlyphs.dashboardSize, weight: .regular)
        for glyph in glyphs {
            let line = CTLineCreateWithAttributedString(NSAttributedString(string: glyph,
                attributes: [.font: font]))
            let runs = CTLineGetGlyphRuns(line) as! [CTRun]
            XCTAssertFalse(runs.isEmpty, glyph)
            for run in runs {
                let count = CTRunGetGlyphCount(run)
                XCTAssertGreaterThan(count, 0, glyph)
                var renderedGlyphs = [CGGlyph](repeating: 0, count: count)
                CTRunGetGlyphs(run, CFRange(location: 0, length: 0), &renderedGlyphs)
                XCTAssertFalse(renderedGlyphs.contains(0), "missing glyph: \(glyph)")
            }
        }
    }

    func testInactiveAndBackgroundIndicatorsKeepFixedBoundsInBothAppearances() throws {
        for state in [PiSessionLifecycle.running, .compacting, .idle, .new, .offline, .unknown] {
            for scene in [ScenePhase.active, .inactive, .background] {
                for colorScheme in [ColorScheme.light, .dark] {
                    for size: CGFloat in [18, PiSessionGlyphs.dashboardSize, 30] {
                        let content = PiSessionGlyph(lifecycle: state, active: false, size: size)
                            .environment(\.scenePhase, scene)
                            .environment(\.colorScheme, colorScheme)
                        let renderer = ImageRenderer(content: content)
                        renderer.scale = 3
                        let image = try XCTUnwrap(renderer.uiImage)
                        XCTAssertEqual(image.size.width, size)
                        XCTAssertEqual(image.size.height, size)
                    }
                }
            }
        }
    }

    func testAllGlyphFramesRenderInTheSameBox() throws {
        let size = PiSessionGlyphs.dashboardSize
        for colorScheme in [ColorScheme.light, .dark] {
            let frames = HStack(spacing: 8) {
                ForEach(Array(PiSessionGlyphs.busyFrames.enumerated()), id: \.offset) { _, glyph in
                    Text(glyph)
                        .font(.system(size: size, weight: .regular, design: .monospaced))
                        .foregroundStyle(PiSessionLifecycle.running.statusColor)
                        .frame(width: size, height: size)
                }
            }
            .padding(8)
            .background(colorScheme == .dark ? Color.black : Color.white)
            let renderer = ImageRenderer(content: frames.environment(\.colorScheme, colorScheme))
            renderer.scale = 3
            let image = try XCTUnwrap(renderer.uiImage)
            XCTAssertEqual(image.size.width, 308)
            XCTAssertEqual(image.size.height, 38)
            let attachment = XCTAttachment(image: image)
            attachment.name = "pi-braille-frames-\(colorScheme)"
            attachment.lifetime = .keepAlways
            add(attachment)
            try XCTUnwrap(image.pngData()).write(to: URL(fileURLWithPath:
                "/tmp/jarvis-dashboard-braille-frames-\(colorScheme).png"))
        }
    }

    func testHostedBusyGlyphsActuallyAdvanceAndStopOffPage() async throws {
        try XCTSkipIf(UIAccessibility.isReduceMotionEnabled, "System Reduce Motion intentionally disables the display clock")
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        for state in [PiSessionLifecycle.running, .compacting] {
            func content(active: Bool) -> AnyView {
                AnyView(PiSessionGlyph(lifecycle: state, active: active)
                    .frame(width: 44, height: 44)
                    .environment(\.scenePhase, .active))
            }
            let host = UIHostingController(rootView: content(active: true))
            host.view.backgroundColor = .black
            let window = UIWindow(windowScene: scene)
            window.overrideUserInterfaceStyle = .dark
            window.rootViewController = host
            window.makeKeyAndVisible()
            defer { window.isHidden = true }
            host.view.layoutIfNeeded()
            try await Task.sleep(for: .milliseconds(180))

            func snapshot() throws -> Data {
                let image = UIGraphicsImageRenderer(size: CGSize(width: 44, height: 44)).image { context in
                    context.cgContext.translateBy(x: 22 - host.view.bounds.midX, y: 22 - host.view.bounds.midY)
                    XCTAssertTrue(host.view.drawHierarchy(in: host.view.bounds, afterScreenUpdates: true))
                }
                return try XCTUnwrap(image.pngData())
            }
            var movingFrames = Set<Data>()
            for _ in 0..<6 {
                movingFrames.insert(try snapshot())
                try await Task.sleep(for: .milliseconds(110))
            }
            XCTAssertGreaterThan(movingFrames.count, 1, "The production periodic timeline must visibly advance")

            host.rootView = content(active: false)
            try await Task.sleep(for: .milliseconds(180))
            let frozen = try snapshot()
            for _ in 0..<3 {
                try await Task.sleep(for: .milliseconds(110))
                XCTAssertEqual(try snapshot(), frozen, "Off-page indicators must stay static")
            }
        }
    }

    func testDashboardAndRoomAudioShareGlyphsWhileTerminalCapsulesArePreserved() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let dashboard = try String(contentsOf: root.appendingPathComponent("JARVIS/Views/HomeView.swift"))
        XCTAssertEqual(dashboard.components(separatedBy: "PiSessionGlyph(lifecycle: lifecycle").count - 1, 2)
        XCTAssertFalse(dashboard.contains("Image(systemName: presentation.symbol)"))
        XCTAssertFalse(dashboard.contains(".piSessionMotion("))
        XCTAssertTrue(dashboard.contains("active: homeMotionActive && !app.isAwaitingFreshState"))
        XCTAssertTrue(dashboard.contains(".accessibilityLabel(\"Pi session "))
        XCTAssertTrue(dashboard.contains(".accessibilityLabel(\"Room Audio, Pi session 10"))
        for path in ["JARVIS/Terminal/PiTerminalView.swift", "JARVISWatch/Views/WatchTerminalView.swift"] {
            let terminal = try String(contentsOf: root.appendingPathComponent(path))
            XCTAssertTrue(terminal.contains("Capsule()"))
            XCTAssertTrue(terminal.contains(".piSessionMotion("))
            XCTAssertFalse(terminal.contains("PiSessionGlyph("))
        }
    }
}
