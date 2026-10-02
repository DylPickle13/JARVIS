import XCTest
import SwiftUI
import JARVISKit
@testable import JARVIS

@MainActor
final class SettingsLayoutTests: XCTestCase {
    @MainActor
    private struct Fixture {
        let defaults = UserDefaults(suiteName: "settings-layout-\(UUID().uuidString)")!
        let app: AppState
        let ssh: PiTerminalSettings
        let watch: WatchTerminalProvisioningSettings
        let terminal: PiTerminalController

        init() {
            defaults.set("http://192.168.1.100:8790", forKey: "jarvis.endpoint.url")
            defaults.set("wss://mac-mini-64.example.ts.net:8791/terminal", forKey: JARVISTerminalConfigurationStore.endpointKey)
            app = AppState(store: EndpointStore(defaults: defaults), preferences: defaults)
            ssh = PiTerminalSettings(defaults: defaults)
            watch = WatchTerminalProvisioningSettings(defaults: defaults)
            terminal = PiTerminalController(settings: ssh)
        }

        func overview(size: DynamicTypeSize = .large) -> some View {
            SettingsDashboardContent(sshSettings: ssh, watchProvisioning: watch)
                .environmentObject(app).environmentObject(terminal)
                .environmentObject(PushNotificationCoordinator.shared)
                .environment(\.dynamicTypeSize, size)
                .padding(.horizontal, 16).padding(.bottom, 12)
        }

        func editor(_ destination: SettingsDestination) -> some View {
            SettingsDetailView(destination: destination, sshSettings: ssh, watchProvisioning: watch)
                .environmentObject(app).environmentObject(terminal)
                .environmentObject(PushNotificationCoordinator.shared)
        }
    }

    private func mount<V: View>(_ view: V) async throws -> (UIWindow, UIHostingController<V>) {
        let host = UIHostingController(rootView: view)
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = host
        window.makeKeyAndVisible()
        host.view.layoutIfNeeded()
        try await Task.sleep(for: .milliseconds(180))
        return (window, host)
    }

    private func descendants(_ view: UIView) -> [UIView] { [view] + view.subviews.flatMap(descendants) }

    func testOverviewSeparatesNavigationFromEditingAndKeepsSafetyGuards() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let overview = try String(contentsOf: root.appendingPathComponent("JARVIS/Views/SettingsView.swift"), encoding: .utf8)
        let editor = try String(contentsOf: root.appendingPathComponent("JARVIS/Views/SettingsDetailView.swift"), encoding: .utf8)
        for forbidden in ["TextField(", "SecureField(", "passwordForEditing()", "DisclosureGroup"] {
            XCTAssertFalse(overview.contains(forbidden), forbidden)
        }
        XCTAssertEqual(overview.components(separatedBy: "ScrollView {").count - 1, 1)
        XCTAssertEqual(editor.components(separatedBy: "ScrollView {").count - 1, 1)
        XCTAssertTrue(overview.contains("SettingsSummaryGrid(columns:"))
        XCTAssertTrue(overview.contains("SettingsInlineCard(\"Diagnostics & Maintenance\""))
        XCTAssertTrue(overview.contains(".navigationDestination(for: SettingsDestination.self)"))
        XCTAssertTrue(overview.contains("if let accessory { accessory }"), "Toggle must be outside NavigationLink")
        XCTAssertFalse(editor.contains(".sheet("))
        for marker in ["app.clearConnection()", "sshSettings.save(", "forgetTrustedHost(",
                       "WatchBridge.shared.publishTerminalConfiguration(configuration)",
                       "retryPendingRegistrations()", "refreshHostStatus()", "secondaryButton: .cancel()"] {
            XCTAssertTrue(editor.contains(marker), marker)
        }
        for marker in ["notifications.setEnabled(enabled)", "maintenance.canRetrySubmission",
                       "maintenance.operationID != nil", "trustedHostKey:", "confirmRestart = true"] {
            XCTAssertTrue(overview.contains(marker), marker)
        }
    }

    func testNormalSettingsFitIPhone11PortraitContentArea() async throws {
        let fixture = Fixture()
        let natural = UIHostingController(rootView: fixture.overview())
        let size = natural.sizeThatFits(in: CGSize(width: 414, height: 10000))
        print("SETTINGS_GRID_NATURAL_SIZE \(size)")
        XCTAssertLessThanOrEqual(size.height, 740)
        let (window, host) = try await mount(TabView(selection: .constant(4)) {
            ForEach(0..<4) { index in
                Text("Fixture").tabItem { Label(["JARVIS", "Home", "Terminal", "Jobs"][index], systemImage: "circle") }.tag(index)
            }
            NavigationStack {
                ScrollView { fixture.overview() }
                    .background(JarvisBackdrop()).toolbar(.hidden, for: .navigationBar)
                    .navigationDestination(for: SettingsDestination.self) { fixture.editor($0) }
            }
            .tabItem { Label("Settings", systemImage: "gearshape") }.tag(4)
        }.preferredColorScheme(.dark).tint(JarvisPalette.accent))
        defer { window.isHidden = true }
        let views = descendants(host.view)
        XCTAssertEqual(views.compactMap { $0 as? UITextField }.count, 0, "No login fields may be mounted on the overview")
        let page = try XCTUnwrap(views.compactMap { $0 as? UIScrollView }.first { $0.contentSize.height > 400 })
        let available = page.bounds.height - page.adjustedContentInset.top - page.adjustedContentInset.bottom
        print("SETTINGS_GRID_CONTENT \(page.contentSize.height) AVAILABLE \(available)")
        XCTAssertLessThanOrEqual(page.contentSize.height, available + 1)
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
        let attachment = XCTAttachment(image: image)
        attachment.name = "balanced-settings-grid"
        attachment.lifetime = .keepAlways
        add(attachment)
        try XCTUnwrap(image.pngData()).write(to: URL(fileURLWithPath: "/tmp/jarvis-balanced-settings.png"))
    }

    func testAllFourCardsHaveIdenticalMeasuredBoundsEvenWithLongContent() async throws {
        let measurements = SettingsCardMeasurements()
        let (window, _) = try await mount(NavigationStack {
            ScrollView {
                SettingsSummaryGrid(columns: 2) {
                    ForEach(Array(SettingsDestination.allCases.enumerated()), id: \.offset) { index, destination in
                        SettingsSummaryCard(destination: destination) {
                            Text(index == 2 ? String(repeating: "Long host name ", count: 10) : "Configured").font(.caption)
                        }
                        .background(GeometryReader { proxy in
                            Color.clear.preference(key: SettingsCardFrames.self,
                                value: [index: proxy.frame(in: .named("settings-grid"))])
                        })
                    }
                }
                .coordinateSpace(name: "settings-grid")
                .onPreferenceChange(SettingsCardFrames.self) { measurements.frames = $0 }
                .padding(16)
            }
        })
        defer { window.isHidden = true }
        XCTAssertEqual(measurements.frames.count, 4)
        let first = try XCTUnwrap(measurements.frames[0])
        for frame in measurements.frames.values {
            XCTAssertEqual(frame.width, first.width, accuracy: 0.5)
            XCTAssertEqual(frame.height, first.height, accuracy: 0.5)
        }
        XCTAssertEqual(measurements.frames[0]?.minY, measurements.frames[1]?.minY)
        XCTAssertEqual(measurements.frames[2]?.minY, measurements.frames[3]?.minY)
    }

    func testAlertsToggleDoesNotNavigate() async throws {
        let routes = SettingsTestRoutes()
        let enabled = SettingsTestToggle()
        let (window, host) = try await mount(NavigationStack(path: Binding(get: { routes.path }, set: { routes.path = $0 })) {
            SettingsSummaryCard(destination: .notifications, accessory: AnyView(
                Toggle("Alerts", isOn: Binding(get: { enabled.value }, set: { enabled.value = $0 }))
            )) { Text("Registration status") }
            .frame(width: 186, height: 190)
            .navigationDestination(for: SettingsDestination.self) { Text($0.title) }
        })
        defer { window.isHidden = true }
        let toggle = try XCTUnwrap(descendants(host.view).compactMap { $0 as? UISwitch }.first)
        toggle.setOn(true, animated: false)
        toggle.sendActions(for: .valueChanged)
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertTrue(enabled.value)
        XCTAssertTrue(routes.path.isEmpty, "Using Alerts must not open notification details")
    }

    func testEachEditorMountsOnlyItsOwnFieldsAndReturnsToOverview() async throws {
        let fixture = Fixture()
        let routes = SettingsTestRoutes()
        let (window, host) = try await mount(SettingsNavigationFixture(fixture: fixture, routes: routes))
        defer { window.isHidden = true }
        for (destination, count) in [(SettingsDestination.connection, 1), (.iphoneTerminal, 4), (.watchTerminal, 1), (.notifications, 0)] {
            routes.path = [destination]
            try await Task.sleep(for: .milliseconds(550))
            XCTAssertEqual(descendants(host.view).compactMap { $0 as? UITextField }.count, count, destination.title)
            routes.path = []
            try await Task.sleep(for: .milliseconds(550))
            XCTAssertEqual(descendants(host.view).compactMap { $0 as? UITextField }.count, 0)
        }
        XCTAssertEqual(fixture.ssh.host, "")
        XCTAssertEqual(fixture.defaults.string(forKey: "jarvis.endpoint.url"), "http://192.168.1.100:8790")
    }

    func testInvalidSavesRemainVisibleInEditorsWithoutChangingCredentials() async throws {
        let fixture = Fixture()
        for destination in [SettingsDestination.iphoneTerminal, .watchTerminal] {
            let (window, host) = try await mount(NavigationStack { fixture.editor(destination) })
            defer { window.isHidden = true }
            let scroll = try XCTUnwrap(descendants(host.view).compactMap { $0 as? UIScrollView }.first)
            let before = scroll.contentSize.height
            let hadPassword = fixture.ssh.hasPassword
            if destination == .iphoneTerminal {
                XCTAssertFalse(fixture.ssh.save(host: "invalid", portText: "0", username: "", password: ""))
                XCTAssertNotNil(fixture.ssh.credentialError)
            } else {
                XCTAssertFalse(fixture.watch.save(provisioningCode: "invalid"))
                XCTAssertNotNil(fixture.watch.errorMessage)
            }
            try await Task.sleep(for: .milliseconds(150))
            XCTAssertGreaterThan(scroll.contentSize.height, before)
            XCTAssertEqual(fixture.ssh.hasPassword, hadPassword)
            XCTAssertEqual(fixture.ssh.host, "")
        }
    }

    func testAccessibilityStacksCardsAndExpandsWithoutShrinking() {
        let fixture = Fixture()
        let normal = UIHostingController(rootView: fixture.overview())
        let accessible = UIHostingController(rootView: fixture.overview(size: .accessibility3))
        let proposal = CGSize(width: 375, height: 20000)
        XCTAssertGreaterThan(accessible.sizeThatFits(in: proposal).height, normal.sizeThatFits(in: proposal).height)
        XCTAssertEqual(SettingsView.columnCount(for: .accessibility3), 1)
    }

    func testBridgeSummaryUsesHostAndPortNotPathOrCredentials() {
        XCTAssertEqual(SettingsDashboardContent.bridgeHost("wss://example.test:8791/terminal"), "example.test:8791")
        XCTAssertEqual(SettingsDashboardContent.bridgeHost(""), "Not provisioned")
        XCTAssertEqual(SettingsDashboardContent.bridgeHost("wss://user:secret@example.test/path?token=private"), "example.test")
    }

    private struct SettingsNavigationFixture: View {
        let fixture: Fixture
        @ObservedObject var routes: SettingsTestRoutes
        var body: some View {
            NavigationStack(path: $routes.path) {
                ScrollView { fixture.overview() }
                    .navigationDestination(for: SettingsDestination.self) { fixture.editor($0) }
            }
        }
    }
}

@MainActor
private final class SettingsTestRoutes: ObservableObject {
    @Published var path: [SettingsDestination] = []
}

@MainActor
private final class SettingsTestToggle {
    var value = false
}

@MainActor
private final class SettingsCardMeasurements {
    var frames: [Int: CGRect] = [:]
}

private struct SettingsCardFrames: PreferenceKey {
    static var defaultValue: [Int: CGRect] { [:] }
    static func reduce(value: inout [Int: CGRect], nextValue: () -> [Int: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}
