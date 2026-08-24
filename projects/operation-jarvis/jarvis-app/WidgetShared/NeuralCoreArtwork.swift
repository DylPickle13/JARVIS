import SwiftUI
import WidgetKit
import JARVISKit

enum JARVISNeuralCoreLayout {
    case phone
    case watch

    var radiusFactor: CGFloat { self == .watch ? 0.305 : 0.325 }
    var lineScale: CGFloat { self == .watch ? 0.72 : 1 }
    var detailScale: CGFloat { self == .watch ? 0.66 : 1 }
    var latitudeCount: Int { self == .watch ? 7 : 11 }
    var longitudeCount: Int { self == .watch ? 8 : 13 }
    var filamentCount: Int { self == .watch ? 54 : 92 }
    var particleCount: Int { self == .watch ? 42 : 78 }
    var rayCount: Int { self == .watch ? 18 : 28 }
    var columnCount: Int { self == .watch ? 7 : 11 }
}

/// Shared native-vector artwork for the iPhone medium widget and Watch Modular
/// middle complication. WidgetKit may animate it only while transitioning
/// between real timeline entries; every resulting frame is a finished static
/// Monochrome Cathedral composition.
struct JARVISNeuralCoreArtwork: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let motionPhase: Double
    let allowsMotion: Bool

    @Environment(\.widgetRenderingMode) private var renderingMode
    @Environment(\.isLuminanceReduced) private var isLuminanceReduced
    @Environment(\.accessibilityReduceMotion) private var accessibilityReduceMotion

    private var usesFullColor: Bool {
        // Do not author an extra Always-On luminance reduction. The system owns
        // actual display luminance; this flag only follows the rendering mode.
        renderingMode == .fullColor
    }

    private var motionEnabled: Bool {
        allowsMotion
            && !telemetry.signalLost
            && !isLuminanceReduced
            && !accessibilityReduceMotion
    }

    private var renderedPhase: Double {
        telemetry.signalLost || !allowsMotion
            ? JARVISNeuralCoreMotion.staticPhase
            : motionPhase
    }

    private var palette: JARVISMonochromeCathedralPalette {
        JARVISMonochromeCathedralPalette(usesFullColor: usesFullColor)
    }

    var body: some View {
        GeometryReader { geometry in
            let phase = CGFloat(renderedPhase)
            let rotation = sin(phase * .pi * 2) * 2.4
            let breathingScale = 1 + cos(phase * .pi * 6) * 0.012

            ZStack(alignment: .topLeading) {
                ZStack {
                    JARVISMonochromeCathedralCanvas(
                        telemetry: telemetry,
                        layout: layout,
                        phase: phase,
                        palette: palette
                    )

                    if !telemetry.signalLost {
                        JARVISNeuralImpulseLayer(
                            telemetry: telemetry,
                            layout: layout,
                            phase: phase,
                            palette: palette,
                            motionEnabled: motionEnabled
                        )

                        JARVISReactorMotionLayer(
                            telemetry: telemetry,
                            layout: layout,
                            phase: phase,
                            palette: palette,
                            motionEnabled: motionEnabled
                        )
                    }
                }
                .rotationEffect(.degrees(rotation))
                .scaleEffect(breathingScale)
                .contentTransition(.interpolate)
                .widgetAccentable()

                Text("JARVIS")
                    .font(.system(
                        size: layout == .watch ? 9 : 15,
                        weight: .bold,
                        design: .default
                    ))
                    .tracking(layout == .watch ? 1.1 : 2.2)
                    .foregroundStyle(palette.bright)
                    .padding(.leading, layout == .watch ? 7 : 2)
                    .padding(.top, layout == .watch ? 6 : 4)
                    .widgetAccentable()
            }
            .clipped()
            .animation(
                motionEnabled
                    ? .linear(duration: JARVISNeuralCoreMotion.transitionDuration)
                    : nil,
                value: renderedPhase
            )
            .transaction { transaction in
                if !motionEnabled {
                    transaction.disablesAnimations = true
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(accessibilityLabel)
            .accessibilityHint(layout == .phone ? "Opens JARVIS Home" : "Opens the JARVIS Pi terminal")
        }
    }

    private var accessibilityLabel: String {
        guard !telemetry.signalLost else { return "JARVIS, signal lost" }
        var values = ["JARVIS online"]
        if let sessions = telemetry.piSessions {
            values.append("\(sessions) active Pi \(sessions == 1 ? "session" : "sessions")")
        }
        let plugsOn = telemetry.plugStates.filter { $0 == .on }.count
        values.append("\(plugsOn) plugs on")
        if let quota = telemetry.codexRemainingPercent {
            values.append("Codex \(Int(quota.rounded())) percent remaining")
        }
        if let pm25 = telemetry.pm25 {
            values.append("PM 2.5 is \(pm25)")
        }
        return values.joined(separator: ", ")
    }
}

private struct JARVISMonochromeCathedralPalette {
    let bright: Color
    let pale: Color
    let silver: Color
    let cool: Color
    let dim: Color
    let veryDim: Color
    let quotaNormal: Color
    let quotaBoundary: Color
    let critical: Color

    init(usesFullColor: Bool) {
        if usesFullColor {
            bright = Color(white: 0.98)
            pale = Color(white: 0.80)
            silver = Color(white: 0.62)
            cool = Color(red: 0.76, green: 0.82, blue: 0.86)
            dim = Color(white: 0.31)
            veryDim = Color(white: 0.18)
            quotaNormal = Color(white: 0.80)
            quotaBoundary = Color(red: 0.26, green: 0.48, blue: 1.00)
            critical = Color(red: 1.00, green: 0.22, blue: 0.27)
        } else {
            bright = .primary
            pale = .primary.opacity(0.82)
            silver = .primary.opacity(0.64)
            cool = .primary.opacity(0.72)
            dim = .secondary.opacity(0.56)
            veryDim = .secondary.opacity(0.30)
            quotaNormal = .primary
            quotaBoundary = .primary
            critical = .primary
        }
    }
}

private struct JARVISMonochromeCathedralCanvas: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let phase: CGFloat
    let palette: JARVISMonochromeCathedralPalette

    var body: some View {
        Canvas { context, size in
            let center = CGPoint(x: size.width * 0.5, y: size.height * 0.5)
            let radius = min(size.height * layout.radiusFactor, size.width * 0.22)

            drawHalo(context: &context, center: center, radius: radius)
            drawCathedralArchitecture(context: &context, center: center, radius: radius)
            drawWireframe(context: &context, center: center, radius: radius)
            drawFilaments(context: &context, center: center, radius: radius)
            drawColumns(context: &context, center: center, radius: radius)
            drawRadialCrown(context: &context, center: center, radius: radius)
            drawParticles(context: &context, center: center, radius: radius)
            drawPlugAnchors(context: &context, center: center, radius: radius)
            drawQuotaArc(context: &context, center: center, radius: radius)
            drawCore(context: &context, center: center, radius: radius)
        }
    }

    private var signalMultiplier: Double {
        telemetry.signalLost ? 0.38 : 1
    }

    private var sessionEnergy: CGFloat {
        CGFloat(telemetry.illuminatedSpokes) / 8
    }

    private func drawHalo(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let haloRadius = radius * 1.12
        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: haloRadius)),
            with: .color(palette.bright.opacity(telemetry.signalLost ? 0.008 : 0.018))
        )
        context.stroke(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: radius * 1.02)),
            with: .color(palette.silver.opacity(0.20 * signalMultiplier)),
            lineWidth: 1.5 * layout.lineScale
        )
    }

    private func drawCathedralArchitecture(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let wave = sin(phase * .pi * 4)
        stroke(
            JARVISCathedralGeometry.arcPoints(
                center: center,
                radius: radius * 1.54,
                start: .pi * (1.17 + wave * 0.012),
                end: .pi * (1.83 - wave * 0.012),
                segments: layout == .watch ? 34 : 64
            ),
            context: &context,
            color: palette.bright.opacity(0.44 * signalMultiplier),
            width: 4.0 * layout.lineScale
        )
        stroke(
            JARVISCathedralGeometry.arcPoints(
                center: center,
                radius: radius * 1.43,
                start: .pi * (1.22 - wave * 0.010),
                end: .pi * (1.78 + wave * 0.010),
                segments: layout == .watch ? 30 : 56
            ),
            context: &context,
            color: palette.silver.opacity(0.34 * signalMultiplier),
            width: 1.8 * layout.lineScale
        )
        stroke(
            JARVISCathedralGeometry.arcPoints(
                center: center,
                radius: radius * 1.54,
                start: .pi * 0.17,
                end: .pi * 0.83,
                segments: layout == .watch ? 34 : 64
            ),
            context: &context,
            color: palette.silver.opacity(0.25 * signalMultiplier),
            width: 1.2 * layout.lineScale
        )

        stroke(
            JARVISCathedralGeometry.rotatedEllipsePoints(
                center: center,
                radiusX: radius * 1.56,
                radiusY: radius * 0.18,
                rotation: sin(phase * .pi * 2) * 0.025,
                segments: layout == .watch ? 46 : 82
            ),
            context: &context,
            color: palette.silver.opacity(0.30 * signalMultiplier),
            width: 0.8 * layout.lineScale
        )
        stroke(
            JARVISCathedralGeometry.rotatedEllipsePoints(
                center: center,
                radiusX: radius * 1.24,
                radiusY: radius * 0.34,
                rotation: .pi / 3 + sin(phase * .pi * 2 + 1.3) * 0.06,
                segments: layout == .watch ? 38 : 72
            ),
            context: &context,
            color: palette.cool.opacity(0.20 * signalMultiplier),
            width: 0.7 * layout.lineScale
        )
        stroke(
            JARVISCathedralGeometry.rotatedEllipsePoints(
                center: center,
                radiusX: radius * 1.18,
                radiusY: radius * 0.31,
                rotation: -.pi / 3 - sin(phase * .pi * 2 + 0.5) * 0.05,
                segments: layout == .watch ? 38 : 72
            ),
            context: &context,
            color: palette.silver.opacity(0.18 * signalMultiplier),
            width: 0.62 * layout.lineScale
        )
    }

    private func drawWireframe(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        for index in 0..<layout.latitudeCount {
            let normalized = CGFloat(index) / CGFloat(layout.latitudeCount - 1) * 2 - 1
            let y = center.y + normalized * radius * 0.82
            let width = max(2, radius * sqrt(max(0, 1 - normalized * normalized)))
            let height = max(1, radius * (0.055 + (1 - abs(normalized)) * 0.035))
            let highlight = 0.5 + 0.5 * sin(phase * .pi * 4 - CGFloat(index) * 0.72)
            stroke(
                JARVISCathedralGeometry.rotatedEllipsePoints(
                    center: CGPoint(x: center.x, y: y),
                    radiusX: width,
                    radiusY: height,
                    rotation: sin(phase * .pi * 2 + CGFloat(index) * 0.7) * 0.018,
                    segments: layout == .watch ? 24 : 46
                ),
                context: &context,
                color: palette.pale.opacity((0.12 + Double(highlight) * 0.15) * signalMultiplier),
                width: (index == layout.latitudeCount / 2 ? 1.1 : 0.58) * layout.lineScale
            )
        }

        for index in 0..<layout.longitudeCount {
            let angle = CGFloat(index) / CGFloat(layout.longitudeCount) * .pi
            let width = radius * (0.12 + 0.84 * abs(sin(angle + phase * 0.38)))
            stroke(
                JARVISCathedralGeometry.rotatedEllipsePoints(
                    center: center,
                    radiusX: width,
                    radiusY: radius,
                    rotation: cos(angle + phase * 0.50) * 0.10,
                    segments: layout == .watch ? 34 : 64
                ),
                context: &context,
                color: palette.silver.opacity((0.11 + Double(JARVISCathedralGeometry.pseudo(index + 40)) * 0.15) * signalMultiplier),
                width: (index % 4 == 0 ? 0.9 : 0.52) * layout.lineScale
            )
        }
    }

    private func drawFilaments(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        for index in 0..<layout.filamentCount {
            if telemetry.signalLost && index % 3 == 0 { continue }
            let filament = JARVISCathedralGeometry.filament(index: index, center: center, radius: radius)
            let lane = index % 8
            let energized = !telemetry.signalLost && lane < telemetry.illuminatedSpokes
            let wave = pow(max(0, cos(phase * .pi * 4 - JARVISCathedralGeometry.pseudo(index + 1720) * .pi * 2)), 10)
            let opacity = telemetry.signalLost
                ? 0.075 + Double(JARVISCathedralGeometry.pseudo(index + 1880)) * 0.08
                : energized
                    ? 0.20 + Double(wave) * 0.48
                    : 0.09 + Double(JARVISCathedralGeometry.pseudo(index + 1880)) * 0.10
            let color = energized && wave > 0.35
                ? palette.bright
                : (index % 3 == 0 ? palette.cool : palette.silver)
            let width = (index % 11 == 0 ? 1.15 : 0.50) * layout.lineScale

            if telemetry.signalLost {
                let points = filament.sampledPoints(count: layout == .watch ? 8 : 12)
                let gapStart = max(2, points.count / 2 - 1)
                let gapEnd = min(points.count - 2, gapStart + 2)
                stroke(Array(points[0...gapStart]), context: &context, color: color.opacity(opacity), width: width)
                stroke(Array(points[gapEnd...]), context: &context, color: color.opacity(opacity), width: width)
            } else {
                var path = Path()
                path.move(to: filament.start)
                path.addQuadCurve(to: filament.end, control: filament.control)
                context.stroke(
                    path,
                    with: .color(color.opacity(opacity)),
                    style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
                )
            }
        }
    }

    private func drawColumns(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        for index in 0..<layout.columnCount {
            let normalized = CGFloat(index) / CGFloat(layout.columnCount - 1) * 2 - 1
            let x = center.x + normalized * radius * 0.82
            let bow = sin((normalized + 1) * .pi / 2) * radius * 0.12
            let shimmer = telemetry.signalLost
                ? 0.10
                : 0.20 + Double(pow(max(0, cos(phase * .pi * 4 - CGFloat(index) * 0.66)), 8)) * 0.30
            stroke(
                [
                    CGPoint(x: x, y: center.y - radius * 0.88),
                    CGPoint(x: x - normalized * bow, y: center.y),
                    CGPoint(x: x, y: center.y + radius * 0.88),
                ],
                context: &context,
                color: palette.bright.opacity(shimmer),
                width: (index == layout.columnCount / 2 ? 1.05 : 0.58) * layout.lineScale
            )
        }
    }

    private func drawRadialCrown(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let focusPhase = JARVISCathedralGeometry.fraction(phase * 2)
        for index in 0..<layout.rayCount {
            let unit = CGFloat(index) / CGFloat(layout.rayCount)
            let angle = unit * .pi * 2 + sin(phase * .pi * 4 + CGFloat(index) * 0.45) * 0.018
            let inner = radius * (0.83 + JARVISCathedralGeometry.pseudo(index + 2300) * 0.10)
            let outer = radius * (1.08 + JARVISCathedralGeometry.pseudo(index + 2520) * (layout == .watch ? 0.26 : 0.38))
            let focus = telemetry.signalLost
                ? 0
                : exp(-pow(JARVISCathedralGeometry.circularDistance(unit, focusPhase) * 10, 2))
            let opacity = (0.20 + Double(JARVISCathedralGeometry.pseudo(index + 2710)) * 0.22 + Double(focus) * 0.48) * signalMultiplier
            let start = CGPoint(
                x: center.x + cos(angle) * inner,
                y: center.y + sin(angle) * inner * 0.90
            )
            let end = CGPoint(
                x: center.x + cos(angle + 0.02) * outer,
                y: center.y + sin(angle + 0.02) * outer * 0.90
            )
            stroke(
                [start, end],
                context: &context,
                color: (focus > 0.25 ? palette.bright : palette.silver).opacity(opacity),
                width: (index % 5 == 0 ? 1.35 : 0.64) * layout.lineScale
            )
            if index % 2 == 0 {
                let dotRadius = (0.8 + JARVISCathedralGeometry.pseudo(index + 2880) * 1.8) * layout.detailScale
                context.fill(
                    Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: end, radius: dotRadius)),
                    with: .color((focus > 0.25 ? palette.bright : palette.pale).opacity(opacity))
                )
            }
        }
    }

    private func drawParticles(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let count = telemetry.signalLost ? layout.particleCount / 2 : layout.particleCount
        let energy = 0.35 + sessionEnergy * 0.65
        for index in 0..<count {
            let baseAngle = JARVISCathedralGeometry.pseudo(index + 3100) * .pi * 2
            let direction: CGFloat = JARVISCathedralGeometry.pseudo(index + 3290) > 0.5 ? 1 : -1
            let orbit = index % 8 == 0
                ? direction * phase * .pi * 2
                : direction * sin(phase * .pi * 4 + JARVISCathedralGeometry.pseudo(index + 3500) * .pi * 2) * 0.11
            let angle = baseAngle + (telemetry.signalLost ? 0 : orbit)
            let radialWave = telemetry.signalLost
                ? 0
                : sin(phase * .pi * 6 + JARVISCathedralGeometry.pseudo(index + 3720) * .pi * 2)
            let distance = radius * (
                0.98
                    + JARVISCathedralGeometry.pseudo(index + 3950) * (layout == .watch ? 0.44 : 0.55)
                    + radialWave * 0.025
            )
            let point = CGPoint(
                x: center.x + cos(angle) * distance,
                y: center.y + sin(angle) * distance * 0.86
            )
            let twinkle = telemetry.signalLost
                ? 0.18
                : (0.30 + pow(0.5 + 0.5 * sin(phase * .pi * 6 + JARVISCathedralGeometry.pseudo(index + 4200) * .pi * 2), 4) * 0.70) * energy
            let particleRadius = (0.45 + JARVISCathedralGeometry.pseudo(index + 4400) * 1.65) * layout.detailScale
            context.fill(
                Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: point, radius: particleRadius)),
                with: .color((index % 5 == 0 ? palette.bright : palette.pale).opacity(Double(twinkle) * signalMultiplier))
            )
        }
    }

    private func drawPlugAnchors(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        for index in 0..<4 {
            let angle = CGFloat(index) * .pi / 2
            let start = CGPoint(
                x: center.x + cos(angle) * radius * 0.88,
                y: center.y + sin(angle) * radius * 0.88
            )
            let end = CGPoint(
                x: center.x + cos(angle) * radius * 1.17,
                y: center.y + sin(angle) * radius * 1.17
            )
            let state = telemetry.plugStates.indices.contains(index) ? telemetry.plugStates[index] : .unknown
            let color: Color
            let opacity: Double
            switch state {
            case .on:
                color = palette.bright
                opacity = telemetry.signalLost ? 0.15 : 0.92
            case .off:
                color = palette.silver
                opacity = telemetry.signalLost ? 0.12 : 0.46
            case .unknown:
                color = palette.veryDim
                opacity = 0.34
            }
            stroke([start, end], context: &context, color: color.opacity(opacity), width: 1.0 * layout.lineScale)
            let nodeRadius = (state == .on ? 2.2 : 1.55) * layout.detailScale
            context.fill(
                Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: end, radius: nodeRadius)),
                with: .color(color.opacity(opacity))
            )
        }
    }

    private func drawQuotaArc(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        guard !telemetry.signalLost, let remaining = telemetry.codexRemainingPercent else { return }
        let progress = CGFloat(min(max(remaining / 100, 0), 1))
        guard progress > 0 else { return }
        let isBoundary = abs(remaining - 30) < 0.000_001
        let color = telemetry.codexIsCritical
            ? palette.critical
            : (isBoundary ? palette.quotaBoundary : palette.quotaNormal)
        let emphasis = telemetry.codexIsCritical || isBoundary
        stroke(
            JARVISCathedralGeometry.arcPoints(
                center: center,
                radius: radius * 1.34,
                start: -.pi / 2,
                end: -.pi / 2 + .pi * 2 * progress,
                segments: max(8, Int(72 * progress))
            ),
            context: &context,
            color: color.opacity(emphasis ? 0.90 : 0.52),
            width: (emphasis ? 1.35 : 0.88) * layout.lineScale
        )
    }

    private func drawCore(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let coreRadius = radius * 0.27
        let strength = coreStrength
        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: coreRadius * 1.72)),
            with: .color(palette.bright.opacity(0.025 * strength))
        )
        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: coreRadius)),
            with: .color(palette.silver.opacity(0.035 * strength))
        )
        context.stroke(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: coreRadius)),
            with: .color(palette.bright.opacity(0.76 * strength)),
            lineWidth: 1.7 * layout.lineScale
        )
        context.stroke(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: coreRadius * 0.70)),
            with: .color(palette.pale.opacity(0.74 * strength)),
            lineWidth: 0.95 * layout.lineScale
        )
        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: coreRadius * 0.31)),
            with: .color(palette.bright.opacity(0.82 * strength))
        )
    }

    private var coreStrength: Double {
        guard !telemetry.signalLost else { return 0.34 }
        guard let pm25 = telemetry.pm25 else { return 0.58 }
        switch pm25 {
        case ...12: return 1.0
        case 13...35: return 0.82
        case 36...55: return 0.66
        default: return 0.50
        }
    }

    private func stroke(
        _ points: [CGPoint],
        context: inout GraphicsContext,
        color: Color,
        width: CGFloat
    ) {
        guard let first = points.first else { return }
        var path = Path()
        path.move(to: first)
        for point in points.dropFirst() { path.addLine(to: point) }
        context.stroke(
            path,
            with: .color(color),
            style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
        )
    }
}

private struct JARVISNeuralImpulseLayer: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let phase: CGFloat
    let palette: JARVISMonochromeCathedralPalette
    let motionEnabled: Bool

    private var impulseCount: Int {
        let base = layout == .watch ? 2 : 4
        let perSpoke = layout == .watch ? 1 : 2
        return min(layout == .watch ? 10 : 20, base + telemetry.illuminatedSpokes * perSpoke)
    }

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let center = CGPoint(x: size.width * 0.5, y: size.height * 0.5)
            let radius = min(size.height * layout.radiusFactor, size.width * 0.22)

            ZStack {
                ForEach(0..<impulseCount, id: \.self) { impulseIndex in
                    let filamentIndex = (impulseIndex * 7 + 3) % layout.filamentCount
                    let filament = JARVISCathedralGeometry.filament(
                        index: filamentIndex,
                        center: center,
                        radius: radius
                    )
                    let speed: CGFloat = JARVISCathedralGeometry.pseudo(impulseIndex + 2010) > 0.5 ? 3 : 1
                    let progress = JARVISCathedralGeometry.fraction(
                        phase * speed + JARVISCathedralGeometry.pseudo(impulseIndex + 2140)
                    )
                    let forward = JARVISCathedralGeometry.pseudo(impulseIndex + 2250) > 0.5
                    let headProgress = forward ? progress : 1 - progress
                    let trailCount = layout == .watch ? 3 : 5

                    ForEach(0...trailCount, id: \.self) { trailIndex in
                        let delta = CGFloat(trailIndex) * (layout == .watch ? 0.050 : 0.038)
                        let pathProgress = forward ? headProgress - delta : headProgress + delta
                        if pathProgress >= 0, pathProgress <= 1 {
                            let point = filament.point(at: pathProgress)
                            let strength = pow(
                                1 - CGFloat(trailIndex) / CGFloat(trailCount + 1),
                                2
                            )
                            let diameter = (trailIndex == 0 ? 3.4 : 1.5) * layout.detailScale

                            Circle()
                                .fill(palette.bright.opacity(Double(strength) * 0.95))
                                .frame(width: diameter, height: diameter)
                                .shadow(
                                    color: palette.bright.opacity(trailIndex == 0 ? 0.46 : 0.14),
                                    radius: trailIndex == 0 ? (layout == .watch ? 1.5 : 3) : 1
                                )
                                .position(point)
                        }
                    }

                    let arrival = pow(max(0, (progress - 0.76) / 0.24), 3)
                    if arrival > 0.01 {
                        let target = forward ? filament.end : filament.start
                        Circle()
                            .fill(palette.bright.opacity(Double(arrival) * 0.98))
                            .frame(
                                width: (3.8 + arrival * 3.0) * layout.detailScale,
                                height: (3.8 + arrival * 3.0) * layout.detailScale
                            )
                            .shadow(color: palette.bright.opacity(0.50), radius: layout == .watch ? 2 : 4)
                            .position(target)
                    }
                }
            }
            .animation(
                motionEnabled
                    ? .linear(duration: JARVISNeuralCoreMotion.transitionDuration)
                    : nil,
                value: phase
            )
        }
    }
}

private struct JARVISReactorMotionLayer: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let phase: CGFloat
    let palette: JARVISMonochromeCathedralPalette
    let motionEnabled: Bool

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let center = CGPoint(x: size.width * 0.5, y: size.height * 0.5)
            let radius = min(size.height * layout.radiusFactor, size.width * 0.22)
            let coreRadius = radius * 0.27
            let corePulse = 0.97 + sin(phase * .pi * 6 - .pi / 2) * 0.065

            ZStack {
                ForEach(0..<3, id: \.self) { waveIndex in
                    let discharge = JARVISCathedralGeometry.fraction(
                        phase * 3 + CGFloat(waveIndex) / 3
                    )
                    let envelope = max(0, sin(discharge * .pi) * (1 - discharge))
                    let waveDiameter = radius * (0.60 + discharge * 1.44)

                    Circle()
                        .stroke(
                            palette.bright.opacity(Double(envelope) * 0.26),
                            lineWidth: (1.20 - discharge * 0.50) * layout.lineScale
                        )
                        .frame(width: waveDiameter, height: waveDiameter)
                        .position(center)
                }

                Circle()
                    .trim(from: 0, to: 0.095)
                    .stroke(
                        palette.bright.opacity(0.78),
                        style: StrokeStyle(
                            lineWidth: 1.65 * layout.lineScale,
                            lineCap: .round
                        )
                    )
                    .frame(width: radius * 2.44, height: radius * 2.44)
                    .rotationEffect(.degrees(Double(phase * 720 - 12)))
                    .position(center)

                Circle()
                    .trim(from: 0, to: 0.28)
                    .stroke(
                        palette.bright.opacity(0.92),
                        style: StrokeStyle(
                            lineWidth: 2.0 * layout.lineScale,
                            lineCap: .round
                        )
                    )
                    .frame(width: coreRadius * 2.32, height: coreRadius * 2.32)
                    .rotationEffect(.degrees(Double(phase * 720 + 10)))
                    .position(center)

                Circle()
                    .fill(palette.bright.opacity(0.055))
                    .frame(width: coreRadius * 3.5, height: coreRadius * 3.5)
                    .scaleEffect(corePulse)
                    .position(center)
            }
            .animation(
                motionEnabled
                    ? .easeInOut(duration: JARVISNeuralCoreMotion.transitionDuration)
                    : nil,
                value: phase
            )
        }
    }
}

private struct JARVISCathedralFilament {
    let start: CGPoint
    let control: CGPoint
    let end: CGPoint

    func point(at progress: CGFloat) -> CGPoint {
        let t = min(max(progress, 0), 1)
        let inverse = 1 - t
        return CGPoint(
            x: inverse * inverse * start.x
                + 2 * inverse * t * control.x
                + t * t * end.x,
            y: inverse * inverse * start.y
                + 2 * inverse * t * control.y
                + t * t * end.y
        )
    }

    func sampledPoints(count: Int) -> [CGPoint] {
        (0...count).map { point(at: CGFloat($0) / CGFloat(count)) }
    }
}

private enum JARVISCathedralGeometry {
    static func pseudo(_ seed: Int) -> CGFloat {
        let value = sin(Double(seed) * 12.9898 + 78.233) * 43_758.5453
        return CGFloat(value - floor(value))
    }

    static func fraction(_ value: CGFloat) -> CGFloat {
        value - floor(value)
    }

    static func circularDistance(_ first: CGFloat, _ second: CGFloat) -> CGFloat {
        let distance = abs(first - second).truncatingRemainder(dividingBy: 1)
        return min(distance, 1 - distance)
    }

    static func circleRect(center: CGPoint, radius: CGFloat) -> CGRect {
        CGRect(
            x: center.x - radius,
            y: center.y - radius,
            width: radius * 2,
            height: radius * 2
        )
    }

    static func filament(
        index: Int,
        center: CGPoint,
        radius: CGFloat
    ) -> JARVISCathedralFilament {
        let startAngle = pseudo(index + 120) * .pi * 2
        let endAngle = pseudo(index + 490) * .pi * 2
        let startRadius = radius * (0.50 + pseudo(index + 950) * 0.43)
        let endRadius = radius * (0.50 + pseudo(index + 1250) * 0.43)
        let start = CGPoint(
            x: center.x + cos(startAngle) * startRadius,
            y: center.y + sin(startAngle) * startRadius
        )
        let end = CGPoint(
            x: center.x + cos(endAngle) * endRadius,
            y: center.y + sin(endAngle) * endRadius
        )
        let midpoint = CGPoint(x: (start.x + end.x) / 2, y: (start.y + end.y) / 2)
        let bend = (pseudo(index + 1430) - 0.5) * radius * 0.42
        let control = CGPoint(
            x: midpoint.x + cos(endAngle + .pi / 2) * bend,
            y: midpoint.y + sin(endAngle + .pi / 2) * bend
        )
        return JARVISCathedralFilament(start: start, control: control, end: end)
    }

    static func rotatedEllipsePoints(
        center: CGPoint,
        radiusX: CGFloat,
        radiusY: CGFloat,
        rotation: CGFloat,
        segments: Int
    ) -> [CGPoint] {
        (0...segments).map { index in
            let angle = CGFloat(index) / CGFloat(segments) * .pi * 2
            let x = cos(angle) * radiusX
            let y = sin(angle) * radiusY
            return CGPoint(
                x: center.x + x * cos(rotation) - y * sin(rotation),
                y: center.y + x * sin(rotation) + y * cos(rotation)
            )
        }
    }

    static func arcPoints(
        center: CGPoint,
        radius: CGFloat,
        start: CGFloat,
        end: CGFloat,
        segments: Int
    ) -> [CGPoint] {
        (0...segments).map { index in
            let progress = CGFloat(index) / CGFloat(segments)
            let angle = start + (end - start) * progress
            return CGPoint(
                x: center.x + cos(angle) * radius,
                y: center.y + sin(angle) * radius
            )
        }
    }
}
