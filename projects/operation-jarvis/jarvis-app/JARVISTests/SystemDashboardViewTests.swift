import XCTest
import SwiftUI
import JARVISKit
@testable import JARVIS

@MainActor
final class SystemDashboardViewTests: XCTestCase {
    private func presentation(offline: Bool = false, includeExtraService: Bool = true, sensorState: String? = nil) throws -> SystemDashboardPresentation {
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
        var object: [String: Any] = ["ok": true, "version": "test-fixture", "uptimeSeconds": 90000,
            "subsystemsMeta": meta, "subsystems": [
                "services": ["ok": true, "services": services],
                "plugs": ["ok": true, "stale": false, "plugs": [:]],
                "purifier": ["ok": true, "stale": false]]]
        let now = Date()
        if let sensorState {
            let reason = sensorState == "unavailable" ? "sensor_read_failed"
                : sensorState == "unknown" ? "not_checked"
                : sensorState == "inactive" ? "monitoring_disabled" : "current"
            func evidence(_ state: String, _ reason: String) -> [String: Any] {
                ["state": state, "reason": reason,
                 "sourceObservedAt": now.addingTimeInterval(-10).formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true)),
                 "validUntil": now.addingTimeInterval(120).formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true))]
            }
            object["health"] = ["scope": "cached_status_health", "components": [
                "security": evidence(sensorState, reason), "overall": evidence("healthy", "current")]]
            object["generatedAt"] = now.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true))
        }
        let state = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        return .init(snapshot: state, requestStartedAt: now, isConnected: !offline, now: now)
    }

    private func content(_ presentation: SystemDashboardPresentation, compact: Bool) -> some View {
        SystemDashboardContent(presentation: presentation, connectionLabel: "Fixture · no network",
            compact: compact, accent: .purple, warning: .orange, surface: Color(.secondarySystemGroupedBackground),
            connectionError: presentation.isConnected ? nil : "Fixture connection unavailable", onRefresh: compact ? nil : {})
            .padding(8)
    }

    private func historyFixture(compact: Bool) async throws -> SystemHistoryModel {
        let window: SystemHistoryWindow = compact ? .hour : .day
        let end = Date()
        let start = end.addingTimeInterval(-window.seconds)
        func stamp(_ value: Date) -> String { value.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true)) }
        let ids = compact ? ["overall"] : ["services", "pi", "network", "devices", "overall"]
        let object: [String: Any] = ["ok": true, "schemaVersion": 1, "scope": "cached_status_health", "window": window.rawValue,
            "from": stamp(start), "to": stamp(end), "sampleIntervalSeconds": 60,
            "resolutionSeconds": Int(window.resolution), "coverageLeaseSeconds": 90, "retentionSeconds": 604800,
            "earliestSampleAt": stamp(start), "latestSampleAt": stamp(end.addingTimeInterval(-10)),
            "series": ids.map { id in ["id": id, "buckets": (0..<window.bucketCount).map { index -> [String: Any] in
                let lo = start.addingTimeInterval(Double(index)*window.resolution)
                let partial = index % 7 == 0
                let unavailable = index % 13 == 0 && !partial
                let state = partial ? "unknown" : unavailable ? "unavailable" : "healthy"
                return ["from": stamp(lo), "to": stamp(lo.addingTimeInterval(window.resolution)),
                    "state": state, "reasonCodes": [unavailable ? "collector_failed" : "current"],
                    "coverageSeconds": partial ? window.resolution/2 : window.resolution,
                    "missingSeconds": partial ? window.resolution/2 : 0,
                    "stateSeconds": [(partial ? "healthy" : state): partial ? window.resolution/2 : window.resolution],
                    "mixed": partial, "sourceObservedAt": stamp(lo)]
            }] }]
        let response = try JSONDecoder().decode(SystemHistoryResponse.self, from: JSONSerialization.data(withJSONObject: object))
        let model = SystemHistoryModel(fetch: { _, _, _ in response })
        model.configure(.init(endpoint: .init(baseURL: URL(string: "http://fixture.invalid")!, token: "fixture-only"),
            surface: compact ? .watch : .phone, visible: true, interactive: true, connected: true))
        for _ in 0..<100 where model.snapshot == nil { try await Task.sleep(for: .milliseconds(5)) }
        XCTAssertNotNil(model.snapshot)
        return model
    }

    func testRecordedHistoryRendersAndFitsPhoneAndWatchWithRealCoverageStates() async throws {
        let dashboard = try presentation(includeExtraService: false)
        for compact in [false, true] {
            let model = try await historyFixture(compact: compact)
            let view = SystemDashboardContent(presentation: dashboard, connectionLabel: "Synthetic fixture · no network",
                compact: compact, accent: .purple, warning: .orange, surface: Color.white.opacity(0.075), historyModel: model).padding(8)
            let viewport = compact ? CGSize(width: 162, height: 197) : CGSize(width: 375, height: 650)
            for size: DynamicTypeSize in [.large, .accessibility3] {
                let host = UIHostingController(rootView: view.dynamicTypeSize(size))
                let extent = host.sizeThatFits(in: viewport)
                XCTAssertLessThanOrEqual(extent.width, viewport.width+0.5)
                XCTAssertLessThanOrEqual(extent.height, viewport.height)
            }
            for scheme in [ColorScheme.light, .dark] {
                let renderer = ImageRenderer(content: view.frame(width: viewport.width, height: viewport.height, alignment: .top)
                    .background(scheme == .dark ? Color.black : Color(.systemGroupedBackground)).environment(\.colorScheme, scheme))
                renderer.scale = 3
                let image = try XCTUnwrap(renderer.uiImage)
                let attachment = XCTAttachment(image: image)
                attachment.name = "system-history-synthetic-\(compact ? "watch" : "phone")-\(scheme)"
                attachment.lifetime = .keepAlways;add(attachment)
            }
            model.configure(.init(endpoint: nil, surface: compact ? .watch : .phone, visible: false, interactive: false, connected: false))
        }
    }

    func testSensorInclusiveOverviewFitsPhoneAndWatchWithoutAddingScrollOrDroppingSensor() throws {
        for sensorState in ["healthy", "unavailable", "unknown", "inactive"] {
            for offline in [false, true] {
                let dashboard = try presentation(offline: offline, includeExtraService: false, sensorState: sensorState)
                XCTAssertEqual(dashboard.compactSubsystemRows.count, 6)
                XCTAssertTrue(dashboard.compactSubsystemRows.contains { $0.id == "security" })
                if !offline && sensorState == "unavailable" { XCTAssertEqual(dashboard.state, .issue) }
                if !offline && sensorState == "unknown" { XCTAssertEqual(dashboard.state, .unknown) }
                for (compact, viewport, textSize) in [
                    (true, CGSize(width: 162, height: 197), DynamicTypeSize.large),
                    (true, CGSize(width: 162, height: 197), .accessibility3),
                    (false, CGSize(width: 375, height: 650), .large),
                    (false, CGSize(width: 320, height: 450), .large),
                    (false, CGSize(width: 750, height: 270), .large),
                    (false, CGSize(width: 375, height: 650), .accessibility3)
                ] {
                    let host = UIHostingController(rootView: content(dashboard, compact: compact).dynamicTypeSize(textSize))
                    let measured = host.sizeThatFits(in: viewport)
                    XCTAssertLessThanOrEqual(measured.width, viewport.width + 0.5)
                    XCTAssertLessThanOrEqual(measured.height, viewport.height + 0.5,
                        "sensor=\(sensorState), offline=\(offline), viewport=\(viewport), text=\(textSize)")
                    host.view.frame = CGRect(origin: .zero, size: viewport); host.view.layoutIfNeeded()
                    func countScrolls(_ view: UIView) -> Int {
                        (view is UIScrollView ? 1 : 0) + view.subviews.reduce(0) { $0 + countScrolls($1) }
                    }
                    XCTAssertEqual(countScrolls(host.view), 0)
                }
                if !offline && ["healthy", "unavailable"].contains(sensorState) {
                    for compact in [false, true] {
                        let viewport = compact ? CGSize(width: 162, height: 197) : CGSize(width: 375, height: 650)
                        for scheme in [ColorScheme.light, .dark] {
                            let renderer = ImageRenderer(content: content(dashboard, compact: compact)
                                .frame(width: viewport.width, height: viewport.height, alignment: .top)
                                .background(scheme == .dark ? Color.black : Color(.systemGroupedBackground))
                                .environment(\.colorScheme, scheme))
                            renderer.scale = 3
                            let attachment = XCTAttachment(image: try XCTUnwrap(renderer.uiImage))
                            attachment.name = "sensor-health-synthetic-\(compact ? "watch" : "phone")-\(sensorState)-\(scheme)"
                            attachment.lifetime = .keepAlways; add(attachment)
                        }
                    }
                }
            }
        }
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

    func testPhoneGlassHighContrastFitsWithoutScrolling() throws {
        let dashboard = try presentation(sensorState: "unavailable")
        for scheme in [ColorScheme.light, .dark] {
            for contrast in [UIAccessibilityContrast.normal, .high] {
                let view = content(dashboard, compact: false)
                    .environment(\.colorScheme, scheme)
                    .dynamicTypeSize(.accessibility3)
                let viewport = CGSize(width: 375, height: 650)
                let host = UIHostingController(rootView: view)
                host.traitOverrides.accessibilityContrast = contrast
                let extent = host.sizeThatFits(in: viewport)
                XCTAssertLessThanOrEqual(extent.width, viewport.width + 0.5)
                XCTAssertLessThanOrEqual(extent.height, viewport.height + 0.5)
                host.view.frame = CGRect(origin: .zero, size: viewport)
                host.view.layoutIfNeeded()
                func scrollCount(_ view: UIView) -> Int {
                    (view is UIScrollView ? 1 : 0) + view.subviews.reduce(0) { $0 + scrollCount($1) }
                }
                XCTAssertEqual(scrollCount(host.view), 0)
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
