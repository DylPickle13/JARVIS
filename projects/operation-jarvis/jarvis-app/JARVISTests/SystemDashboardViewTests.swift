import XCTest
import SwiftUI
import JARVISKit
@testable import JARVIS

@MainActor
final class SystemDashboardViewTests: XCTestCase {
    private func presentation(offline: Bool = false, includeExtraService: Bool = true, sensorState: String? = nil, deviceCoverage: Bool = false, includeMinecraft: Bool = false) throws -> SystemDashboardPresentation {
        let meta: [String: Any] = Dictionary(uniqueKeysWithValues:
            ["services", "pi", "plugs", "purifier", "network", "codexQuota", "claudeQuota"].map {
                ($0, ["ok": true, "stale": false, "ageSeconds": 10] as [String: Any])
            })
        var services: [String: Any] = [
            "runner": ["ok": true, "displayName": "Scheduled Jobs Runner", "description": "Runs due jobs into bounded private local history",
                "critical": true, "executionMode": "periodic", "loaded": true, "running": false, "lastExitCode": 0],
            "voice": ["ok": true, "displayName": "Room Audio Server", "critical": false, "running": false, "executionMode": "continuous"]]
        if includeExtraService {
            services["broken"] = ["ok": true, "displayName": "Required daemon", "critical": true, "running": false, "executionMode": "continuous"]
        }
        if includeMinecraft {
            services["minecraft-server"] = ["ok": true, "displayName": "Minecraft Server",
                "critical": false, "executionMode": "continuous", "running": true,
                "ready": true, "readinessReason": "java_listening", "sortOrder": 40]
            services["minecraft-jarvis-bot"] = ["ok": true, "displayName": "Minecraft JARVIS Bot",
                "critical": false, "executionMode": "continuous", "running": false, "sortOrder": 50]
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
        if deviceCoverage {
            let ids = ["keyboard-watcher", "keyboard", "mouse", "led-strip", "room-audio-mac",
                       "hub", "door-sensor", "motion-sensor", "sensor-reader", "front-doorbell",
                       "indoor-camera", "room-audio-pi", "family-room-tv", "family-room-speaker"]
            object["deviceHealth"] = ["version": 1, "scope": "device_check_coverage", "devices": ids.map { id in
                ["id": id, "name": id, "scope": "tcp_reachability", "expectation": "always",
                 "coverage": "background", "state": "available", "reason": "current",
                 "ageSeconds": 0, "lastAttemptAt": now.formatted(.iso8601),
                 "freshnessLimitSeconds": 150, "dependsOn": [], "blockedBy": [], "incidentOpen": false] as [String: Any]
            }]
        }
        let state = try JSONDecoder().decode(StateSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
        return .init(snapshot: state, requestStartedAt: now, isConnected: !offline, now: now)
    }

    /// The graph/exception design uses the existing parent scroll/Crown viewport.
    /// Bound its natural height per visible row instead of clipping it to the old chip-card height.
    private func assertTelemetryExtent(_ size: CGSize, width: CGFloat, compact: Bool,
                                       dashboard: SystemDashboardPresentation, textSize: DynamicTypeSize,
                                       file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertLessThanOrEqual(size.width, width + 0.5, file: file, line: line)
        XCTAssertTrue(size.height.isFinite && size.height > 0, file: file, line: line)
        let scale: CGFloat = textSize.isAccessibilitySize ? 4 : 1
        let base: CGFloat = compact ? 230 : 480
        let perRow: CGFloat = compact ? 48 : 66
        let budget = (base + perRow * CGFloat(dashboard.telemetryExceptions.count)) * scale
        XCTAssertLessThanOrEqual(size.height, budget, "Natural content must stay bounded and Crown-scrollable", file: file, line: line)
    }

    private func content(_ presentation: SystemDashboardPresentation, compact: Bool) -> some View {
        SystemDashboardContent(presentation: presentation, connectionLabel: "Fixture · no network",
            compact: compact, accent: .purple, warning: .orange, surface: Color(.secondarySystemGroupedBackground),
            connectionError: presentation.isConnected ? nil : "Fixture connection unavailable",
            onRefresh: compact ? nil : {}, onServices: {}, onMinecraft: {})
            .padding(8)
    }

    private func historyFixture(compact: Bool, tailIssue: Bool = false) async throws -> SystemHistoryModel {
        let window: SystemHistoryWindow = .hour
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
                let unavailable = (index % 13 == 0 || (tailIssue && index >= 55)) && !partial
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

    func testHealthViewsUseOnlyStateReadErrorsNotGeneralOperationErrors() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let phone = try String(contentsOf: root.appendingPathComponent("JARVIS/Views/SystemView.swift"), encoding: .utf8)
        let watch = try String(contentsOf: root.appendingPathComponent("JARVISWatch/Views/WatchSystemHealthView.swift"), encoding: .utf8)
        XCTAssertTrue(phone.contains("connectionError: app.stateErrorMessage,"))
        XCTAssertFalse(phone.contains("app.stateErrorMessage ?? app.errorMessage"))
        XCTAssertTrue(watch.contains("connectionError: model.stateErrorMessage,"))
        XCTAssertFalse(watch.contains("connectionError: model.errorMessage,"))
        let model = try String(contentsOf: root.appendingPathComponent("JARVISWatch/Views/WatchConnectView.swift"), encoding: .utf8)
        XCTAssertTrue(model.contains("stateErrorMessage = errorMessage"), "Real direct/relay state failures remain represented")
        XCTAssertTrue(model.contains("self.stateErrorMessage = nil"), "Accepted phone snapshots clear the state failure")
    }

    func testHealthCardOmitsRedundantTopHeaderButRetainsRealFailureNotice() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let source = try String(contentsOf: root.appendingPathComponent("JARVISKit/Sources/JARVISKit/SystemDashboardContent.swift"), encoding: .utf8)
        XCTAssertFalse(source.contains("Text(\"SYSTEM / HEALTH\")"))
        XCTAssertFalse(source.contains("Text(\"CACHED\")"))
        XCTAssertTrue(source.contains("State request failed"), "Do not conceal real read errors to make the card green")
        XCTAssertTrue(source.contains("not live connectivity or home security"), "Cached-evidence accessibility explanation remains")
    }

    func testTelemetryFiltersHealthyMarkersButRetainsEveryException() throws {
        let healthy = try presentation(includeExtraService: false, sensorState: "healthy", deviceCoverage: true, includeMinecraft: true)
        XCTAssertEqual(healthy.state, .healthy)
        XCTAssertTrue(healthy.telemetryExceptions.isEmpty)
        let issue = try presentation(sensorState: "unavailable", deviceCoverage: true, includeMinecraft: true)
        XCTAssertEqual(issue.state, .issue)
        XCTAssertEqual(issue.telemetryExceptions.map(\.id), issue.visualGroups.filter { $0.state != .healthy }.map(\.id))
        XCTAssertFalse(issue.telemetryExceptions.contains { $0.state == .healthy })
        let offline = try presentation(offline: true, deviceCoverage: true, includeMinecraft: true)
        XCTAssertEqual(offline.telemetryExceptions.count, offline.visualGroups.count)
    }

    func testTelemetryRendersSelectedDesignWithRealHistoryOnPhoneAndWatch() async throws {
        for issue in [false, true] {
            let dashboard = try presentation(includeExtraService: issue, sensorState: "healthy", deviceCoverage: true, includeMinecraft: true)
            for compact in [false, true] {
                let history = try await historyFixture(compact: compact, tailIssue: issue)
                let width: CGFloat = compact ? 162 : 375
                for scheme in [ColorScheme.light, .dark] {
                    let view = SystemDashboardContent(presentation: dashboard, connectionLabel: "Offline fixture; no device reads",
                        compact: compact, showsHeader: false, accent: .cyan, warning: .orange, surface: .black,
                        historyModel: history, onServices: {}, onMinecraft: {}, active: false)
                        .environment(\.colorScheme, scheme)
                    let host = UIHostingController(rootView: view)
                    let size = host.sizeThatFits(in: CGSize(width: width, height: 10000))
                    XCTAssertLessThanOrEqual(size.width, width + 0.5)
                    XCTAssertGreaterThan(size.height, 100)
                    XCTAssertLessThan(size.height, compact ? 500 : 900)
                    if compact && !issue { XCTAssertLessThanOrEqual(size.height, 197, "Normal healthy card fits the smallest Watch viewport") }
                    let renderer = ImageRenderer(content: view.frame(width: width)
                        .background(scheme == .dark ? Color.black : Color.white))
                    renderer.scale = 3
                    let attachment = XCTAttachment(image: try XCTUnwrap(renderer.uiImage))
                    attachment.name = "telemetry-\(compact ? "watch" : "phone")-\(issue ? "issue" : "healthy")-\(scheme)"
                    attachment.lifetime = .keepAlways; add(attachment)
                }
                history.configure(.init(endpoint: nil, surface: compact ? .watch : .phone, visible: false, interactive: false, connected: false))
            }
        }
    }

    func testVisualCardDelegatesOnlyReadOnlyServicesAndMinecraftAndKeepsPlatformInputOwnership() throws {
        let appRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let source = try String(contentsOf: appRoot.appendingPathComponent("JARVISKit/Sources/JARVISKit/SystemDashboardContent.swift"), encoding: .utf8)
        for forbidden in [".sheet(", "selectedDetail", "ScrollView", ".onTapGesture", ".gesture(", "digitalCrownRotation"] {
            XCTAssertFalse(source.contains(forbidden), forbidden)
        }
        XCTAssertEqual(source.components(separatedBy: "Button(").count - 1, 2,
                       "Direct exception route and optional iPhone refresh only; no separate chooser")
        XCTAssertTrue(source.contains("onServices?()"))
        XCTAssertTrue(source.contains("onMinecraft?()"))
        XCTAssertFalse(source.contains("onDetails"))
        XCTAssertTrue(source.contains("system-minecraft-button"))
        let services = try String(contentsOf: appRoot.appendingPathComponent("JARVISKit/Sources/JARVISKit/SystemServicesContent.swift"), encoding: .utf8)
        for forbidden in ["Button(", "Task {", "client.", "serviceAction", "Timer("] {
            XCTAssertFalse(services.contains(forbidden), forbidden)
        }
        XCTAssertTrue(source.contains("if !compact"))
        XCTAssertTrue(source.contains("group.accessibilityText + serviceEvidence(group)"))
        XCTAssertTrue(source.contains("presentation.telemetryExceptions"))
        XCTAssertFalse(source.contains("system-details-menu"))
        XCTAssertFalse(source.contains("ellipsis"))
        XCTAssertTrue(source.contains(".jarvisGlassSurface(surface, in: RoundedRectangle"))
        XCTAssertFalse(source.contains("Color(red: 0.035, green: 0.085, blue: 0.13)"))
        XCTAssertFalse(source.contains(".fill(LinearGradient"), "No blue/status wash over the standard themed surface")
        for path in ["JARVIS/Views/SystemView.swift", "JARVISWatch/Views/WatchSystemHealthView.swift"] {
            let host = try String(contentsOf: appRoot.appendingPathComponent(path), encoding: .utf8)
            XCTAssertFalse(host.contains("showsDetailChoices"))
            XCTAssertFalse(host.contains("confirmationDialog(\"Read-only system details\""))
            XCTAssertTrue(host.contains(".sheet(item: $serviceScope)"))
            XCTAssertTrue(host.contains("onServices: { serviceScope = .services }"))
            XCTAssertTrue(host.contains("onMinecraft: { serviceScope = .minecraft }"))
        }
        XCTAssertFalse(source.contains("checkmark"))
        let chart = try String(contentsOf: appRoot.appendingPathComponent("JARVISKit/Sources/JARVISKit/SystemTelemetryChart.swift"), encoding: .utf8)
        XCTAssertTrue(chart.contains("#if os(iOS)"))
        XCTAssertTrue(chart.contains("accessibilityAdjustableAction"))
        XCTAssertTrue(chart.contains("SystemTelemetryWindow.isSolid"))
    }

    func testWatchHistoryAvailabilityDoesNotFollowRelaySnapshotProvenance() throws {
        let appRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let source = try String(contentsOf: appRoot.appendingPathComponent("JARVISWatch/Views/WatchConnectView.swift"), encoding: .utf8)
        XCTAssertTrue(source.contains("historyDirectConnection.allowsPolling(at: store.endpointURL)"))
        XCTAssertFalse(source.contains("connected: connectionState == .connected && !isViaPhone"))
        XCTAssertTrue(source.contains("historyDirectConnection.receivedDirectState(from: endpoint)"))
        XCTAssertTrue(source.contains("acceptDirectState(resolved.state, from: resolved.endpointURL)"))
        XCTAssertTrue(source.contains("if self.store.endpointURL != url { self.historyDirectConnection.invalidate() }"))
        for marker in ["func sceneDidEnterBackground()", "private func useRelayOrCache("] {
            let body = try XCTUnwrap(source.components(separatedBy: marker).last).components(separatedBy: "\n    func ")[0]
            XCTAssertTrue(body.contains("historyDirectConnection.invalidate()"))
        }
        let relay = try XCTUnwrap(source.components(separatedBy: "nonisolated func watchBridgeDidReceiveState(_").last)
            .components(separatedBy: "nonisolated func watchBridgeDidReceivePlugCommand")[0]
        XCTAssertTrue(relay.contains("self.isViaPhone = true"), "Control routing still knows state came from the phone")
        XCTAssertFalse(relay.contains("historyDirectConnection.invalidate()"))
        XCTAssertFalse(relay.contains("receivedDirectState"), "Relay cannot establish direct history availability")
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
                assertTelemetryExtent(extent, width: viewport.width, compact: compact, dashboard: dashboard, textSize: size)
            }
            for scheme in [ColorScheme.light, .dark] {
                let renderer = ImageRenderer(content: view.frame(width: viewport.width)
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

    func testMinecraftDetailFitsPhoneAndWatchWidthAndGrowsForCrownOverflow() throws {
        for offline in [false, true] {
            let dashboard = try presentation(offline: offline, includeExtraService: false, includeMinecraft: true)
            XCTAssertEqual(dashboard.services.count, 4)
            for (compact, width) in [(true, CGFloat(162)), (false, CGFloat(320))] {
                for size in [DynamicTypeSize.large, .accessibility3] {
                    let view = SystemServicesContent(presentation: dashboard, scope: .minecraft, compact: compact,
                        accent: .purple, warning: .orange, surface: Color(.secondarySystemGroupedBackground))
                        .dynamicTypeSize(size)
                    let host = UIHostingController(rootView: view)
                    let measured = host.sizeThatFits(in: CGSize(width: width, height: 10000))
                    XCTAssertLessThanOrEqual(measured.width, width + 0.5)
                    XCTAssertGreaterThan(measured.height, 197, "Detail content must overflow, not silently drop services")
                    let renderer = ImageRenderer(content: view.frame(width: width))
                    renderer.scale = 2
                    let attachment = XCTAttachment(image: try XCTUnwrap(renderer.uiImage))
                    attachment.name = "minecraft-service-list-synthetic-\(compact)-\(offline)-\(size)"
                    attachment.lifetime = .keepAlways; add(attachment)
                }
            }
        }
    }

    func testDedicatedMinecraftCheckFitsWidthAndAllowsParentOverflow() throws {
        for coverage in [false, true] {
            for offline in [false, true] {
                let dashboard = try presentation(offline: offline, includeExtraService: false,
                    sensorState: "healthy", deviceCoverage: coverage, includeMinecraft: true)
                XCTAssertEqual(dashboard.visualGroups.map(\.id), coverage
                    ? ["services", "minecraft", "pi", "network", "computer", "security", "devices"]
                    : ["services", "minecraft", "pi", "network", "devices", "security"])
                XCTAssertTrue(dashboard.visualGroups.contains { $0.id == "minecraft" })
                for (compact, viewport) in [(true, CGSize(width: 162, height: 197)),
                                           (true, CGSize(width: 184, height: 224)),
                                           (false, CGSize(width: 320, height: 450)),
                                           (false, CGSize(width: 750, height: 270))] {
                    for textSize in [DynamicTypeSize.large, .accessibility3] {
                        let view = content(dashboard, compact: compact).dynamicTypeSize(textSize)
                        let host = UIHostingController(rootView: view)
                        let measured = host.sizeThatFits(in: viewport)
                        XCTAssertLessThanOrEqual(measured.width, viewport.width + 0.5)
                        assertTelemetryExtent(measured, width: viewport.width, compact: compact, dashboard: dashboard, textSize: textSize)
                        host.view.frame = CGRect(origin: .zero, size: viewport); host.view.layoutIfNeeded()
                        func scrolls(_ view: UIView) -> Int {
                            (view is UIScrollView ? 1 : 0) + view.subviews.reduce(0) { $0 + scrolls($1) }
                        }
                        XCTAssertEqual(scrolls(host.view), 0)
                        if coverage && !offline {
                            let renderer = ImageRenderer(content: view.frame(width: viewport.width)
                                .background(Color.black).environment(\.colorScheme, .dark))
                            renderer.scale = 3
                            let attachment = XCTAttachment(image: try XCTUnwrap(renderer.uiImage))
                            attachment.name = "dedicated-minecraft-check-\(compact)-\(Int(viewport.width))-\(textSize)"
                            attachment.lifetime = .keepAlways; add(attachment)
                        }
                    }
                }
            }
        }
    }

    func testDedicatedServicesAndMinecraftSheetsDoNotDuplicateRowsAndFitDetailWidths() throws {
        let dashboard = try presentation(includeMinecraft: true)
        let services = SystemServicesScope.services.services(in: dashboard)
        let minecraft = SystemServicesScope.minecraft.services(in: dashboard)
        XCTAssertEqual(minecraft.map(\.id), SystemDashboardPresentation.minecraftServiceIDs)
        XCTAssertEqual(services.count, 3)
        XCTAssertEqual(dashboard.services.count, 5)
        XCTAssertTrue(Set(services.map(\.id)).isDisjoint(with: minecraft.map(\.id)))
        for scope in [SystemServicesScope.services, .minecraft] {
            for compact in [false, true] {
                for textSize in [DynamicTypeSize.large, .accessibility3] {
                    let width: CGFloat = compact ? 162 : 320
                    let view = SystemServicesContent(presentation: dashboard, scope: scope,
                        compact: compact, accent: .purple, warning: .orange, surface: Color(.secondarySystemGroupedBackground))
                        .dynamicTypeSize(textSize)
                    let host = UIHostingController(rootView: view)
                    let measured = host.sizeThatFits(in: CGSize(width: width, height: 10000))
                    XCTAssertLessThanOrEqual(measured.width, width + 0.5)
                    XCTAssertGreaterThan(measured.height, 100)
                    let renderer = ImageRenderer(content: view.frame(width: width))
                    renderer.scale = 2
                    let attachment = XCTAttachment(image: try XCTUnwrap(renderer.uiImage))
                    attachment.name = "disjoint-service-lists-\(scope)-\(compact)-\(textSize)"
                    attachment.lifetime = .keepAlways; add(attachment)
                }
            }
        }
    }

    func testDefaultServicesContentNeverRepeatsMinecraftRows() throws {
        let dashboard = try presentation(includeMinecraft: true)
        let view = SystemServicesContent(presentation: dashboard,
            accent: .purple, warning: .orange, surface: Color(.secondarySystemGroupedBackground))
        XCTAssertEqual(view.scope, .services)
        XCTAssertEqual(view.scope.services(in: dashboard).map(\.id), dashboard.backgroundServices.map(\.id))
        XCTAssertFalse(view.scope.services(in: dashboard).contains {
            SystemDashboardPresentation.minecraftServiceIDs.contains($0.id)
        })
    }

    func testOwnerDeviceGroupsFitPhoneAndWatch() throws {
        for offline in [false, true] {
            let dashboard = try presentation(offline: offline, includeExtraService: false, sensorState: "healthy", deviceCoverage: true)
            XCTAssertEqual(dashboard.visualGroups.map(\.id),
                ["services", "pi", "network", "computer", "security", "devices"])
            for (compact, viewport) in [(true, CGSize(width: 162, height: 197)),
                                        (false, CGSize(width: 320, height: 450)),
                                        (false, CGSize(width: 750, height: 270))] {
                for textSize in [DynamicTypeSize.large, .accessibility3] {
                    let host = UIHostingController(rootView: content(dashboard, compact: compact).dynamicTypeSize(textSize))
                    let measured = host.sizeThatFits(in: viewport)
                    assertTelemetryExtent(measured, width: viewport.width, compact: compact, dashboard: dashboard, textSize: textSize)
                }
                if !offline {
                    let renderer = ImageRenderer(content: content(dashboard, compact: compact)
                        .frame(width: viewport.width, height: viewport.height, alignment: .top)
                        .background(Color.black).environment(\.colorScheme, .dark))
                    renderer.scale = 3
                    let image = try XCTUnwrap(renderer.uiImage)
                    let attachment = XCTAttachment(image: image)
                    attachment.name = "owner-system-groups-\(Int(viewport.width))-\(compact)"
                    attachment.lifetime = .keepAlways; add(attachment)
                }
            }
        }
    }

    func testSensorInclusiveOverviewFitsPhoneAndWatchWithoutAddingScrollOrDroppingSensor() throws {
        for sensorState in ["healthy", "unavailable", "unknown", "inactive"] {
            for offline in [false, true] {
                let dashboard = try presentation(offline: offline, includeExtraService: false, sensorState: sensorState)
                XCTAssertEqual(dashboard.compactSubsystemRows.count, 7)
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
                    assertTelemetryExtent(measured, width: viewport.width, compact: compact, dashboard: dashboard, textSize: textSize)
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
            assertTelemetryExtent(measured, width: 162, compact: true, dashboard: dashboard, textSize: size)
        }
    }

    func testPhoneDashboardFitsPortraitLandscapeWidthsAndPreservesLargeText() throws {
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
                assertTelemetryExtent(measured, width: viewport.width, compact: false, dashboard: dashboard, textSize: textSize)
            }
        }
    }

    func testPhoneHighContrastFitsWidthWithoutOwningParentScrolling() throws {
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
                assertTelemetryExtent(extent, width: viewport.width, compact: false, dashboard: dashboard, textSize: .accessibility3)
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
