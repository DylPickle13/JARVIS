import XCTest
import SwiftUI
import UIKit
import JARVISKit
@testable import JARVIS

@MainActor
final class TabPageAnimationTests: XCTestCase {
    private func fixture(reduceMotion: Bool = false) async throws -> (UIWindow, UITabBarController, TabSwipeNavigation.Coordinator) {
        let tabs = UITabBarController()
        tabs.viewControllers = [UIColor.red, .blue].enumerated().map { index, color in
            let controller = UIViewController()
            controller.view.backgroundColor = color
            controller.tabBarItem = UITabBarItem(title: "Fixture \(index)", image: nil, tag: index)
            return controller
        }
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = tabs
        window.makeKeyAndVisible()
        tabs.view.layoutIfNeeded()
        try await Task.sleep(for: .milliseconds(100)) // render a real frame before snapshotting
        let probe = TabSwipeNavigation.Probe(frame: tabs.view.bounds)
        tabs.view.addSubview(probe)
        let coordinator = TabSwipeNavigation.Coordinator()
        coordinator.configure(section: .home, active: true, reduceMotion: reduceMotion) { [weak coordinator] page in
            tabs.selectedIndex = page == .home ? 0 : 1
            coordinator?.configure(section: page, active: true, reduceMotion: reduceMotion, select: { _ in })
        }
        coordinator.mount(probe)
        return (window, tabs, coordinator)
    }

    func testCommittedSwipeAnimatesButKeepsNativeControllersAndTabBar() async throws {
        let (window, tabs, coordinator) = try await fixture()
        defer { coordinator.pageAnimator.cancel(); window.isHidden = true }
        let controllers = tabs.viewControllers!
        let bar = tabs.tabBar
        let delegate = tabs.delegate
        let barFrame = bar.frame
        coordinator.selectFromSwipe(.system)
        XCTAssertEqual(tabs.selectedIndex, 1, "Routing must not wait for the animation")
        XCTAssertTrue(coordinator.pageAnimator.isInFlight)
        for _ in 0..<20 where !coordinator.pageAnimator.isAnimating { try await Task.sleep(for: .milliseconds(5)) }
        XCTAssertTrue(coordinator.pageAnimator.isAnimating)
        XCTAssertEqual(controllers[1].view.alpha, 1, "Live pages must not multiply UIKit's own crossfade")
        XCTAssertEqual(controllers[1].view.transform, .identity)
        XCTAssertTrue(tabs.tabBar === bar)
        XCTAssertEqual(bar.frame, barFrame)
        XCTAssertTrue(tabs.delegate === delegate)
        for (old, new) in zip(controllers, tabs.viewControllers!) { XCTAssertTrue(old === new) }
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertFalse(coordinator.pageAnimator.isInFlight)
        XCTAssertEqual(controllers[1].view.alpha, 1)
        XCTAssertEqual(controllers[1].view.transform, .identity)
    }

    func testReducedMotionRoutesImmediatelyWithoutSnapshotAnimation() async throws {
        let (window, tabs, coordinator) = try await fixture(reduceMotion: true)
        defer { window.isHidden = true }
        coordinator.selectFromSwipe(.system)
        XCTAssertEqual(tabs.selectedIndex, 1)
        XCTAssertFalse(coordinator.pageAnimator.isInFlight)
        XCTAssertEqual(tabs.selectedViewController?.view.alpha, 1)
    }

    func testBackgroundAndReduceMotionChangesCancelAndRestoreContent() async throws {
        for reduceMotion in [false, true] {
            let (window, tabs, coordinator) = try await fixture()
            defer { coordinator.pageAnimator.cancel(); window.isHidden = true }
            coordinator.selectFromSwipe(.system)
            try await Task.sleep(for: .milliseconds(40))
            XCTAssertTrue(coordinator.pageAnimator.isInFlight)
            coordinator.configure(section: .system, active: reduceMotion, reduceMotion: reduceMotion, select: { _ in })
            XCTAssertFalse(coordinator.pageAnimator.isInFlight)
            XCTAssertEqual(tabs.selectedViewController?.view.alpha, 1)
            XCTAssertEqual(tabs.selectedViewController?.view.transform, .identity)
        }
    }

    func testNewRouteCancelsPendingAnimationWithoutRestoringOldSelection() async throws {
        let (window, tabs, coordinator) = try await fixture()
        defer { coordinator.pageAnimator.cancel(); window.isHidden = true }
        coordinator.selectFromSwipe(.system)
        coordinator.configure(section: .pi, active: true, select: { _ in })
        try await Task.sleep(for: .milliseconds(80))
        XCTAssertEqual(coordinator.section, .pi)
        XCTAssertFalse(coordinator.pageAnimator.isInFlight)
        XCTAssertNil(coordinator.pan.view)
        XCTAssertEqual(tabs.selectedViewController?.view.alpha, 1)
    }

    func testRotationCancelsAndRapidSwipesDoNotStack() async throws {
        let (window, tabs, coordinator) = try await fixture()
        defer { coordinator.pageAnimator.cancel(); window.isHidden = true }
        coordinator.selectFromSwipe(.system)
        coordinator.selectFromSwipe(.home)
        XCTAssertEqual(coordinator.section, .system)
        try await Task.sleep(for: .milliseconds(40))
        tabs.view.bounds.size.width += 1
        coordinator.pageAnimator.validateLayout()
        XCTAssertFalse(coordinator.pageAnimator.isInFlight)
        XCTAssertEqual(tabs.selectedViewController?.view.transform, .identity)
    }

    func testRealSwiftUITabViewAnimatesForwardReverseAndIntoTerminal() async throws {
        let selection = AnimatedTabSelection()
        let host = UIHostingController(rootView: AnimatedTabFixture(selection: selection))
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer { window.isHidden = true }
        func coordinators(_ view: UIView) -> [TabSwipeNavigation.Coordinator] {
            (view.gestureRecognizers ?? []).compactMap { $0.delegate as? TabSwipeNavigation.Coordinator }
                + view.subviews.flatMap(coordinators)
        }
        host.view.layoutIfNeeded()
        for _ in 0..<50 where coordinators(host.view).isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        try await Task.sleep(for: .milliseconds(100))
        let coordinator = try XCTUnwrap(coordinators(host.view).first)
        defer { coordinator.pageAnimator.cancel() }
        XCTAssertNotNil(TabPageAnimator.tabController(in: host))
        for destination in [AppSection.system, .home, .system, .pi] {
            coordinator.selectFromSwipe(destination)
            XCTAssertEqual(selection.section, destination)
            for _ in 0..<30 where !coordinator.pageAnimator.isAnimating { try await Task.sleep(for: .milliseconds(5)) }
            XCTAssertTrue(coordinator.pageAnimator.isAnimating, "Real SwiftUI destination: \(destination)")
            try await Task.sleep(for: .milliseconds(80))
            let renderer = UIGraphicsImageRenderer(bounds: window.bounds)
            let attachment = XCTAttachment(image: renderer.image { _ in
                window.drawHierarchy(in: window.bounds, afterScreenUpdates: false)
            })
            attachment.name = "tab-swipe-mid-transition-\(destination)"
            attachment.lifetime = .keepAlways
            add(attachment)
            try await Task.sleep(for: .milliseconds(320))
            XCTAssertFalse(coordinator.pageAnimator.isInFlight)
        }
        XCTAssertNil(coordinator.pan.view, "No tab gesture may remain on Terminal")
        coordinator.selectFromSwipe(.jobs)
        XCTAssertEqual(selection.section, .pi, "Terminal keeps horizontal session gestures")
    }
}

@MainActor
private final class AnimatedTabSelection: ObservableObject {
    @Published var section: AppSection = .home
}

private struct AnimatedTabFixture: View {
    @ObservedObject var selection: AnimatedTabSelection
    var body: some View {
        TabView(selection: $selection.section) {
            ForEach(AppSection.allCases, id: \.self) { page in
                NavigationStack {
                    Text(page.title).frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(page == .home ? Color.red : Color.blue)
                }
                .tabItem { Label(page.title, systemImage: "circle") }
                .tag(page)
            }
        }
        .background {
            TabSwipeNavigation(section: selection.section, active: true) { selection.section = $0 }
        }
    }
}
