import SwiftUI

/// Fixed decorative cadence and short perimeter coverage, never progress.
public enum ActivityEdgeGeometry {
    public static let fadeDuration = 0.65
    public static func ranges(time: Double, period: Double = 2.8) -> [ClosedRange<Double>] {
        guard time.isFinite, period.isFinite, period > 0 else { return [] }
        let cycles = time / period
        guard cycles.isFinite else { return [] }
        var start = cycles.truncatingRemainder(dividingBy: 1)
        if start < 0 { start += 1 }
        let end = start + 0.24
        return end <= 1 ? [start...end] : [start...1, 0...(end - 1)]
    }
}

public extension View {
    /// Callers permit a fade only for a known, fresh completion. Loss of trust,
    /// visibility or accessibility eligibility destroys the animation subtree.
    func activityCardEdge(active: Bool, allowed: Bool, cornerRadius: CGFloat = 14,
                          compact: Bool = false, muted: Bool = false) -> some View {
        modifier(ActivityCardEdge(active: active, allowed: allowed,
            cornerRadius: cornerRadius, compact: compact, muted: muted))
    }

    func activityStatusBreath(active: Bool, slow: Bool = false, compact: Bool = false) -> some View {
        modifier(ActivityStatusBreath(active: active, slow: slow, compact: compact))
    }
}

private struct ActivityCardEdge: ViewModifier {
    let active: Bool
    let allowed: Bool
    let cornerRadius: CGFloat
    let compact: Bool
    let muted: Bool
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    func body(content: Content) -> some View {
        let eligible = ActivityMotionGate.allows(active: allowed, sceneActive: scenePhase == .active,
            reduceMotion: reduceMotion, luminanceReduced: luminanceReduced)
        content.overlay {
            ZStack {
                if eligible && active {
                    ActivityEdgeHighlight(cornerRadius: cornerRadius, compact: compact, muted: muted)
                        .transition(.opacity)
                }
            }
            // Keep the outgoing edge at the card's full bounds during its fade.
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            // Only the decoration fades; labels, controls and layout never do.
            .animation(eligible ? .easeOut(duration: ActivityEdgeGeometry.fadeDuration) : nil, value: active)
            // Interrupt even a fade already in flight on stale/AOD/Reduce Motion.
            .id(eligible)
            .transaction { if !eligible { $0.animation = nil; $0.disablesAnimations = true } }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }
}

private struct ActivityEdgeHighlight: View {
    let cornerRadius: CGFloat
    let compact: Bool
    let muted: Bool
    var body: some View {
        // Mounted only during eligible activity or its bounded650ms completion fade.
        // No network requests, unbounded tasks, glow/blur or rotating card geometry.
        TimelineView(.animation(minimumInterval: compact ? 0.05 : (1.0 / 30))) { context in
            Canvas { graphics, size in
                let rect = CGRect(origin: .zero, size: size).insetBy(dx: 1.5, dy: 1.5)
                guard rect.width > 0, rect.height > 0 else { return }
                let path = RoundedRectangle(cornerRadius: max(0, cornerRadius - 1.5), style: .continuous).path(in: rect)
                for range in ActivityEdgeGeometry.ranges(time: context.date.timeIntervalSinceReferenceDate,
                                                         period: compact ? 3.2 : 2.8) {
                    graphics.stroke(path.trimmedPath(from: range.lowerBound, to: range.upperBound),
                        with: .color(.white.opacity(muted ? 0.65 : (compact ? 0.9 : 0.95))),
                        style: StrokeStyle(lineWidth: muted ? 1.75 : (compact ? 2 : 2.5), lineCap: .round))
                }
            }
        }
    }
}

private struct ActivityStatusBreath: ViewModifier {
    let active: Bool
    let slow: Bool
    let compact: Bool
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    @ViewBuilder func body(content: Content) -> some View {
        let enabled = ActivityMotionGate.allows(active: active, sceneActive: scenePhase == .active,
            reduceMotion: reduceMotion, luminanceReduced: luminanceReduced)
        if #available(iOS 17, watchOS 10, macOS 14, *), enabled {
            content.phaseAnimator([false, true]) { dot, dimmed in
                dot.opacity(dimmed ? 0.35 : 1)
                    .scaleEffect(dimmed ? 0.85 : 1.45)
            } animation: { _ in .easeInOut(duration: slow ? 1.3 : 0.8) }
        } else {
            content
        }
    }
}
