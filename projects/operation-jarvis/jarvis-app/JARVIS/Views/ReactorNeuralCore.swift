import SwiftUI
import JARVISKit

struct ReactorHeaderCore: View {
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !active || reduceMotion)) { context in
            let time = active && !reduceMotion ? context.date.timeIntervalSinceReferenceDate : 0
            ReactorNeuralCore(time: time, energy: ReactorTitlePhase(elapsed: time, animated: active && !reduceMotion).energy)
        }
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }
}

/// Reuse the widget's Cathedral renderer, not a second interpretation of it.
/// ReactorHeaderCore owns visibility, reduced-motion policy, and clipping.
struct ReactorNeuralCore: View {
    let time: TimeInterval
    let energy: Double

    var body: some View {
        GeometryReader { geometry in
            JARVISNeuralCoreFrameArtwork(
                telemetry: JARVISNeuralCoreTelemetry(cached: nil),
                layout: .phone,
                motionPhase: Self.phase(time: time),
                layerSet: .complete
            )
            // Render at widget scale, then crop—not shrink—to the header band.
            // Its architectural wings remain visible beside the opaque wordmark.
            .frame(width: geometry.size.width, height: max(140, geometry.size.height))
            .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
        }
        .clipped()
        .opacity(0.95 + energy * 0.05)
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }

    static func phase(time: TimeInterval) -> Double {
        (max(0, time) / JARVISNeuralCoreMotion.continuousLoopDuration)
            .truncatingRemainder(dividingBy: 1)
    }
}
