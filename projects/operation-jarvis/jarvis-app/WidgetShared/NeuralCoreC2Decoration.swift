import SwiftUI

/// Approved C2: subdued dendritic sides, with the dense central shell remaining
/// dominant. Static branches and shell are hoisted outside the 48-frame stack.
/// Twelve short outward pulses share its existing phase; no new motion clock,
/// telemetry dependency, blur pass or intentional Always-On dimming is added.
/// Owner-requested extra vibrancy is confined to central-shell contrast and
/// silver highlights; side-beam brightness and all RGB palette values stay fixed.
enum JARVISNeuralCoreC2Decoration {
    struct Palette {
        let white: Color
        let bright: Color
        let beam: Color
        let pale: Color
        let silver: Color

        init(usesFullColor: Bool) {
            white = usesFullColor ? .white : .primary
            bright = usesFullColor ? Color(white: 0.98) : .primary
            beam = usesFullColor ? Color(white: 0.90) : .primary.opacity(0.92)
            pale = usesFullColor ? Color(white: 0.80) : .primary.opacity(0.82)
            silver = usesFullColor ? Color(white: 0.62) : .primary.opacity(0.64)
        }
    }

    private static func noise(_ value: Int) -> CGFloat {
        let f = sin(Double(value) * 127.1 + 311.7) * 43758.5453
        return CGFloat(f - floor(f))
    }

    private static func cubic(_ a: CGPoint, _ b: CGPoint, _ c: CGPoint, _ d: CGPoint, _ t: CGFloat) -> CGPoint {
        let k = 1 - t
        return CGPoint(
            x: k*k*k*a.x + 3*k*k*t*b.x + 3*k*t*t*c.x + t*t*t*d.x,
            y: k*k*k*a.y + 3*k*k*t*b.y + 3*k*t*t*c.y + t*t*t*d.y
        )
    }

    private struct Beam {
        let start: CGPoint
        let control1: CGPoint
        let control2: CGPoint
        let end: CGPoint

        func point(at progress: CGFloat) -> CGPoint {
            JARVISNeuralCoreC2Decoration.cubic(start, control1, control2, end, progress)
        }
    }

    /// Shared by the static dendrite and its moving light so they cannot drift.
    private static func beam(index: Int, side: Int, size: CGSize, radius r: CGFloat) -> Beam {
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let u = r / 50, sign = CGFloat(side)
        let seed = index + (side == -1 ? 500 : 900)
        let offset = (noise(seed) * 2 - 1) * 0.78
        let start = CGPoint(x: c.x + sign*r*0.45, y: c.y + offset*r*0.22)
        let reach = (size.width/2 - 8*u) * (0.80 + 0.20*noise(seed+2))
        let end = CGPoint(x: c.x + sign*reach, y: c.y + offset*r)
        return Beam(start: start,
                    control1: CGPoint(x: c.x + sign*r*1.05, y: c.y - offset*r*0.38),
                    control2: CGPoint(x: c.x + sign*reach*0.74, y: end.y + (noise(seed+11)-0.5)*r*0.75),
                    end: end)
    }

    /// Decorative pulses are never progress or throughput. The outer widget
    /// policy supplies a fixed phase for Reduce Motion, AOD and static fallback.
    static func drawImpulses(context: inout GraphicsContext, size: CGSize, radius r: CGFloat, palette: Palette, phase: CGFloat) {
        guard r > 0, phase.isFinite else { return }
        let u = r / 50
        let normalizedPhase = phase - phase.rounded(.down)
        for side in [-1, 1] {
            for index in [0, 4, 8, 12, 16, 20] {
                let shape = beam(index: index, side: side, size: size, radius: r)
                let seed = index + (side == -1 ? 500 : 900)
                let shifted = normalizedPhase + noise(seed+2020)
                let progress = shifted - shifted.rounded(.down)
                // Smooth wrap: fade before the head returns to its root.
                let envelope = Double(min(1, progress/0.14, (1-progress)/0.14))
                let t = 0.16 + progress*0.76
                let tailT = max(0.12, t-0.12)
                let head = shape.point(at: t)
                let tail = shape.point(at: tailT)
                var path = Path()
                path.move(to: tail)
                for segment in 1...6 {
                    path.addLine(to: shape.point(at: tailT + (t-tailT)*CGFloat(segment)/6))
                }
                // A bounded soft under-stroke avoids per-frame blur filters.
                context.stroke(path, with: .color(palette.pale.opacity(0.055*envelope)), lineWidth: 2.1*u)
                context.stroke(path, with: .linearGradient(Gradient(colors: [.clear, palette.bright.opacity(0.68*envelope)]), startPoint: tail, endPoint: head), lineWidth: 0.80*u)
                dot(head, radius: 0.95*u, color: palette.bright.opacity(0.72*envelope), context: &context)
                // The glints sit on the exact parent/fork junctions.
                for junction in [CGFloat(0.42), 0.55, 0.68] {
                    let glint = Double(max(0, 1-abs(t-junction)/0.045)) * envelope
                    if glint > 0.001 {
                        dot(shape.point(at: junction), radius: 1.25*u, color: palette.bright.opacity(0.45*glint), context: &context)
                    }
                }
            }
        }
    }

    static func drawBeams(context: inout GraphicsContext, size: CGSize, radius r: CGFloat, palette: Palette) {
        guard r > 0 else { return }
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let u = r / 50
        for side in [-1, 1] {
            let sign = CGFloat(side)
            for i in 0..<24 {
                let seed = i + (side == -1 ? 500 : 900)
                let shape = beam(index: i, side: side, size: size, radius: r)
                let start = shape.start, end = shape.end
                let p1 = shape.control1, p2 = shape.control2
                let major = i % 5 == 0
                let alpha = 0.35 * (major ? 1 : Double(0.30 + noise(seed+9)*0.35))
                var path = Path()
                path.move(to: start)
                path.addCurve(to: end, control1: p1, control2: p2)
                let gradient = Gradient(stops: [
                    .init(color: palette.pale.opacity(alpha*0.3), location: 0),
                    .init(color: palette.beam.opacity(alpha), location: 0.26),
                    .init(color: palette.pale.opacity(alpha*0.70), location: 0.60),
                    .init(color: palette.silver.opacity(alpha*0.16), location: 0.88),
                    .init(color: .clear, location: 1)
                ])
                let shading = GraphicsContext.Shading.linearGradient(gradient, startPoint: start, endPoint: end)
                context.stroke(path, with: shading, lineWidth: (major ? 0.64 : 0.33)*u)
                if major {
                    var glow = context
                    glow.addFilter(.blur(radius: 1.8*u))
                    glow.stroke(path, with: shading, lineWidth: 1.1*u)
                }
                for j in 0..<3 {
                    let root = cubic(start, p1, p2, end, 0.42 + CGFloat(j)*0.13)
                    let tip = CGPoint(x: root.x + sign*r*(0.45 + noise(seed+j+50)*0.30), y: root.y + (noise(seed+j+60)-0.5)*r*0.65)
                    let control = CGPoint(x: root.x + sign*r*0.32, y: tip.y)
                    var fork = Path()
                    fork.move(to: root)
                    fork.addQuadCurve(to: tip, control: control)
                    context.stroke(fork, with: .linearGradient(Gradient(colors: [palette.pale.opacity(alpha*0.65), .clear]), startPoint: root, endPoint: tip), lineWidth: 0.32*u)
                    if i % 2 == 0 {
                        let q = CGPoint(x: 0.25*root.x + 0.5*control.x + 0.25*tip.x, y: 0.25*root.y + 0.5*control.y + 0.25*tip.y)
                        let end2 = CGPoint(x: q.x + sign*r*0.22, y: q.y + (noise(seed+j+70)-0.5)*r*0.26)
                        var twig = Path()
                        twig.move(to: q)
                        twig.addQuadCurve(to: end2, control: CGPoint(x: q.x + sign*r*0.12, y: end2.y))
                        context.stroke(twig, with: .linearGradient(Gradient(colors: [palette.pale.opacity(alpha*0.5), .clear]), startPoint: q, endPoint: end2), lineWidth: 0.27*u)
                        dot(q, radius: 0.40*u, color: palette.beam.opacity(0.30), context: &context)
                    }
                    if major {
                        dot(root, radius: 0.43*u, color: palette.white.opacity(0.27), context: &context)
                    }
                }
            }
            for i in 0..<18 {
                let seed = i + (side == -1 ? 1800 : 2200)
                let p = CGPoint(x: c.x + sign*r*(1.15 + noise(seed)*(size.width/(2*r)-1.4)), y: c.y + (noise(seed+90)-0.5)*r*0.78*2)
                dot(p, radius: (0.18 + noise(seed+7)*0.30)*u, color: palette.pale.opacity(Double(0.10 + noise(seed+9)*0.22)), context: &context)
            }
        }
    }

    static func drawShell(context: inout GraphicsContext, center c: CGPoint, radius r: CGFloat, palette: Palette) {
        guard r > 0 else { return }
        let u = r / 50
        for i in 0..<112 {
            let angle = CGFloat(i)/112 * .pi*2
            let inner: CGFloat = 0.34 + noise(i+3100)*0.30
            let outer: CGFloat = 0.84 + noise(i+3200)*0.22
            var points: [CGPoint] = []
            points.reserveCapacity(8)
            for j in 0...7 {
                let t = CGFloat(j)/7
                let a = angle + sin(t*4.3 + CGFloat(i))*0.12 + (noise(i*31+j+17)-0.5)*0.075
                let rr = r*(inner + (outer-inner)*t)
                points.append(CGPoint(x: c.x + cos(a)*rr, y: c.y + sin(a)*rr))
            }
            var path = Path()
            path.addLines(points)
            context.stroke(path, with: .color(palette.pale.opacity(Double(0.26 + noise(i+99)*0.28))), lineWidth: (i % 7 == 0 ? 0.64 : 0.34)*u)
            let p = points[4]
            let a = angle + 0.10 + noise(i+110)*0.20
            let q = CGPoint(x: c.x + cos(a)*r*outer, y: c.y + sin(a)*r*outer)
            var branch = Path()
            branch.move(to: p)
            branch.addLine(to: CGPoint(x: (p.x+q.x)*0.5 + 2*u, y: (p.y+q.y)*0.5 - u))
            branch.addLine(to: q)
            context.stroke(branch, with: .color(palette.pale.opacity(0.30)), lineWidth: 0.29*u)
            if i % 3 == 0 { dot(points[6], radius: 0.58*u, color: palette.bright.opacity(0.88), context: &context) }
            if i % 11 == 0 {
                var halo = context
                halo.addFilter(.blur(radius: 1.3*u))
                dot(p, radius: 2*u, color: palette.white.opacity(0.33), context: &halo)
                dot(p, radius: 0.90*u, color: palette.bright.opacity(0.98), context: &context)
            }
        }
    }

    private static func dot(_ p: CGPoint, radius: CGFloat, color: Color, context: inout GraphicsContext) {
        context.fill(Path(ellipseIn: CGRect(x: p.x-radius, y: p.y-radius, width: radius*2, height: radius*2)), with: .color(color))
    }
}
