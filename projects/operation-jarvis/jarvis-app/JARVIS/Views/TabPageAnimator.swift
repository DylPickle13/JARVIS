import UIKit
import JARVISKit

/// Animates a committed swipe without replacing TabView, its delegate, or any
/// hosting/navigation controller. The native tab bar and persistent tab state stay put.
@MainActor
final class TabPageAnimator {
    private weak var tabs: UITabBarController?
    private weak var source: UIView?
    private var overlay: UIView?
    private var snapshot: UIView?
    private var animator: UIViewPropertyAnimator?
    private var containerBounds = CGRect.zero
    private var direction: PageNavigationMotion.Direction = .forward
    private var generation = UUID()
    private(set) var destination: AppSection?
    var isInFlight: Bool { destination != nil }
    var isAnimating: Bool { animator?.isRunning == true }

    static func tabController(in controller: UIViewController) -> UITabBarController? {
        if let tabs = controller as? UITabBarController { return tabs }
        for child in controller.children {
            if let tabs = tabController(in: child) { return tabs }
        }
        return nil
    }

    func prepare(tabs: UITabBarController, destination: AppSection,
                 direction: PageNavigationMotion.Direction) {
        cancel()
        guard let source = tabs.selectedViewController?.viewIfLoaded,
              source.window != nil, source.bounds.width > 0, source.bounds.height > 0,
              let snapshot = source.snapshotView(afterScreenUpdates: false) else { return }
        let container = tabs.view!
        var frame = source.convert(source.bounds, to: container).intersection(container.bounds)
        if !tabs.tabBar.isHidden {
            let bar = tabs.tabBar.convert(tabs.tabBar.bounds, to: container)
            if frame.intersects(bar) { frame.size.height = max(0, bar.minY - frame.minY) }
        }
        guard !frame.isEmpty, !frame.isNull else { return }
        let overlay = UIView(frame: frame)
        overlay.clipsToBounds = true
        // Shield content taps briefly while its visual position is in flight;
        // the native tab bar remains outside this overlay and fully usable.
        overlay.isUserInteractionEnabled = true
        overlay.backgroundColor = .systemBackground
        overlay.accessibilityElementsHidden = true
        snapshot.frame = source.convert(source.bounds, to: container)
            .offsetBy(dx: -frame.minX, dy: -frame.minY)
        overlay.addSubview(snapshot)
        container.addSubview(overlay)
        self.tabs = tabs
        self.source = source
        self.snapshot = snapshot
        self.overlay = overlay
        self.direction = direction
        self.destination = destination
        containerBounds = container.bounds
    }

    func selectionDidChange(to section: AppSection) {
        guard destination == section else { cancel(); return }
        // SwiftUI commits TabView selection after its representable update. Wait
        // for that commit, not for a second tap; abandon stale/interrupted work.
        startWhenReady(generation: generation, attempt: 0)
    }

    private func startWhenReady(generation expected: UUID, attempt: Int) {
        DispatchQueue.main.asyncAfter(deadline: .now() + (attempt == 0 ? 0 : 0.016)) { [weak self] in
            guard let self, self.generation == expected, let tabs = self.tabs,
                  let overlay = self.overlay else { return }
            guard tabs.view.window != nil, tabs.view.bounds == self.containerBounds,
                  !UIAccessibility.isReduceMotionEnabled,
                  !TabSwipeNavigation.Coordinator.hasOverlay(tabs) else { self.cancel(); return }
            tabs.view.layoutIfNeeded()
            guard let incoming = tabs.selectedViewController?.viewIfLoaded,
                  incoming !== self.source, incoming.window != nil else {
                if attempt < 4 { self.startWhenReady(generation: expected, attempt: attempt + 1) }
                else { self.cancel() }
                return
            }
            guard let arrival = incoming.snapshotView(afterScreenUpdates: true),
                  let departure = self.snapshot else { self.cancel(); return }
            arrival.frame = incoming.convert(incoming.bounds, to: tabs.view)
                .offsetBy(dx: -overlay.frame.minX, dy: -overlay.frame.minY)
            let travel = CGFloat(self.direction.sign * PageNavigationMotion.travel(extent: overlay.bounds.width))
            arrival.transform = CGAffineTransform(translationX: travel, y: 0)
            arrival.alpha = 0
            overlay.insertSubview(arrival, belowSubview: departure)
            tabs.view.bringSubviewToFront(overlay)
            // Animate only snapshots. UIKit may run its own tab crossfade below
            // us; never multiply it, change a live page's alpha, or move controls.
            let animator = UIViewPropertyAnimator(duration: PageNavigationMotion.duration, curve: .easeOut) {
                arrival.transform = .identity
                arrival.alpha = 1
                departure.transform = CGAffineTransform(translationX: -travel, y: 0)
                departure.alpha = 0
            }
            self.animator = animator
            animator.addCompletion { [weak self] _ in
                guard let self, self.generation == expected else { return }
                self.cancel()
            }
            animator.startAnimation()
        }
    }

    func validateLayout() {
        if let tabs, tabs.view.window == nil || tabs.view.bounds != containerBounds { cancel() }
    }

    func cancel() {
        generation = UUID()
        animator?.stopAnimation(true)
        animator = nil
        overlay?.removeFromSuperview()
        overlay = nil
        snapshot = nil
        source = nil
        tabs = nil
        destination = nil
    }
}
