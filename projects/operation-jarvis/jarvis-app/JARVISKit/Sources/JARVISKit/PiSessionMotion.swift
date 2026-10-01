import SwiftUI

/// Decorative positions, not task progress. Shared timing keeps Home and terminal in sync.
public enum PiSessionMotionGeometry {
    public static func highlights(lifecycle: PiSessionLifecycle, time: Double, compact: Bool) -> [Double] {
        guard time.isFinite, lifecycle == .running || lifecycle == .compacting else { return [] }
        let period = (lifecycle == .compacting ? 2.6 : 1.8) * (compact ? 1.3 : 1)
        let cycle = time.truncatingRemainder(dividingBy: period) / period
        let phase = cycle < 0 ? cycle + 1 : cycle
        if lifecycle == .compacting {
            let left = -0.25 + phase * 0.75
            return [left, 1 - left]
        }
        return [-0.25 + phase * 1.5]
    }
}

public extension View {
    /// Applies a moving highlight only inside the original icon/dot, without resizing it.
    func piSessionMotion(lifecycle: PiSessionLifecycle, active: Bool, compact: Bool = false) -> some View {
        modifier(PiSessionMotion(lifecycle: lifecycle, active: active, compact: compact))
    }
}

private struct PiSessionMotion: ViewModifier {
    let lifecycle: PiSessionLifecycle
    let active: Bool
    let compact: Bool
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced
    @State private var previousLifecycle: PiSessionLifecycle?
    @State private var flashStarted: Date?

    func body(content: Content) -> some View {
        let eligible = ActivityMotionGate.allows(active: active && lifecycle != .unknown,
            sceneActive: scenePhase == .active, reduceMotion: reduceMotion,
            luminanceReduced: luminanceReduced)
        let moving = lifecycle == .running || lifecycle == .compacting
        content.overlay {
            if eligible && (moving || flashStarted != nil) {
                TimelineView(.animation(minimumInterval: compact ? 1.0 / 20 : 1.0 / 30)) { context in
                    Canvas { graphics, size in
                        let bounds = CGRect(origin: .zero, size: size)
                        if let flashStarted {
                            let strength = max(0, 1 - context.date.timeIntervalSince(flashStarted) / 0.55)
                            graphics.fill(Path(bounds), with: .color(.white.opacity(0.65 * strength)))
                        }
                        let positions = PiSessionMotionGeometry.highlights(lifecycle: lifecycle,
                            time: context.date.timeIntervalSinceReferenceDate, compact: compact)
                        for position in positions {
                            let center = size.width * position
                            let radius = max(1, size.width * 0.24)
                            graphics.fill(Path(bounds), with: .linearGradient(
                                Gradient(colors: [.clear, .white.opacity(0.85), .clear]),
                                startPoint: CGPoint(x: center - radius, y: 0),
                                endPoint: CGPoint(x: center + radius, y: 0)))
                        }
                    }
                }
                .mask(content)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
            }
        }
        .task(id: lifecycle) {
            let changed = previousLifecycle != nil && previousLifecycle != lifecycle
            previousLifecycle = lifecycle
            flashStarted = nil
            guard eligible && changed else { return }
            flashStarted = Date()
            defer { flashStarted = nil }
            try? await Task.sleep(for: .milliseconds(550))
        }
        .onChange(of: eligible) { allowed in
            if !allowed { flashStarted = nil }
        }
    }
}
