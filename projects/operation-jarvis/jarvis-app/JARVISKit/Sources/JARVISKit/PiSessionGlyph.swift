import SwiftUI

/// Pi's ten-frame loader sequence. Animation is decorative, never task progress.
public enum PiSessionGlyphs {
    /// Shared base size for the dashboard cards and Room Audio; Dynamic Type scales it.
    public static let dashboardSize: CGFloat = 22
    public static let frameInterval: TimeInterval = 0.08
    public static let busyFrames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    public static func isBusy(_ lifecycle: PiSessionLifecycle) -> Bool {
        lifecycle == .running || lifecycle == .compacting
    }

    public static func animates(lifecycle: PiSessionLifecycle, active: Bool,
                                sceneActive: Bool, reduceMotion: Bool,
                                luminanceReduced: Bool) -> Bool {
        isBusy(lifecycle) && ActivityMotionGate.allows(active: active,
            sceneActive: sceneActive, reduceMotion: reduceMotion,
            luminanceReduced: luminanceReduced)
    }

    public static func glyph(lifecycle: PiSessionLifecycle, time: TimeInterval = 0,
                             animating: Bool = false) -> String {
        switch lifecycle {
        case .running, .compacting:
            guard animating, time.isFinite, time >= 0 else { return busyFrames[0] }
            // Bound before converting to Int, including extreme finite timestamps.
            let cycle = frameInterval * Double(busyFrames.count)
            let phase = time.truncatingRemainder(dividingBy: cycle)
            let index = min(Int(phase / frameInterval), busyFrames.count - 1)
            return busyFrames[index]
        case .idle: return "●"
        case .new: return "○"
        case .offline: return "×"
        case .unknown: return "?"
        }
    }
}

/// Fixed-size dashboard glyph; phone/Watch Terminal capsules keep their own motion.
public struct PiSessionGlyph: View {
    public let lifecycle: PiSessionLifecycle
    public let active: Bool
    public let size: CGFloat

    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    public init(lifecycle: PiSessionLifecycle, active: Bool, size: CGFloat = PiSessionGlyphs.dashboardSize) {
        self.lifecycle = lifecycle
        self.active = active
        self.size = size
    }

    public var body: some View {
        Group {
            if PiSessionGlyphs.animates(lifecycle: lifecycle, active: active,
                sceneActive: scenePhase == .active, reduceMotion: reduceMotion,
                luminanceReduced: luminanceReduced) {
                // A common epoch keeps every busy indicator in phase. This clock
                // exists only while eligible; it never refreshes backend state.
                TimelineView(.periodic(from: Date(timeIntervalSinceReferenceDate: 0),
                                       by: PiSessionGlyphs.frameInterval)) { context in
                    Text(PiSessionGlyphs.glyph(lifecycle: lifecycle,
                        time: context.date.timeIntervalSinceReferenceDate, animating: true))
                }
            } else {
                // Retain a recognisable busy shape under Reduce Motion/offscreen.
                Text(PiSessionGlyphs.glyph(lifecycle: lifecycle))
            }
        }
        .font(.system(size: size, weight: .regular, design: .monospaced))
        .foregroundStyle(lifecycle.statusColor)
        .frame(width: size, height: size)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
