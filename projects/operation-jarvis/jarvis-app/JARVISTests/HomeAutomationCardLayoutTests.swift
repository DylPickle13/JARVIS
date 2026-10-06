import XCTest
import SwiftUI
import UIKit
import JARVISKit
@testable import JARVIS

@MainActor
final class HomeAutomationCardLayoutTests: XCTestCase {
    private func content(_ control: HomeAutomationControl, size: HomeAutomationCardContent.Size,
                         status: String = "On", busy: Bool = false, warning: Bool = false) -> some View {
        HomeAutomationCardContent(control: control, status: status,
            enabled: status == "On" ? true : status == "Off" ? false : nil, busy: busy,
            hasWarning: warning, size: size, accent: .purple, warning: .orange,
            surface: Color.white.opacity(0.075))
    }

    func testPhoneAutomationCardsMatchRealPlugCardHeightForEveryStateAndTextSize() {
        for width in [CGFloat(140), 175, 288] {
            for text in [DynamicTypeSize.large, .accessibility3] {
                let plug = UIHostingController(rootView: PlugCard(name: "lamp", isOn: true, isBusy: false).dynamicTypeSize(text))
                let plugSize = plug.sizeThatFits(in: CGSize(width: width, height: 1000))
                XCTAssertEqual(plugSize.height, 54, accuracy: 0.5)
                for control in HomeAutomationControl.allCases {
                    for status in ["On", "Off", "Unavailable", "Unconfirmed", "Changing…"] {
                        let host = UIHostingController(rootView: content(control, size: .phone, status: status,
                            busy: status == "Changing…", warning: status == "Unconfirmed").dynamicTypeSize(text))
                        let measured = host.sizeThatFits(in: CGSize(width: width, height: 1000))
                        XCTAssertEqual(measured.height, plugSize.height, accuracy: 0.5)
                        XCTAssertLessThanOrEqual(measured.width, width + 0.5)
                    }
                }
            }
        }
    }

    func testBothWatchCardsKeepOneCompactRowBelowHealth() throws {
        for viewport in [CGSize(width: 162, height: 197), CGSize(width: 184, height: 224)] {
            let row = HStack(spacing: 4) {
                content(.automaticVoice, size: .watch)
                content(.barnDoor, size: .watch, status: "Off")
            }
            let host = UIHostingController(rootView: row)
            let measured = host.sizeThatFits(in: CGSize(width: viewport.width - 16, height: 1000))
            XCTAssertEqual(measured.height, 44, accuracy: 0.5)
            let homeContent = VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 6) { Image(systemName: "house.fill"); Text("Home").font(.headline.weight(.bold)); Spacer() }
                SystemDashboardContent(presentation: .init(snapshot: nil, requestStartedAt: nil),
                    connectionLabel: "Synthetic fixture · no network", compact: true,
                    accent: .purple, warning: .orange, surface: Color.white.opacity(0.075))
                row
            }.padding(.horizontal, 8).padding(.vertical, 7)
            let extent = UIHostingController(rootView: homeContent).sizeThatFits(in:
                CGSize(width: viewport.width, height: 1000))
            XCTAssertLessThanOrEqual(extent.width, viewport.width + 0.5)
            // Health and history remain intact; Crown overflow, not smaller cards
            // or clipped content, accommodates the new health-first ordering.
            XCTAssertGreaterThan(extent.height, measured.height)
            for scheme in [ColorScheme.light, .dark] {
                let renderer = ImageRenderer(content: homeContent.frame(width: viewport.width)
                    .background(scheme == .dark ? Color.black : Color.white).environment(\.colorScheme, scheme))
                renderer.scale = 3
                let attachment = XCTAttachment(image: try XCTUnwrap(renderer.uiImage))
                attachment.name = "synthetic-watch-health-before-controls-\(Int(viewport.width))-\(scheme)"
                attachment.lifetime = .keepAlways; add(attachment)
            }
        }
    }

    func testAccessibilityWatchCardsGrowRatherThanClipText() {
        let view = VStack(spacing: 4) {
            content(.automaticVoice, size: .watch)
            content(.barnDoor, size: .watch, status: "Off")
        }.dynamicTypeSize(.accessibility3)
        let measured = UIHostingController(rootView: view).sizeThatFits(in: CGSize(width: 146, height: 1000))
        XCTAssertGreaterThanOrEqual(measured.height, 92)
        XCTAssertLessThanOrEqual(measured.width, 146.5)
    }

    func testCompactLabelsRemoveOnlyStaticSubtitlesAndKeepAllWriteSafeguards() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let phone = try String(contentsOf: root.appendingPathComponent("JARVIS/Views/SystemView.swift"), encoding: .utf8)
        let watch = try String(contentsOf: root.appendingPathComponent("JARVISWatch/Views/WatchDashboardContent.swift"), encoding: .utf8)
        let label = try String(contentsOf: root.appendingPathComponent("JARVISKit/Sources/JARVISKit/HomeAutomationCardContent.swift"), encoding: .utf8)
        XCTAssertFalse(phone.contains("Text(control.detail)")); XCTAssertFalse(watch.contains("Text(control.detail)"))
        for source in [phone, watch] {
            XCTAssertTrue(source.contains("outcomeWarning"))
            XCTAssertTrue(source.contains(".accessibilityValue(label +"))
            XCTAssertTrue(source.contains(".accessibilityLabel(control.title)"))
            XCTAssertTrue(source.contains(".accessibilityElement(children: .ignore)"))
            XCTAssertTrue(source.contains("state?.canChange(control"))
            XCTAssertTrue(source.contains("barnConfirmation = command"))
            XCTAssertTrue(source.contains("does not stop an alarm already sounding"))
        }
        let start = try XCTUnwrap(watch.range(of: "private var homePage: some View"))
        let end = try XCTUnwrap(watch.range(of: "private func homeAutomationCard", range: start.upperBound..<watch.endIndex))
        let home = String(watch[start.lowerBound..<end.lowerBound])
        let header = try XCTUnwrap(home.range(of: "pageHeader(\"Home\"")).lowerBound
        let health = try XCTUnwrap(home.range(of: "WatchSystemHealthView(model:")).lowerBound
        let controls = try XCTUnwrap(home.range(of: "homeAutomationCard(control")).lowerBound
        XCTAssertLessThan(header, health)
        XCTAssertLessThan(health, controls, "Watch must match the iPhone health-first Home order")
        XCTAssertLessThan(controls, try XCTUnwrap(home.range(of: "outcomeWarning")).lowerBound)
        XCTAssertEqual(home.components(separatedBy: "WatchSystemHealthView(model:").count - 1, 1)
        XCTAssertLessThan(try XCTUnwrap(phone.range(of: "SystemDashboardContent(presentation:")).lowerBound,
                          try XCTUnwrap(phone.range(of: "HomeAutomationCards {")).lowerBound)
        XCTAssertTrue(watch.contains("WatchSystemCrownViewport(active: scenePhase == .active && !dimmed && selectedPage == .home && !overlayOwnsInput)"))
        XCTAssertTrue(home.contains("HStack(spacing: 4)"))
        XCTAssertTrue(watch.contains(".disabled(busy || dimmed || scenePhase != .active"))
        for forbidden in ["Button(", "Task {", "JarvisClient", "setHomeAutomation"] { XCTAssertFalse(label.contains(forbidden)) }
    }
}
