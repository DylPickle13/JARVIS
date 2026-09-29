import XCTest
import SwiftUI
import JARVISKit
@testable import JARVIS

@MainActor
final class SystemDashboardViewTests: XCTestCase {
    private func presentation(offline: Bool = false, includeExtraService: Bool = true) throws -> SystemDashboardPresentation {
        let meta: [String: Any] = Dictionary(uniqueKeysWithValues:
            ["services", "pi", "plugs", "purifier", "network", "codexQuota"].map {
                ($0, ["ok": true, "stale": false, "ageSeconds": 10] as [String: Any])
            })
        var services: [String: Any] = [
            "runner": ["ok": true, "displayName": "Scheduled Jobs Runner", "description": "Runs due jobs into bounded private local history",
                "critical": true, "executionMode": "periodic", "loaded": true, "running": false, "lastExitCode": 0],
            "voice": ["ok": true, "displayName": "Room Audio Server", "critical": false, "running": false, "executionMode": "continuous"]]
        if includeExtraService {
            services["broken"] = ["ok": true, "displayName": "Required daemon", "critical": true, "running": false, "executionMode": "continuous"]
        }
        let object: [String: Any] = ["ok": true, "version": "test-fixture", "uptimeSeconds": 90000,
            "subsystemsMeta": meta, "subsystems": [
                "services": ["ok": true, "services": services],
                "plugs": ["ok": true, "stale": false, "plugs": [:]],
                "purifier": ["ok": true, "stale": false]]]
        let state = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        let now = Date()
        return .init(snapshot: state, requestStartedAt: now, isConnected: !offline, now: now)
    }

    private func content(_ presentation: SystemDashboardPresentation, compact: Bool) -> some View {
        SystemDashboardContent(presentation: presentation, connectionLabel: "Fixture · no network",
            compact: compact, accent: .purple, warning: .orange, surface: Color(.secondarySystemGroupedBackground),
            connectionError: presentation.isConnected ? nil : "Fixture connection unavailable", onRefresh: compact ? nil : {})
            .padding(8)
    }

    func testCompactDashboardFitsWatchWidthAndSupportsAccessibilityText() throws {
        let dashboard = try presentation()
        for size: DynamicTypeSize in [.large, .accessibility3] {
            let host = UIHostingController(rootView: content(dashboard, compact: true).dynamicTypeSize(size))
            let measured = host.sizeThatFits(in: CGSize(width: 162, height: 197))
            XCTAssertLessThanOrEqual(measured.width, 162.5)
            XCTAssertGreaterThan(measured.height, 100)
            XCTAssertLessThanOrEqual(measured.height, 197, "All overview content must fit the 40mm canvas without scrolling or clipping")
        }
    }

    func testPhoneDashboardFitsPortraitLandscapeAndLargeTextWithoutScrolling() throws {
        for offline in [false, true] {
            let dashboard = try presentation(offline: offline)
            for (viewport, textSize) in [
                (CGSize(width: 375, height: 650), DynamicTypeSize.large),
                (CGSize(width: 414, height: 720), .large),
                (CGSize(width: 320, height: 450), .large),
                (CGSize(width: 750, height: 270), .large),
                (CGSize(width: 375, height: 650), .accessibility3)
            ] {
                let host = UIHostingController(rootView: content(dashboard, compact: false).dynamicTypeSize(textSize))
                let measured = host.sizeThatFits(in: viewport)
                XCTAssertLessThanOrEqual(measured.width, viewport.width + 0.5)
                XCTAssertLessThanOrEqual(measured.height, viewport.height + 0.5,
                    "Entire overview must fit \(viewport) at \(textSize), offline=\(offline)")
            }
        }
    }

    func testWatchOverviewRendersOneScreenSummary() throws {
        let dashboard = try presentation(includeExtraService: false)
        let renderer = ImageRenderer(content: SystemDashboardContent(presentation: dashboard,
            connectionLabel: "Fixture", compact: true, accent: .purple, warning: .orange,
            surface: Color.white.opacity(0.075))
            .padding(.horizontal, 8).padding(.vertical, 7)
            .frame(width: 162, height: 197, alignment: .top)
            .background(Color.black).environment(\.colorScheme, .dark))
        renderer.scale = 3
        let image = try XCTUnwrap(renderer.uiImage)
        XCTAssertEqual(image.size, CGSize(width: 162, height: 197))
        let attachment = XCTAttachment(image: image)
        attachment.name = "system-watch-one-screen-two-services"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testOverviewDoesNotMountAScrollView() throws {
        let dashboard = try presentation()
        for compact in [false, true] {
            let host = UIHostingController(rootView: content(dashboard, compact: compact))
            host.view.frame = CGRect(x: 0, y: 0, width: compact ? 162 : 375, height: compact ? 197 : 650)
            host.view.layoutIfNeeded()
            func scrollViews(in view: UIView) -> Int {
                (view is UIScrollView ? 1 : 0) + view.subviews.reduce(0) { $0 + scrollViews(in: $1) }
            }
            XCTAssertEqual(scrollViews(in: host.view), 0, "Detail sheets may scroll; the closed overview must not")
        }
    }

    func testPhoneDashboardRendersLightDarkAndOfflineFixtures() throws {
        for offline in [false, true] {
            for scheme in [ColorScheme.light, .dark] {
                let dashboard = try presentation(offline: offline)
                // No clipping modifier or tall scroll content: render the real
                // constrained overview and verify its natural extent separately.
                let renderer = ImageRenderer(content: content(dashboard, compact: false)
                    .frame(width: 375, height: 650, alignment: .top)
                    .background(Color(.systemGroupedBackground))
                    .environment(\.colorScheme, scheme))
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.uiImage)
                XCTAssertEqual(image.size, CGSize(width: 375, height: 650))
                let data = try XCTUnwrap(image.cgImage?.dataProvider?.data)
                let bytes = try XCTUnwrap(CFDataGetBytePtr(data))
                let nonblack = stride(from: 0, to: CFDataGetLength(data) - 3, by: 4).filter {
                    bytes[$0] > 10 || bytes[$0 + 1] > 10 || bytes[$0 + 2] > 10
                }.count
                XCTAssertGreaterThan(nonblack, 1000, "Reject empty/black snapshot evidence")
                let attachment = XCTAttachment(image: image)
                attachment.name = "system-dashboard-\(scheme)-\(offline ? "offline" : "connected")"
                attachment.lifetime = .keepAlways
                add(attachment)
            }
        }
    }
}
