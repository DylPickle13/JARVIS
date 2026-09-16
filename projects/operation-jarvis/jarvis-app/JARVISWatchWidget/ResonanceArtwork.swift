import SwiftUI
import WidgetKit

/// Decorative voice-port artwork, never an indication that the microphone is live.
struct JARVISResonanceArtwork: View {
    @Environment(\.isLuminanceReduced) private var reducedLuminance
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.widgetRenderingMode) private var renderingMode
    var allowsMotion = true

    private var animate: Bool {
        allowsMotion && !reducedLuminance && !reduceMotion &&
            renderingMode == .fullColor && JARVISWidgetTimerAnimationFont.isAvailable
    }

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            ZStack {
                // Permanent complete frame: even a suspended timer mask leaves
                // recognizable rings, waveform, and nodes, never an empty icon.
                ResonanceFrame(phase: 0, movingOnly: false, subdued: animate)
                if animate {
                    ForEach(0..<24, id: \.self) { index in
                        ResonanceFrame(phase: Double(index) / 24, movingOnly: true)
                            .frame(width: side, height: side)
                            .mask {
                                JARVISWidgetTimerFrameWindow(frameIndex: index, frameCount: 24, extent: max(1, side))
                                    .frame(width: side, height: side)
                            }
                    }
                }
            }
            .frame(width: side, height: side)
            .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
        }
        .id(animate)
        .widgetAccentable()
        .accessibilityHidden(true)
    }
}

/// Canonical 112-unit geometry matches the approved Resonance concept.
private struct ResonanceFrame: View {
    let phase: Double
    let movingOnly: Bool
    var subdued = false

    var body: some View {
        Canvas { context, size in
            let scale = min(size.width, size.height) / 112
            context.translateBy(x: size.width / 2, y: size.height / 2)
            context.scaleBy(x: scale, y: scale)
            func arc(_ radius: CGFloat, _ start: Double, _ length: Double, _ width: CGFloat, _ opacity: Double) {
                var path = Path()
                path.addArc(center: .zero, radius: radius, startAngle: .degrees(start), endAngle: .degrees(start + length), clockwise: false)
                context.stroke(path, with: .color(.white.opacity(opacity)), style: StrokeStyle(lineWidth: width, lineCap: .round))
            }
            if !movingOnly {
                for base in [3.0, 123, 243] {
                    arc(43, base, 101, 1.65, 0.88)
                    arc(37, base + 11, 67, 0.85, 0.40)
                }
            }
            let angle = phase * 2 * Double.pi
            let heights = [14.0, 31, 43, 26, 12]
            for (index, baseline) in heights.enumerated() {
                let modulation = movingOnly ? 1 + 0.10 * sin(angle + Double(index) * 0.7) : 1
                let h = baseline * modulation
                let x = Double(index - 2) * 7
                var bar = Path()
                bar.move(to: CGPoint(x: x, y: -h / 2))
                bar.addLine(to: CGPoint(x: x, y: h / 2))
                context.stroke(bar, with: .color(.white.opacity(subdued ? 0.52 : 0.96)), style: StrokeStyle(lineWidth: 2.8, lineCap: .round))
            }
            for base in [112.0, 232, 352] {
                let drift = movingOnly ? 2.5 * sin(angle) : 0
                let radians = (base + drift) * Double.pi / 180
                let center = CGPoint(x: cos(radians) * 43, y: sin(radians) * 43)
                context.fill(Path(ellipseIn: CGRect(x: center.x - 1.7, y: center.y - 1.7, width: 3.4, height: 3.4)), with: .color(.white.opacity(subdued ? 0.45 : 0.9)))
            }
            if movingOnly {
                // Restrained travelling sheen inside each static inner arc.
                for base in [14.0, 134, 254] {
                    arc(37, base + 25 + 18 * sin(angle), 12, 0.9, 0.65)
                }
            }
        }
    }
}
