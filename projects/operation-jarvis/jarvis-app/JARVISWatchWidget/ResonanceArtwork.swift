import SwiftUI
import WidgetKit

/// Static Mark VI-inspired triangular arc reactor, never a microphone/listening indicator.
/// Legacy type names preserve the existing Talk widget integration.
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

/// Canonical 112-unit geometry; inverted emitter with a layered metal housing.
struct ResonanceStaticFrame: View {
    var simplified = false

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

            // Two nested steel-white rims, with black separation around the emitter.
            context.stroke(triangle(1), with: .color(.white.opacity(0.55)), style: StrokeStyle(lineWidth: 3, lineJoin: .round))
            context.stroke(triangle(0.84), with: .color(.white.opacity(simplified ? 0.75 : 0.90)), style: StrokeStyle(lineWidth: 2, lineJoin: .round))
            if !simplified {
                // A restrained top bevel, not a glow or animated highlight.
                var bevel = Path()
                bevel.move(to: CGPoint(x: -35, y: -34))
                bevel.addLine(to: CGPoint(x: 35, y: -34))
                context.stroke(bevel, with: .color(.white.opacity(0.85)), style: StrokeStyle(lineWidth: 1, lineCap: .round))
            }
            // Keep the triangular silhouette complete in reduced luminance.
            context.fill(triangle(simplified ? 0.62 : 0.65), with: .color(.white))
        }
    }
}
