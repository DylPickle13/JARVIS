import SwiftUI
import UIKit
import JARVISKit

/// One directional recognizer on the phone's tab host. It is physically detached
/// while Terminal is selected, so it cannot compete with Pi session gestures.
struct TabSwipeNavigation: UIViewRepresentable {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let section: AppSection
    let active: Bool
    let select: (AppSection) -> Void

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> Probe {
        let view = Probe()
        view.isUserInteractionEnabled = false
        view.backgroundColor = .clear
        view.mounted = { [weak coordinator = context.coordinator] probe in
            coordinator?.mount(probe)
        }
        return view
    }

    func updateUIView(_ view: Probe, context: Context) {
        context.coordinator.configure(section: section, active: active, reduceMotion: reduceMotion, select: select)
        context.coordinator.mount(view)
    }

    static func dismantleUIView(_ view: Probe, coordinator: Coordinator) {
        view.mounted = nil
        coordinator.detach()
        coordinator.pageAnimator.cancel()
    }

    final class Probe: UIView {
        var mounted: ((Probe) -> Void)?
        override func didMoveToWindow() {
            super.didMoveToWindow()
            mounted?(self)
        }
        override func layoutSubviews() {
            super.layoutSubviews()
            mounted?(self)
        }
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        private(set) var section: AppSection = .home
        private var active = false
        private var reduceMotion = false
        let pageAnimator = TabPageAnimator()
        private var select: ((AppSection) -> Void)?
        private var startedOn: AppSection?
        private weak var probe: Probe?
        private weak var host: UIViewController?
        lazy var pan: UIPanGestureRecognizer = {
            let recognizer = UIPanGestureRecognizer(target: self, action: #selector(dragged(_:)))
            recognizer.maximumNumberOfTouches = 1
            recognizer.cancelsTouchesInView = true
            recognizer.delegate = self
            return recognizer
        }()

        func configure(section: AppSection, active: Bool, reduceMotion: Bool = false,
                       select: @escaping (AppSection) -> Void) {
            let changed = self.section != section
            if changed || self.active != active { detach() }
            self.section = section
            self.active = active
            self.reduceMotion = reduceMotion
            self.select = select
            if !active || reduceMotion { pageAnimator.cancel() }
            else if changed { pageAnimator.selectionDidChange(to: section) }
        }

        func mount(_ probe: Probe) {
            self.probe = probe
            pageAnimator.validateLayout()
            guard active, section != .pi, probe.window != nil else { detach(); return }
            var responder: UIResponder? = probe
            while let current = responder, !(current is UIViewController) { responder = current.next }
            guard var controller = responder as? UIViewController else { return }
            while let parent = controller.parent { controller = parent }
            host = controller
            if pan.view !== controller.view {
                detach()
                controller.view.addGestureRecognizer(pan)
            }
        }

        func detach() {
            pan.view?.removeGestureRecognizer(pan)
            startedOn = nil
        }

        /// Public-to-tests policy avoids relying on SwiftUI's private view names.
        static func blocksTouch(_ view: UIView, root: UIView) -> Bool {
            var candidate: UIView? = view
            while let current = candidate {
                if current is UIControl || current is UITextView || current is UITabBar
                    || current.accessibilityTraits.contains(.adjustable) { return true }
                if let scroll = current as? UIScrollView, isHorizontal(scroll) { return true }
                if current === root { break }
                candidate = current.superview
            }
            return false
        }

        static func isHorizontal(_ scroll: UIScrollView) -> Bool {
            scroll.alwaysBounceHorizontal || scroll.contentSize.width > scroll.bounds.width + 1
        }

        static func hasOverlay(_ controller: UIViewController) -> Bool {
            if controller.presentedViewController != nil { return true }
            return controller.children.contains(where: hasOverlay)
        }

        static func isPushedContent(_ view: UIView) -> Bool {
            var responder: UIResponder? = view
            while let current = responder {
                if let controller = current as? UIViewController,
                   let navigation = controller.navigationController,
                   navigation.viewControllers.count > 1 { return true }
                responder = current.next
            }
            return false
        }

        private func isExcluded(_ point: CGPoint, in root: UIView) -> Bool {
            if root.isHidden || root.alpha < 0.01 { return false }
            if root is TabSwipeExclusionView, root.bounds.contains(root.convert(point, from: pan.view)) { return true }
            return root.subviews.contains { isExcluded(point, in: $0) }
        }

        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
            guard active, section != .pi, !UIAccessibility.isVoiceOverRunning,
                  let view = touch.view, let host, let probe,
                  probe.bounds.contains(touch.location(in: probe)),
                  !Self.hasOverlay(host), !Self.blocksTouch(view, root: host.view),
                  !Self.isPushedContent(view),
                  !isExcluded(touch.location(in: host.view), in: host.view) else { return false }
            return true
        }

        func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
            let velocity = pan.velocity(in: pan.view)
            guard active, section != .pi, !pageAnimator.isInFlight, abs(velocity.x) > abs(velocity.y) * 1.5 else { return false }
            // Fail immediately on vertical intent and at non-wrapping boundaries.
            return section.swipeDestination(horizontal: velocity.x < 0 ? -64 : 64, vertical: 0) != nil
        }

        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            // Let vertical page scrolling start naturally. Horizontal controls,
            // pop gestures and other drag recognizers never share this gesture.
            guard let scroll = other.view as? UIScrollView,
                  other === scroll.panGestureRecognizer else { return false }
            return !Self.isHorizontal(scroll)
        }

        @objc private func dragged(_ gesture: UIPanGestureRecognizer) {
            if gesture.state == .began { startedOn = section }
            guard gesture.state == .ended else { return }
            defer { startedOn = nil }
            guard active, startedOn == section, let host, !Self.hasOverlay(host) else { return }
            let distance = gesture.translation(in: gesture.view)
            guard let destination = section.swipeDestination(horizontal: distance.x, vertical: distance.y) else { return }
            selectFromSwipe(destination)
        }
        func selectFromSwipe(_ destination: AppSection) {
            guard active, section != .pi, !pageAnimator.isInFlight,
                  let host, !Self.hasOverlay(host),
                  let from = AppSection.allCases.firstIndex(of: section),
                  let to = AppSection.allCases.firstIndex(of: destination),
                  abs(to - from) == 1,
                  let direction = PageNavigationMotion.direction(from: from, to: to) else { return }
            if PageNavigationMotion.allows(active: active,
                reduceMotion: reduceMotion || UIAccessibility.isReduceMotionEnabled),
               let tabs = TabPageAnimator.tabController(in: host) {
                pageAnimator.prepare(tabs: tabs, destination: destination, direction: direction)
            }
            // Route immediately through the existing binding; only presentation waits.
            select?(destination)
        }
    }
}

/// Explicit exclusion for SwiftUI horizontal controls, whose UIKit hit target
/// may be their containing hosting view rather than a UIControl.
private final class TabSwipeExclusionView: UIView {}
private struct TabSwipeExclusion: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView {
        let view = TabSwipeExclusionView()
        view.isUserInteractionEnabled = false
        return view
    }
    func updateUIView(_ uiView: UIView, context: Context) {}
}

extension View {
    func tabSwipeExcluded() -> some View { background(TabSwipeExclusion()) }
}
