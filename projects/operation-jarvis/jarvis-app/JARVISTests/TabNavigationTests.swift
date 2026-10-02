import XCTest
import SwiftUI
import UIKit
import JARVISKit
@testable import JARVIS

@MainActor
final class TabNavigationTests: XCTestCase {
    func testTitlesAndStableRoutes() {
        XCTAssertEqual(AppSection.allCases.map(\.title), ["JARVIS", "Home", "Terminal", "Jobs", "Settings"])
        XCTAssertEqual(AppSection(rawValue: "home"), .home)
        XCTAssertEqual(AppSection(rawValue: "system"), .system)
        XCTAssertEqual(AppSection(rawValue: "pi"), .pi)
        XCTAssertEqual(WatchDashboardPage.allCases, [.home, .terminal, .plugs, .jarvis, .jobs])
    }

    func testEveryPhoneSwipeAndNonWrappingBoundaries() {
        let cases: [(AppSection, AppSection?, AppSection?)] = [
            (.home, .system, nil), (.system, .pi, .home), (.pi, nil, nil),
            (.jobs, .settings, .pi), (.settings, nil, .jobs)
        ]
        for (page, left, right) in cases {
            XCTAssertEqual(page.swipeDestination(horizontal: -100, vertical: 0), left)
            XCTAssertEqual(page.swipeDestination(horizontal: 100, vertical: 0), right)
        }
    }

    func testShortVerticalDiagonalAndInvalidDragsAreIgnored() {
        for page in AppSection.allCases {
            for (x, y) in [(63.0, 0.0), (-63, 0), (100, 100), (-100, 100), (0, 200),
                           (90, 60), (.nan, 0), (.infinity, 0), (100, .nan)] {
                XCTAssertNil(page.swipeDestination(horizontal: x, vertical: y))
            }
        }
        XCTAssertEqual(AppSection.home.swipeDestination(horizontal: -64, vertical: 0), .system)
    }

    func testRecognizerIsDetachedOnTerminalAndBackgroundWithoutDuplication() {
        let controller = UIViewController()
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 390, height: 844))
        window.rootViewController = controller
        window.makeKeyAndVisible()
        defer { window.isHidden = true }
        let probe = TabSwipeNavigation.Probe(frame: controller.view.bounds)
        controller.view.addSubview(probe)
        let coordinator = TabSwipeNavigation.Coordinator()
        coordinator.configure(section: .home, active: true, select: { _ in })
        coordinator.mount(probe)
        coordinator.mount(probe)
        XCTAssertTrue(coordinator.pan.view === controller.view)
        XCTAssertEqual(controller.view.gestureRecognizers?.filter { $0 === coordinator.pan }.count, 1)
        coordinator.configure(section: .pi, active: true, select: { _ in })
        coordinator.mount(probe)
        XCTAssertNil(coordinator.pan.view, "Terminal must have no tab recognizer")
        coordinator.configure(section: .jobs, active: true, select: { _ in })
        coordinator.mount(probe)
        XCTAssertTrue(coordinator.pan.view === controller.view)
        coordinator.configure(section: .jobs, active: false, select: { _ in })
        coordinator.mount(probe)
        XCTAssertNil(coordinator.pan.view)
    }

    func testSwiftUIBridgeTracksRealTabHostAndSelectionChanges() async throws {
        let selection = NavigationFixtureSelection()
        let host = UIHostingController(rootView: NavigationFixture(selection: selection))
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 390, height: 844))
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer { window.isHidden = true }
        func tabRecognizers(_ view: UIView) -> [UIGestureRecognizer] {
            (view.gestureRecognizers ?? []).filter { $0.delegate is TabSwipeNavigation.Coordinator }
                + view.subviews.flatMap(tabRecognizers)
        }
        host.view.layoutIfNeeded()
        for _ in 0..<30 where tabRecognizers(host.view).isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertEqual(tabRecognizers(host.view).count, 1)
        selection.section = .pi
        for _ in 0..<30 where !tabRecognizers(host.view).isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(tabRecognizers(host.view).isEmpty)
        selection.section = .jobs
        for _ in 0..<30 where tabRecognizers(host.view).isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertEqual(tabRecognizers(host.view).count, 1)
    }

    func testNativeControlsAndHorizontalScrollingAreExcluded() {
        let root = UIView()
        for control in [UISlider(), UISwitch(), UITextField(), UITextView(), UITabBar()] as [UIView] {
            let child = UIView()
            root.addSubview(control)
            control.addSubview(child)
            XCTAssertTrue(TabSwipeNavigation.Coordinator.blocksTouch(child, root: root))
        }
        let scroll = UIScrollView(frame: CGRect(x: 0, y: 0, width: 300, height: 400))
        root.addSubview(scroll)
        scroll.contentSize = CGSize(width: 300, height: 1200)
        XCTAssertFalse(TabSwipeNavigation.Coordinator.blocksTouch(scroll, root: root))
        scroll.contentSize.width = 600
        XCTAssertTrue(TabSwipeNavigation.Coordinator.blocksTouch(scroll, root: root))
        scroll.contentSize.width = 300
        scroll.alwaysBounceHorizontal = true
        XCTAssertTrue(TabSwipeNavigation.Coordinator.blocksTouch(scroll, root: root))
    }

    func testPushedSettingsAndJobDetailsKeepTheirNavigationGestures() {
        let root = UIViewController()
        let navigation = UINavigationController(rootViewController: root)
        XCTAssertFalse(TabSwipeNavigation.Coordinator.isPushedContent(root.view))
        let details = UIViewController()
        navigation.pushViewController(details, animated: false)
        XCTAssertTrue(TabSwipeNavigation.Coordinator.isPushedContent(details.view))
    }

    func testModalSheetsAndAlertsBlockTabSwipes() async {
        let controller = UIViewController()
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 390, height: 844))
        window.rootViewController = controller
        window.makeKeyAndVisible()
        defer { window.isHidden = true }
        XCTAssertFalse(TabSwipeNavigation.Coordinator.hasOverlay(controller))
        await withCheckedContinuation { continuation in
            controller.present(UIViewController(), animated: false) { continuation.resume() }
        }
        XCTAssertTrue(TabSwipeNavigation.Coordinator.hasOverlay(controller))
        await withCheckedContinuation { continuation in
            controller.dismiss(animated: false) { continuation.resume() }
        }
        XCTAssertFalse(TabSwipeNavigation.Coordinator.hasOverlay(controller))
    }

    func testMovedHomeControlsFitSmallPhoneAndLargeText() throws {
        let defaults = UserDefaults(suiteName: "jarvis.home-layout.\(UUID().uuidString)")!
        let app = AppState(store: EndpointStore(defaults: defaults), historyEndpointProvider: { _ in nil })
        app.lastState = try JSONDecoder().decode(StateSnapshot.self, from: Data(#"""
        {"ok":true,"subsystems":{
          "plugs":{"ok":true,"stale":false,"plugs":{
            "family-room-light":{"ok":true,"isOn":true},"lamp":{"ok":true,"isOn":false},
            "pedalboard":{"ok":true,"isOn":false},"tv":{"ok":true,"isOn":true}}},
          "purifier":{"ok":true,"name":"Air Purifier","isOn":true,"mode":"auto","pm25":8,"filterLife":90}
        }}
        """#.utf8))
        app.connectionState = .connected
        // No scene activation, endpoint, transport or device commands in this fixture.
        app.setActiveSection(.system)
        for size in [DynamicTypeSize.large, .accessibility3] {
            let controls = HomeDeviceControls { _ in }.environmentObject(app).dynamicTypeSize(size)
            let host = UIHostingController(rootView: controls)
            let measured = host.sizeThatFits(in: CGSize(width: 288, height: 3000))
            XCTAssertLessThanOrEqual(measured.width, 288.5)
            XCTAssertGreaterThan(measured.height, 100)
            XCTAssertLessThan(measured.height, 3000)
            for scheme in [ColorScheme.light, .dark] {
                let view = VStack(spacing: 10) {
                    TabPageHeader(title: "Home")
                    SystemDashboardContent(presentation: .init(snapshot: app.lastState,
                        requestStartedAt: nil, isConnected: true), connectionLabel: "Synthetic fixture",
                        showsHeader: false, accent: .purple, warning: .orange, surface: JarvisPalette.surface)
                    controls
                }
                .padding(16).frame(width: 320)
                .background(Color(uiColor: .systemGroupedBackground))
                .environment(\.colorScheme, scheme)
                let renderer = ImageRenderer(content: view)
                renderer.scale = 2
                let attachment = XCTAttachment(image: try XCTUnwrap(renderer.uiImage))
                attachment.name = "home-navigation-fixture-\(size)-\(scheme)"
                attachment.lifetime = .keepAlways
                add(attachment)
            }
        }
    }

    func testPhoneDeviceCardsStayOnHomeWhileWatchRestoresDedicatedPages() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        func source(_ path: String) throws -> String {
            try String(contentsOf: root.appendingPathComponent(path), encoding: .utf8)
        }
        let jarvis = try source("JARVIS/Views/HomeView.swift")
        XCTAssertFalse(jarvis.contains("purifierSection("))
        XCTAssertFalse(jarvis.contains("plugsSection("))
        XCTAssertTrue(jarvis.contains("OMLXStatusCard"))
        let home = try source("JARVIS/Views/SystemView.swift")
        XCTAssertLessThan(try XCTUnwrap(home.range(of: "SystemDashboardContent")?.lowerBound),
                          try XCTUnwrap(home.range(of: "HomeDeviceControls")?.lowerBound))
        let controls = try source("JARVIS/Views/HomeDeviceControls.swift")
        XCTAssertLessThan(try XCTUnwrap(controls.range(of: "plugsSection(state)")?.lowerBound),
                          try XCTUnwrap(controls.range(of: "purifierSection(state)")?.lowerBound))
        XCTAssertTrue(controls.contains(".tabSwipeExcluded()"))
        let watch = try source("JARVISWatch/Views/WatchDashboardContent.swift")
        let homeBlock = try XCTUnwrap(watch.components(separatedBy: "private var resolvedHomePage:").last)
            .components(separatedBy: "private var resolvedOverviewPage:")[0]
        XCTAssertTrue(homeBlock.contains("WatchSystemHealthView"))
        XCTAssertFalse(homeBlock.contains("plugButton"))
        XCTAssertFalse(homeBlock.contains("purifierPanel"))
        XCTAssertTrue(homeBlock.contains("WatchSystemCrownViewport"))
        XCTAssertTrue(watch.contains("case .plugs:"))
        XCTAssertTrue(watch.contains("onAdvancePage: { selectedPage = .plugs }"))
        XCTAssertTrue(watch.contains("onPreviousPage: { selectedPage = .jarvis }"))
        XCTAssertTrue(watch.contains("ForEach(WatchDashboardPage.allCases"))
        let plugsBlock = try XCTUnwrap(watch.components(separatedBy: "private var resolvedPlugsPage:").last)
            .components(separatedBy: "private func plugButton(")[0]
        XCTAssertTrue(plugsBlock.contains("LazyVGrid(columns: gridColumns"))
        XCTAssertTrue(plugsBlock.contains("accessiblePlugButton(name)"))
        XCTAssertTrue(plugsBlock.contains("WatchSystemCrownViewport"))
        for (start, end) in [("private var overviewPage:", "private var purifierPanel:"),
                             ("private var accessibilityOverviewPage:", "private func accessiblePlugButton")] {
            let overview = try XCTUnwrap(watch.components(separatedBy: start).last)
                .components(separatedBy: end)[0]
            XCTAssertLessThan(try XCTUnwrap(overview.range(of: "purifierPanel")?.lowerBound),
                              try XCTUnwrap(overview.range(of: "codexQuotaPanel")?.lowerBound))
            XCTAssertLessThan(try XCTUnwrap(overview.range(of: "codexQuotaPanel")?.lowerBound),
                              try XCTUnwrap(overview.range(of: "omlxCard")?.lowerBound))
        }
        let entry = try XCTUnwrap(watch.components(separatedBy: ".onChange(of: selectedPage)").last)
            .components(separatedBy: ".onChange(of: showsSystemDetails)")[0]
        XCTAssertTrue(entry.contains("if page == .jarvis"))
        XCTAssertTrue(entry.contains("await model.refreshPurifierReadings()"))
        XCTAssertFalse(entry.contains("page == .home"))
        XCTAssertFalse(entry.contains("page == .plugs"))
        let terminal = try source("JARVISWatch/Views/WatchTerminalView.swift")
        XCTAssertTrue(terminal.contains("if destination == .home { onPreviousPage?() }"))
        XCTAssertTrue(terminal.contains("if destination == .plugs { onAdvancePage?() }"))
    }
}

@MainActor
private final class NavigationFixtureSelection: ObservableObject {
    @Published var section: AppSection = .home
}

private struct NavigationFixture: View {
    @ObservedObject var selection: NavigationFixtureSelection
    var body: some View {
        TabView(selection: $selection.section) {
            ForEach(AppSection.allCases, id: \.self) { page in
                NavigationStack {
                    ScrollView { Text(page.title).frame(maxWidth: .infinity, minHeight: 1000) }
                }
                .tag(page)
                .tabItem { Label(page.title, systemImage: "circle") }
            }
        }
        .background {
            TabSwipeNavigation(section: selection.section, active: true) { selection.section = $0 }
        }
    }
}
