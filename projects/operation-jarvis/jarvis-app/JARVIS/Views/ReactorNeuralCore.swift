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
/// ReactorHeaderCore owns visibility and reduced-motion policy.
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
            // Let the canonical renderer fit its geometry to the dedicated right
            // column. Two-point insets enlarge the core without cropping it.
            .frame(width: Self.artworkSize(in: geometry.size).width,
                   height: Self.artworkSize(in: geometry.size).height)
            .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
        }
        .clipped()
        .opacity(0.95 + energy * 0.05)
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }

    static func artworkSize(in size: CGSize) -> CGSize {
        CGSize(width: max(0, size.width - 4), height: max(0, size.height - 4))
    }

    static func phase(time: TimeInterval) -> Double {
        (max(0, time) / JARVISNeuralCoreMotion.continuousLoopDuration)
            .truncatingRemainder(dividingBy: 1)
    }
}
