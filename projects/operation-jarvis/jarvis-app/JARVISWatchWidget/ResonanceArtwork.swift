import SwiftUI
import WidgetKit

/// A static engraved voice port, never a microphone/listening indicator.
/// One Canvas: no timer text, frame selectors, animation, or font dependency.
struct JARVISResonanceArtwork: View {
    @Environment(\.isLuminanceReduced) private var reducedLuminance

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            ResonanceStaticFrame(simplified: reducedLuminance)
                .frame(width: side, height: side)
                .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
        }
        .widgetAccentable()
        .accessibilityHidden(true)
    }
}

/// Canonical 112-unit geometry; broad silhouettes survive small face slots.
struct ResonanceStaticFrame: View {
    var simplified = false

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
            func point(_ radius: Double, _ degrees: Double) -> CGPoint {
                let radians = degrees * .pi / 180
                return CGPoint(x: cos(radians) * radius, y: sin(radians) * radius)
            }
            // Three machined outer segments with fine inset tracks and end caps.
            for base in [3.0, 123, 243] {
                arc(44, base, 100, 2.4, 0.95)
                arc(37.5, base + 10, 74, 1.15, 0.55)
                if !simplified {
                    arc(48, base + 8, 80, 0.8, 0.28)
                    arc(40.5, base + 3, 18, 1.0, 0.75)
                    arc(44, base + 92, 8, 3.6, 1)
                }
            }
            // Instrument-style calibration marks, omitted in reduced luminance.
            if !simplified {
                for index in 0..<24 where index % 8 != 7 {
                    let angle = Double(index) * 15 + 3
                    var tick = Path()
                    tick.move(to: point(50, angle))
                    tick.addLine(to: point(index % 2 == 0 ? 53 : 51.5, angle))
                    context.stroke(tick, with: .color(.white.opacity(index % 2 == 0 ? 0.55 : 0.3)), lineWidth: 0.9)
                }
            }
            // Five fixed waveform bars with a bright center and balanced shoulders.
            for (index, height) in [15.0, 29, 43, 29, 15].enumerated() {
                let x = Double(index - 2) * 7.5
                var bar = Path()
                bar.move(to: CGPoint(x: x, y: -height / 2))
                bar.addLine(to: CGPoint(x: x, y: height / 2))
                context.stroke(bar, with: .color(.white.opacity(index == 2 ? 1 : 0.88)), style: StrokeStyle(lineWidth: index == 2 ? 3.6 : 3.0, lineCap: .round))
            }
            // Three orbital jewel nodes, each held inside a small static socket.
            for angle in [113.0, 233, 353] {
                let center = point(44, angle)
                if !simplified {
                    context.stroke(Path(ellipseIn: CGRect(x: center.x - 3.7, y: center.y - 3.7, width: 7.4, height: 7.4)), with: .color(.white.opacity(0.45)), lineWidth: 0.85)
                }
                context.fill(Path(ellipseIn: CGRect(x: center.x - 1.8, y: center.y - 1.8, width: 3.6, height: 3.6)), with: .color(.white))
            }
        }
    }
}
