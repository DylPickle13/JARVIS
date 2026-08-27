import SwiftUI
import WidgetKit
import JARVISKit

enum JARVISNeuralCoreLayout {
    case phone
    case watch

    /// Both widgets use one canonical Cathedral design. Only the surrounding
    /// surface size and selector cadence differ between iPhone and Watch.
    var radiusFactor: CGFloat { 0.325 }
    var latitudeCount: Int { 11 }
    var longitudeCount: Int { 13 }
    var filamentCount: Int { 92 }
    var particleCount: Int { 78 }
    var rayCount: Int { 28 }
    var columnCount: Int { 11 }

    private var referenceRadius: CGFloat { 50 }

    func visualScale(for radius: CGFloat) -> CGFloat {
        radius / referenceRadius
    }

    func lineScale(for radius: CGFloat) -> CGFloat {
        0.50 * visualScale(for: radius)
    }

    func detailScale(for radius: CGFloat) -> CGFloat {
        0.50 * visualScale(for: radius)
    }

    var continuousFrameCount: Int {
        self == .watch
            ? JARVISNeuralCoreMotion.watchContinuousFrameCount
            : JARVISNeuralCoreMotion.phoneContinuousFrameCount
    }

    /// Use the phone-authored curve quality on both surfaces so the Watch is a
    /// uniform physical scaling of the same artwork rather than a reduced study.
    func curveSegments(watch _: Int, phone: Int) -> Int {
        phone
    }
}

enum JARVISNeuralCoreArtworkLayerSet {
    case complete
    case staticBackground
    case phaseArtwork
}

/// One complete native-vector frame for the iPhone medium widget and Watch
/// rectangular complication. Every phase is independently balanced because
/// the system may freeze or suppress the timer-text frame selector at any time.
struct JARVISNeuralCoreArtwork: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let motionPhase: Double
    let allowsMotion: Bool
    let hidesAccessibility: Bool
    let layerSet: JARVISNeuralCoreArtworkLayerSet
    let includesWordmark: Bool

    init(
        telemetry: JARVISNeuralCoreTelemetry,
        layout: JARVISNeuralCoreLayout,
        motionPhase: Double,
        allowsMotion: Bool,
        hidesAccessibility: Bool = false,
        layerSet: JARVISNeuralCoreArtworkLayerSet = .complete,
        includesWordmark: Bool = true
    ) {
        self.telemetry = telemetry
        self.layout = layout
        self.motionPhase = motionPhase
        self.allowsMotion = allowsMotion
        self.hidesAccessibility = hidesAccessibility
        self.layerSet = layerSet
        self.includesWordmark = includesWordmark
    }

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
        motionEnabled ? motionPhase : JARVISNeuralCoreMotion.staticPhase
    }

    private var palette: JARVISMonochromeCathedralPalette {
        JARVISMonochromeCathedralPalette(usesFullColor: usesFullColor)
    }

    var body: some View {
        GeometryReader { _ in
            let phase = CGFloat(renderedPhase)

            ZStack(alignment: .topLeading) {
                JARVISMonochromeCathedralCanvas(
                    telemetry: telemetry,
                    layout: layout,
                    phase: phase,
                    palette: palette,
                    motionEnabled: motionEnabled,
                    layerSet: layerSet
                )
                .contentTransition(.interpolate)
                .widgetAccentable()

                if includesWordmark {
                    JARVISNeuralCoreWordmark(layout: layout)
                }
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
            .accessibilityLabel(JARVISNeuralCoreAccessibility.label(for: telemetry))
            .accessibilityHint(JARVISNeuralCoreAccessibility.hint(for: layout))
            .accessibilityHidden(hidesAccessibility)
        }
    }
}

/// A lightweight internal frame used by the phone timer-mask stack. The outer
/// continuous artwork owns geometry, animation, transactions, accessibility,
/// and its single wordmark instead of serializing those wrappers 60 times.
struct JARVISNeuralCoreFrameArtwork: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let motionPhase: Double
    let layerSet: JARVISNeuralCoreArtworkLayerSet

    @Environment(\.widgetRenderingMode) private var renderingMode

    private var palette: JARVISMonochromeCathedralPalette {
        JARVISMonochromeCathedralPalette(usesFullColor: renderingMode == .fullColor)
    }

    var body: some View {
        JARVISMonochromeCathedralCanvas(
            telemetry: telemetry,
            layout: layout,
            phase: CGFloat(motionPhase),
            palette: palette,
            motionEnabled: true,
            layerSet: layerSet
        )
        .widgetAccentable(true)
        .clipped()
    }
}

struct JARVISNeuralCoreWordmark: View {
    let layout: JARVISNeuralCoreLayout

    @Environment(\.widgetRenderingMode) private var renderingMode

    private var palette: JARVISMonochromeCathedralPalette {
        JARVISMonochromeCathedralPalette(usesFullColor: renderingMode == .fullColor)
    }

    var body: some View {
        GeometryReader { geometry in
            let radius = min(
                geometry.size.height * layout.radiusFactor,
                geometry.size.width * 0.22
            )
            let scale = layout.visualScale(for: radius)

            Text("JARVIS")
                .font(.system(
                    size: 12 * scale,
                    weight: .bold,
                    design: .default
                ))
                .tracking(1.5 * scale)
                .foregroundStyle(palette.bright)
                .padding(.leading, 15 * scale)
                .padding(.top, 12.5 * scale)
                .widgetAccentable()
                // The brand label is public decoration, never telemetry.
                // Keep it visible if WidgetKit redacts stale snapshots.
                .unredacted()
        }
    }
}

enum JARVISNeuralCoreAccessibility {
    static func label(for telemetry: JARVISNeuralCoreTelemetry) -> String {
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

    static func hint(for layout: JARVISNeuralCoreLayout) -> String {
        layout == .phone ? "Opens JARVIS Home" : "Opens the JARVIS Pi terminal"
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
    let motionEnabled: Bool
    let layerSet: JARVISNeuralCoreArtworkLayerSet

    var body: some View {
        Canvas { context, size in
            let center = CGPoint(x: size.width * 0.5, y: size.height * 0.5)
            let radius = min(size.height * layout.radiusFactor, size.width * 0.22)

            switch layerSet {
            case .complete:
                drawHalo(context: &context, center: center, radius: radius)
                drawCathedralArchitecture(context: &context, center: center, radius: radius)
                drawWireframe(context: &context, center: center, radius: radius)
                drawFilaments(context: &context, center: center, radius: radius)
                drawColumns(context: &context, center: center, radius: radius)
                drawRadialCrown(context: &context, center: center, radius: radius)
                drawParticles(context: &context, center: center, radius: radius)
                drawPlugAnchors(context: &context, center: center, radius: radius)
                drawSegmentedQuotaRing(context: &context, center: center, radius: radius)
                drawReactorDischarges(context: &context, center: center, radius: radius)
                drawCore(context: &context, center: center, radius: radius)
            case .staticBackground:
                // The halo is phase-independent and originally rendered first.
                // Hoisting exactly this layer preserves both pixels and ordering.
                drawHalo(context: &context, center: center, radius: radius)
            case .phaseArtwork:
                // Preserve every phase-driven operation in its original order.
                drawCathedralArchitecture(context: &context, center: center, radius: radius)
                drawWireframe(context: &context, center: center, radius: radius)
                drawFilaments(context: &context, center: center, radius: radius)
                drawColumns(context: &context, center: center, radius: radius)
                drawRadialCrown(context: &context, center: center, radius: radius)
                drawParticles(context: &context, center: center, radius: radius)
                drawPlugAnchors(context: &context, center: center, radius: radius)
                drawSegmentedQuotaRing(context: &context, center: center, radius: radius)
                drawReactorDischarges(context: &context, center: center, radius: radius)
                drawCore(context: &context, center: center, radius: radius)
            }
        }
    }

    private var signalMultiplier: Double {
        telemetry.signalLost ? 0.38 : 1
    }

    private var sessionEnergy: CGFloat {
        CGFloat(telemetry.illuminatedSpokes) / 8
    }

    /// Preserve the approved study's neural density whenever Pi is active while
    /// still scaling the firing field down—and fully off—with real session data.
    private var sessionActivity: CGFloat {
        guard !telemetry.signalLost, telemetry.illuminatedSpokes > 0 else { return 0 }
        return min(1, 0.25 + sessionEnergy * 1.5)
    }

    private func drawHalo(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let haloRadius = radius * 1.08
        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: haloRadius)),
            with: .color(palette.bright.opacity(telemetry.signalLost ? 0.008 : 0.018))
        )
        context.stroke(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: radius * 1.02)),
            with: .color(palette.silver.opacity(0.20 * signalMultiplier)),
            lineWidth: 1.6 * layout.lineScale(for: radius)
        )
    }

    private func drawCathedralArchitecture(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let wave = sin(phase * .pi * 4)
        let primaryArch = JARVISCathedralGeometry.arcPath(
            center: center,
            radius: radius * 1.54,
            start: .pi * (1.17 + wave * 0.012),
            end: .pi * (1.83 - wave * 0.012),
            segments: layout.curveSegments(watch: 34, phone: 36)
        )
        stroke(
            primaryArch,
            context: &context,
            color: palette.bright.opacity(0.10 * signalMultiplier),
            width: 4.2 * layout.lineScale(for: radius)
                + 4.5 * layout.visualScale(for: radius)
        )
        stroke(
            primaryArch,
            context: &context,
            color: palette.bright.opacity(0.40 * signalMultiplier),
            width: 4.2 * layout.lineScale(for: radius)
        )
        stroke(
            JARVISCathedralGeometry.arcPath(
                center: center,
                radius: radius * 1.45,
                start: .pi * (1.22 - wave * 0.010),
                end: .pi * (1.78 + wave * 0.010),
                segments: layout.curveSegments(watch: 30, phone: 34)
            ),
            context: &context,
            color: palette.silver.opacity(0.34 * signalMultiplier),
            width: 2.1 * layout.lineScale(for: radius)
        )
        stroke(
            JARVISCathedralGeometry.arcPath(
                center: center,
                radius: radius * 1.54,
                start: .pi * 0.17,
                end: .pi * 0.83,
                segments: layout.curveSegments(watch: 34, phone: 36)
            ),
            context: &context,
            color: palette.silver.opacity(0.24 * signalMultiplier),
            width: 1.5 * layout.lineScale(for: radius)
        )

        stroke(
            JARVISCathedralGeometry.rotatedEllipsePath(
                center: center,
                radiusX: radius * 1.56,
                radiusY: radius * 0.18,
                rotation: sin(phase * .pi * 2) * 0.025,
                segments: layout.curveSegments(watch: 46, phone: 44)
            ),
            context: &context,
            color: palette.silver.opacity(0.30 * signalMultiplier),
            width: 0.85 * layout.lineScale(for: radius)
        )
        stroke(
            JARVISCathedralGeometry.rotatedEllipsePath(
                center: center,
                radiusX: radius * 1.24,
                radiusY: radius * 0.34,
                rotation: .pi / 3 + sin(phase * .pi * 2 + 1.3) * 0.06,
                segments: layout.curveSegments(watch: 38, phone: 40)
            ),
            context: &context,
            color: palette.cool.opacity(0.20 * signalMultiplier),
            width: 0.72 * layout.lineScale(for: radius)
        )
        stroke(
            JARVISCathedralGeometry.rotatedEllipsePath(
                center: center,
                radiusX: radius * 1.18,
                radiusY: radius * 0.31,
                rotation: -.pi / 3 - sin(phase * .pi * 2 + 0.5) * 0.05,
                segments: layout.curveSegments(watch: 38, phone: 40)
            ),
            context: &context,
            color: palette.silver.opacity(0.18 * signalMultiplier),
            width: 0.65 * layout.lineScale(for: radius)
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
            let width = max(
                4 * layout.visualScale(for: radius),
                radius * sqrt(max(0, 1 - normalized * normalized))
            )
            let height = max(
                2 * layout.visualScale(for: radius),
                radius * (0.055 + (1 - abs(normalized)) * 0.035)
            )
            let highlight = 0.5 + 0.5 * sin(phase * .pi * 4 - CGFloat(index) * 0.72)
            stroke(
                JARVISCathedralGeometry.rotatedEllipsePath(
                    center: CGPoint(x: center.x, y: y),
                    radiusX: width,
                    radiusY: height,
                    rotation: sin(phase * .pi * 2 + CGFloat(index) * 0.7) * 0.018,
                    segments: layout.curveSegments(watch: 24, phone: 26)
                ),
                context: &context,
                color: palette.pale.opacity((0.12 + Double(highlight) * 0.15) * signalMultiplier),
                width: (index == layout.latitudeCount / 2 ? 1.15 : 0.62) * layout.lineScale(for: radius)
            )
        }

        for index in 0..<layout.longitudeCount {
            let angle = CGFloat(index) / CGFloat(layout.longitudeCount) * .pi
            let width = radius * (0.12 + 0.84 * abs(sin(angle + phase * 0.38)))
            stroke(
                JARVISCathedralGeometry.rotatedEllipsePath(
                    center: center,
                    radiusX: width,
                    radiusY: radius,
                    rotation: cos(angle + phase * 0.50) * 0.10,
                    segments: layout.curveSegments(watch: 34, phone: 36)
                ),
                context: &context,
                color: palette.silver.opacity((0.11 + Double(JARVISCathedralGeometry.pseudo(index + 40)) * 0.15) * signalMultiplier),
                width: (index % 4 == 0 ? 0.95 : 0.55) * layout.lineScale(for: radius)
            )
        }
    }

    private func drawFilaments(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let spin = phase * .pi * 2

        for index in 0..<layout.filamentCount {
            if telemetry.signalLost && index % 3 == 0 { continue }

            let filament = JARVISCathedralGeometry.filament(
                index: index,
                center: center,
                radius: radius,
                phase: telemetry.signalLost ? JARVISNeuralCoreMotion.staticPhase : Double(phase)
            )
            let rawTravel = pow(
                max(0, cos(spin * 2 - JARVISCathedralGeometry.pseudo(index + 1720) * .pi * 2)),
                10
            )
            let travel = rawTravel * sessionActivity
            let opacity = telemetry.signalLost
                ? 0.075 + Double(JARVISCathedralGeometry.pseudo(index + 1880)) * 0.08
                : 0.10
                    + Double(JARVISCathedralGeometry.pseudo(index + 1880)) * 0.18
                    + Double(travel) * 0.48
            let color = travel > 0.35
                ? palette.bright
                : (index % 3 == 0 ? palette.cool : palette.silver)
            let width = (index % 11 == 0 ? 1.25 : 0.55) * layout.lineScale(for: radius)
            let points = filament.sampledPoints(
                count: layout.curveSegments(watch: 9, phone: 8)
            )

            if telemetry.signalLost {
                let gapStart = max(2, points.count / 2 - 1)
                let gapEnd = min(points.count - 2, gapStart + 2)
                stroke(Array(points[0...gapStart]), context: &context, color: color.opacity(opacity), width: width)
                stroke(Array(points[gapEnd...]), context: &context, color: color.opacity(opacity), width: width)
            } else {
                if travel > 0.72 {
                    stroke(
                        points,
                        context: &context,
                        color: palette.bright.opacity(0.10),
                        width: width + 4 * layout.visualScale(for: radius)
                    )
                }
                stroke(points, context: &context, color: color.opacity(opacity), width: width)
            }

            guard sessionActivity > 0,
                  index % 2 == 0,
                  JARVISCathedralGeometry.pseudo(index + 2460) <= 0.40 + sessionActivity * 0.60
            else { continue }

            let speed = CGFloat(2 + Int(JARVISCathedralGeometry.pseudo(index + 2010) * 4))
            let progress = JARVISCathedralGeometry.fraction(
                phase * speed + JARVISCathedralGeometry.pseudo(index + 2140)
            )
            let forward = JARVISCathedralGeometry.pseudo(index + 2250) > 0.5
            let headProgress = forward ? progress : 1 - progress
            let firing = pow(max(0, sin(progress * .pi)), 2.2) * sessionActivity
            guard firing > 0.025 else { continue }

            let trailCount = 5
            for trailIndex in stride(from: trailCount, through: 0, by: -1) {
                let delta = CGFloat(trailIndex) * 0.038
                let pathProgress = forward ? headProgress - delta : headProgress + delta
                guard pathProgress >= 0, pathProgress <= 1 else { continue }
                let point = filament.point(at: pathProgress)
                let tailStrength = firing * pow(
                    1 - CGFloat(trailIndex) / CGFloat(trailCount + 1),
                    2
                )
                let dotRadius = (trailIndex == 0 ? 1.75 : 0.85) * layout.detailScale(for: radius)

                if trailIndex == 0 {
                    context.fill(
                        Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                            center: point,
                            radius: dotRadius * 4.8
                        )),
                        with: .color(palette.bright.opacity(Double(tailStrength) * 0.10))
                    )
                }
                context.fill(
                    Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                        center: point,
                        radius: dotRadius
                    )),
                    with: .color(palette.bright.opacity(Double(tailStrength) * 0.92))
                )
            }

            let arrival = pow(max(0, min(1, (progress - 0.78) / 0.22)), 3)
            if arrival > 0.01 {
                let target = forward ? filament.end : filament.start
                let nodeRadius = (
                    1.4 + JARVISCathedralGeometry.pseudo(index + 2370) * 1.3
                ) * layout.detailScale(for: radius)
                context.fill(
                    Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                        center: target,
                        radius: nodeRadius * 3.8
                    )),
                    with: .color(palette.bright.opacity(Double(arrival) * 0.12))
                )
                context.fill(
                    Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                        center: target,
                        radius: nodeRadius
                    )),
                    with: .color(palette.bright.opacity(Double(arrival) * 0.95))
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
                width: (index == layout.columnCount / 2 ? 1.15 : 0.62) * layout.lineScale(for: radius)
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
            let outer = radius * (1.08 + JARVISCathedralGeometry.pseudo(index + 2520) * 0.38)
            let focus = telemetry.signalLost
                ? 0
                : exp(-pow(JARVISCathedralGeometry.circularDistance(unit, focusPhase) * 10, 2))
            let opacity = (0.22 + Double(JARVISCathedralGeometry.pseudo(index + 2710)) * 0.24 + Double(focus) * 0.48) * signalMultiplier
            let start = CGPoint(
                x: center.x + cos(angle) * inner,
                y: center.y + sin(angle) * inner * 0.90
            )
            let end = CGPoint(
                x: center.x + cos(angle + 0.02) * outer,
                y: center.y + sin(angle + 0.02) * outer * 0.90
            )
            let lineWidth = (index % 5 == 0 ? 1.45 : 0.68) * layout.lineScale(for: radius)
            if focus > 0.55 {
                stroke(
                    [start, end],
                    context: &context,
                    color: palette.bright.opacity(0.10),
                    width: lineWidth + 4 * layout.visualScale(for: radius)
                )
            }
            stroke(
                [start, end],
                context: &context,
                color: (focus > 0.25 ? palette.bright : palette.silver).opacity(opacity),
                width: lineWidth
            )
            if index % 2 == 0 {
                let dotRadius = (0.9 + JARVISCathedralGeometry.pseudo(index + 2880) * 2.2) * layout.detailScale(for: radius)
                if focus > 0.48 {
                    context.fill(
                        Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                            center: end,
                            radius: dotRadius * 3
                        )),
                        with: .color(palette.bright.opacity(0.08))
                    )
                }
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
        let energy = telemetry.signalLost ? CGFloat(0.18) : max(0.25, sessionActivity)
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
                    + JARVISCathedralGeometry.pseudo(index + 3950) * 0.55
                    + radialWave * 0.025
            )
            let point = CGPoint(
                x: center.x + cos(angle) * distance,
                y: center.y + sin(angle) * distance * 0.86
            )
            let twinkle = telemetry.signalLost
                ? 0.18
                : (0.30 + pow(0.5 + 0.5 * sin(phase * .pi * 6 + JARVISCathedralGeometry.pseudo(index + 4200) * .pi * 2), 4) * 0.70) * energy
            let particleRadius = (0.55 + JARVISCathedralGeometry.pseudo(index + 4400) * 2.35) * layout.detailScale(for: radius)
            if twinkle > 0.80 {
                context.fill(
                    Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                        center: point,
                        radius: particleRadius * 3.2
                    )),
                    with: .color(palette.bright.opacity(0.055))
                )
            }
            context.fill(
                Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: point, radius: particleRadius)),
                with: .color((index % 5 == 0 ? palette.bright : palette.pale).opacity(Double(twinkle) * 0.82 * signalMultiplier))
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
            stroke([start, end], context: &context, color: color.opacity(opacity), width: 1.0 * layout.lineScale(for: radius))
            let nodeRadius = (state == .on ? 2.2 : 1.55) * layout.detailScale(for: radius)
            context.fill(
                Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: end, radius: nodeRadius)),
                with: .color(color.opacity(opacity))
            )
        }
    }

    private func drawSegmentedQuotaRing(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let segmentCount = 18
        let progress = telemetry.codexRemainingPercent.map {
            CGFloat(min(max($0 / 100, 0), 1))
        }
        let isBoundary = telemetry.codexRemainingPercent.map {
            abs($0 - 30) < 0.000_001
        } ?? false
        let quotaColor = telemetry.codexIsCritical
            ? palette.critical
            : (isBoundary ? palette.quotaBoundary : palette.quotaNormal)
        let runnerPhase = JARVISCathedralGeometry.fraction(phase * 2)
        let offset = motionEnabled ? phase * 20 * .pi / 180 : CGFloat.zero

        for index in 0..<segmentCount {
            let unit = CGFloat(index) / CGFloat(segmentCount)
            let end = -unit * .pi * 2 - offset
            let start = end - (.pi * 2 / CGFloat(segmentCount)) * 0.58
            let carriesQuota = progress.map { unit < $0 } ?? false
            let runner = telemetry.signalLost || !carriesQuota
                ? 0
                : exp(-pow(JARVISCathedralGeometry.circularDistance(unit, runnerPhase) * 9, 2))
            let opacity = telemetry.signalLost
                ? 0.08
                : (carriesQuota ? 0.22 : 0.10) + Double(runner) * 0.55
            let color = carriesQuota ? quotaColor : palette.silver
            let lineWidth = (0.65 + runner * 1.3) * layout.lineScale(for: radius)
            let points = JARVISCathedralGeometry.arcPath(
                center: center,
                radius: radius * 1.07,
                start: start,
                end: end,
                segments: layout.curveSegments(watch: 5, phone: 5)
            )

            if runner > 0.55 {
                stroke(
                    points,
                    context: &context,
                    color: color.opacity(0.10),
                    width: lineWidth + 4 * layout.visualScale(for: radius)
                )
            }
            stroke(
                points,
                context: &context,
                color: color.opacity(opacity),
                width: lineWidth
            )
        }
    }

    private func drawReactorDischarges(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        guard !telemetry.signalLost, telemetry.illuminatedSpokes > 0 else { return }

        for waveIndex in 0..<3 {
            let discharge = JARVISCathedralGeometry.fraction(
                phase * 3 + CGFloat(waveIndex) / 3
            )
            let envelope = max(0, sin(discharge * .pi) * (1 - discharge))
            let dischargeRadius = radius * (0.30 + discharge * 0.72)
            context.stroke(
                Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                    center: center,
                    radius: dischargeRadius
                )),
                with: .color(palette.bright.opacity(Double(envelope) * 0.24)),
                lineWidth: (1.25 - discharge * 0.55) * layout.lineScale(for: radius)
            )
        }

        let scannerEnd = -(phase * 720 - 12) * .pi / 180
        let scannerStart = scannerEnd - 34 * .pi / 180
        let scanner = JARVISCathedralGeometry.arcPath(
            center: center,
            radius: radius * 1.22,
            start: scannerStart,
            end: scannerEnd,
            segments: layout.curveSegments(watch: 10, phone: 10)
        )
        stroke(
            scanner,
            context: &context,
            color: palette.bright.opacity(0.10),
            width: 1.7 * layout.lineScale(for: radius)
                + 4 * layout.visualScale(for: radius)
        )
        stroke(
            scanner,
            context: &context,
            color: palette.bright.opacity(0.72),
            width: 1.7 * layout.lineScale(for: radius)
        )
    }

    private func drawCore(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat
    ) {
        let spin = phase * .pi * 2
        let pulse = motionEnabled
            ? 1 + 0.065 * sin(spin * 3 - .pi / 2)
            : 1
        let coreRadius = radius * 0.27 * pulse
        let strength = coreStrength
        let haloEnergy = motionEnabled ? (sin(spin * 3) + 1) / 2 : 0.5

        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                center: center,
                radius: coreRadius * 1.82
            )),
            with: .color(palette.bright.opacity((0.020 + Double(haloEnergy) * 0.032) * strength))
        )
        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: coreRadius)),
            with: .color(palette.silver.opacity(0.030 * strength))
        )
        context.stroke(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(center: center, radius: coreRadius)),
            with: .color(palette.bright.opacity(0.76 * strength)),
            lineWidth: 1.8 * layout.lineScale(for: radius)
        )
        context.stroke(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                center: center,
                radius: coreRadius * 0.70
            )),
            with: .color(palette.pale.opacity(0.75 * strength)),
            lineWidth: 1.0 * layout.lineScale(for: radius)
        )
        let nucleusEnergy = motionEnabled
            ? 0.72 + 0.20 * sin(spin * 3 - .pi / 2)
            : 0.82
        context.fill(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                center: center,
                radius: coreRadius * 0.31
            )),
            with: .color(palette.bright.opacity(Double(nucleusEnergy) * strength))
        )
        context.stroke(
            Path(ellipseIn: JARVISCathedralGeometry.circleRect(
                center: center,
                radius: coreRadius * 0.31
            )),
            with: .color(palette.bright.opacity(0.94 * strength)),
            lineWidth: 0.9 * layout.lineScale(for: radius)
        )

        let coreSpin = motionEnabled ? phase * .pi * 4 : CGFloat.zero
        drawCoreArc(
            context: &context,
            center: center,
            radius: coreRadius * 1.16,
            startDegrees: 10,
            endDegrees: 112,
            rotation: coreSpin,
            color: palette.bright.opacity(0.90 * strength),
            width: 2.1 * layout.lineScale(for: radius),
            glow: true,
            glowExpansion: 4.5 * layout.visualScale(for: radius)
        )
        drawCoreArc(
            context: &context,
            center: center,
            radius: coreRadius * 1.16,
            startDegrees: 154,
            endDegrees: 237,
            rotation: coreSpin,
            color: palette.dim.opacity(0.72 * strength),
            width: 1.6 * layout.lineScale(for: radius),
            glow: false,
            glowExpansion: 0
        )
        drawCoreArc(
            context: &context,
            center: center,
            radius: coreRadius * 1.16,
            startDegrees: 273,
            endDegrees: 344,
            rotation: coreSpin,
            color: palette.pale.opacity(0.76 * strength),
            width: 1.6 * layout.lineScale(for: radius),
            glow: false,
            glowExpansion: 0
        )
    }

    private func drawCoreArc(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat,
        startDegrees: CGFloat,
        endDegrees: CGFloat,
        rotation: CGFloat,
        color: Color,
        width: CGFloat,
        glow: Bool,
        glowExpansion: CGFloat
    ) {
        // Convert the AppKit motion-study angles into SwiftUI's y-down space.
        let start = -endDegrees * .pi / 180 + rotation
        let end = -startDegrees * .pi / 180 + rotation
        let points = JARVISCathedralGeometry.arcPath(
            center: center,
            radius: radius,
            start: start,
            end: end,
            segments: layout.curveSegments(watch: 12, phone: 12)
        )
        if glow {
            stroke(
                points,
                context: &context,
                color: palette.bright.opacity(0.10),
                width: width + glowExpansion
            )
        }
        stroke(points, context: &context, color: color, width: width)
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
        _ path: Path,
        context: inout GraphicsContext,
        color: Color,
        width: CGFloat
    ) {
        context.stroke(
            path,
            with: .color(color),
            style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
        )
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
    /// Every authored seed is phase-independent. Compute each deterministic
    /// value once per extension process instead of repeating thousands of sine
    /// operations while WidgetKit constructs the frame stack.
    private static let pseudoCache: [CGFloat] = (0..<4_608).map { seed in
        let value = sin(Double(seed) * 12.9898 + 78.233) * 43_758.5453
        return CGFloat(value - floor(value))
    }

    static func pseudo(_ seed: Int) -> CGFloat {
        if pseudoCache.indices.contains(seed) {
            return pseudoCache[seed]
        }
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
        radius: CGFloat,
        phase: Double
    ) -> JARVISCathedralFilament {
        let spin = CGFloat(phase) * .pi * 2
        let startAngle = pseudo(index + 120) * .pi * 2
            + 0.050 * sin(spin * 2 + pseudo(index + 700) * .pi * 2)
        let endAngle = pseudo(index + 490) * .pi * 2
            - 0.045 * sin(spin * 2 + pseudo(index + 810) * .pi * 2)
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

    static func rotatedEllipsePath(
        center: CGPoint,
        radiusX: CGFloat,
        radiusY: CGFloat,
        rotation: CGFloat,
        segments: Int
    ) -> Path {
        let cosine = cos(rotation)
        let sine = sin(rotation)
        var path = Path()
        for index in 0...segments {
            let angle = CGFloat(index) / CGFloat(segments) * .pi * 2
            let x = cos(angle) * radiusX
            let y = sin(angle) * radiusY
            let point = CGPoint(
                x: center.x + x * cosine - y * sine,
                y: center.y + x * sine + y * cosine
            )
            if index == 0 {
                path.move(to: point)
            } else {
                path.addLine(to: point)
            }
        }
        return path
    }

    static func arcPath(
        center: CGPoint,
        radius: CGFloat,
        start: CGFloat,
        end: CGFloat,
        segments: Int
    ) -> Path {
        var path = Path()
        for index in 0...segments {
            let progress = CGFloat(index) / CGFloat(segments)
            let angle = start + (end - start) * progress
            let point = CGPoint(
                x: center.x + cos(angle) * radius,
                y: center.y + sin(angle) * radius
            )
            if index == 0 {
                path.move(to: point)
            } else {
                path.addLine(to: point)
            }
        }
        return path
    }
}
