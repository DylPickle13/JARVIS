import SwiftUI
import WidgetKit

/// Surge Cascade reactor: decorative motion, never a microphone/listening indicator.
/// Legacy type names preserve the existing Talk widget integration.
struct JARVISResonanceArtwork: View {
    @Environment(\.isLuminanceReduced) private var reducedLuminance

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    // Two-second cycle: 16 phases (nominal 8 FPS), 32 masks instead of 64.
    // Bound Talk's scene count after a physical widget memory-limit termination.
    private let frameCount = 16
    private var animates: Bool {
        !reducedLuminance && !reduceMotion && JARVISWidgetTimerAnimationFont.isAvailable
    }

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            Group {
                if animates {
                    ZStack {
                        ForEach(0..<frameCount, id: \.self) { index in
                            ResonanceStaticFrame(phase: Double(index) / Double(frameCount))
                                .frame(width: side, height: side)
                                .mask {
                                    JARVISWidgetTimerFrameWindow(
                                        frameIndex: index, frameCount: frameCount, extent: max(1, side)
                                    )
                                    .frame(width: side, height: side)
                                }
                        }
                    }
                } else {
                    ResonanceStaticFrame(simplified: reducedLuminance)
                }
            }
                .id(animates)
                .frame(width: side, height: side)
                .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
        }
        .widgetAccentable()
        .accessibilityHidden(true)
    }
}

/// Canonical 112-unit geometry; inverted emitter with a layered metal housing.
struct ResonanceStaticFrame: View {
    var simplified = false
    // Freeze the current Cascade design when WidgetKit cannot animate.
    var phase: Double = 0.25

    var body: some View {
        Canvas { context, size in
            let scale = min(size.width, size.height) / 112
            context.translateBy(x: size.width / 2, y: size.height / 2)
            context.scaleBy(x: scale, y: scale)

            // Clipped tips suggest machined metal while retaining the inverted triangle.
            func triangle(_ insetScale: CGFloat) -> Path {
                let vertices: [CGPoint] = [
                    CGPoint(x: -39, y: -34), CGPoint(x: 39, y: -34),
                    CGPoint(x: 42, y: -29), CGPoint(x: 3, y: 37),
                    CGPoint(x: -3, y: 37), CGPoint(x: -42, y: -29)
                ]
                var path = Path()
                for (index, vertex) in vertices.enumerated() {
                    let point = CGPoint(x: vertex.x * insetScale, y: vertex.y * insetScale)
                    if index == 0 { path.move(to: point) }
                    else { path.addLine(to: point) }
                }
                path.closeSubpath()
                return path
            }

            // Reduced luminance changes brightness, never the reactor geometry.
            context.opacity = simplified ? 0.65 : 1
            do {
                // Keep the animated housing, but use an explicit white emitter in
                // every rendering mode—not a gray fill flattened by the watch face.
                context.stroke(triangle(1.06), with: .color(.white.opacity(0.43)),
                               style: StrokeStyle(lineWidth: 1.4, lineJoin: .round))
                context.stroke(triangle(0.91), with: .color(.white.opacity(0.69)),
                               style: StrokeStyle(lineWidth: 1.05, lineJoin: .round))
                for index in 0..<3 {
                    let u = (phase + Double(index) / 3).truncatingRemainder(dividingBy: 1)
                    let brightness = (70 + 185 * sqrt(max(0, sin(.pi * u)))) / 255
                    context.stroke(triangle(1.02 - 0.72 * u),
                                   with: .color(Color(white: brightness)),
                                   style: StrokeStyle(lineWidth: 2.8, lineJoin: .round))
                }
                // Paint last so inward waves never hollow out the solid core.
                context.fill(triangle(0.72), with: .color(.white))
            }
        }
    }
}
