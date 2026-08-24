import SwiftUI
import WidgetKit
import JARVISKit

enum JARVISNeuralCoreLayout {
    case phone
    case watch
}

/// Shared vector artwork for the iPhone medium widget and Watch Modular middle
/// complication. It is intentionally static between real timeline updates.
struct JARVISNeuralCoreArtwork: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout

    @Environment(\.widgetRenderingMode) private var renderingMode
    @Environment(\.isLuminanceReduced) private var isLuminanceReduced

    private var usesFullColor: Bool {
        renderingMode == .fullColor && !isLuminanceReduced
    }

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            ZStack(alignment: .topLeading) {
                JARVISNeuralCoreCanvas(
                    telemetry: telemetry,
                    layout: layout,
                    usesFullColor: usesFullColor
                )
                .widgetAccentable()

                Text("J")
                    .font(.system(size: layout == .watch ? 14 : 27, weight: .bold, design: .rounded))
                    .foregroundStyle(usesFullColor ? Color.white : Color.primary)
                    .position(coreCenter(in: size))

                Text("JARVIS")
                    .font(.system(size: layout == .watch ? 14 : 27, weight: .bold, design: .default))
                    .tracking(layout == .watch ? 1.2 : 3.0)
                    .foregroundStyle(usesFullColor ? Color.white : Color.primary)
                    .frame(width: size.width * (layout == .watch ? 0.55 : 0.58), alignment: .leading)
                    .position(
                        x: size.width * (layout == .watch ? 0.70 : 0.69),
                        y: size.height * (layout == .watch ? 0.22 : 0.25)
                    )

                if telemetry.signalLost {
                    Text("SIGNAL LOST")
                        .font(.system(size: layout == .watch ? 8 : 11, weight: .bold, design: .monospaced))
                        .tracking(layout == .watch ? 0.8 : 1.5)
                        .foregroundStyle(usesFullColor ? Color.orange : Color.secondary)
                        .frame(width: size.width * (layout == .watch ? 0.55 : 0.58), alignment: .leading)
                        .position(
                            x: size.width * (layout == .watch ? 0.70 : 0.69),
                            y: size.height * (layout == .watch ? 0.79 : 0.77)
                        )
                } else if layout == .phone {
                    HStack(spacing: 8) {
                        Text("MAC-MINI-64")
                        if let linkLabel = telemetry.linkLabel {
                            Circle()
                                .fill(usesFullColor ? Color.cyan : Color.primary)
                                .frame(width: 5, height: 5)
                                .widgetAccentable()
                            Text(linkLabel)
                                .foregroundStyle(usesFullColor ? Color.cyan : Color.primary)
                                .widgetAccentable()
                        }
                    }
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .tracking(0.7)
                    .foregroundStyle(usesFullColor ? Color.white.opacity(0.72) : Color.secondary)
                    .frame(width: size.width * 0.58, alignment: .leading)
                    .position(x: size.width * 0.69, y: size.height * 0.78)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(accessibilityLabel)
            .accessibilityHint("Opens the JARVIS Pi terminal")
        }
    }

    private func coreCenter(in size: CGSize) -> CGPoint {
        CGPoint(
            x: size.width * (layout == .watch ? 0.19 : 0.20),
            y: size.height * 0.52
        )
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

private struct JARVISNeuralCoreCanvas: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let usesFullColor: Bool

    private let fullColorCyan = Color(red: 0.08, green: 0.78, blue: 1.00)
    private let fullColorBlue = Color(red: 0.26, green: 0.48, blue: 1.00)
    private let criticalRed = Color(red: 1.00, green: 0.22, blue: 0.27)

    var body: some View {
        Canvas { context, size in
            let center = CGPoint(
                x: size.width * (layout == .watch ? 0.19 : 0.20),
                y: size.height * 0.52
            )
            let radius = min(
                size.height * (layout == .watch ? 0.34 : 0.36),
                size.width * (layout == .watch ? 0.14 : 0.16)
            )
            let scale = layout == .watch ? 0.72 : 1.0
            let cyan = usesFullColor ? fullColorCyan : Color.primary
            let blue = usesFullColor ? fullColorBlue : Color.primary
            let dim = usesFullColor ? fullColorCyan.opacity(0.19) : Color.secondary.opacity(0.32)
            let line = usesFullColor ? fullColorCyan.opacity(telemetry.signalLost ? 0.30 : 0.78) : Color.primary.opacity(telemetry.signalLost ? 0.38 : 0.82)

            if usesFullColor && !telemetry.signalLost {
                context.addFilter(.shadow(color: fullColorCyan.opacity(0.38), radius: layout == .watch ? 2 : 4))
            }

            drawRing(context: &context, center: center, radius: radius + 3 * scale, color: dim, width: 4 * scale)
            drawQuotaArc(context: &context, center: center, radius: radius + 3 * scale, cyan: cyan, critical: criticalRed, width: 3 * scale)
            drawRing(context: &context, center: center, radius: radius - 6 * scale, color: cyan.opacity(telemetry.signalLost ? 0.22 : 0.58), width: 1.4 * scale)
            drawRing(context: &context, center: center, radius: radius - 15 * scale, color: airQualityColor(cyan: cyan).opacity(telemetry.signalLost ? 0.18 : 0.64), width: 1.5 * scale)
            drawSpokes(context: &context, center: center, radius: radius, cyan: cyan, dim: dim, width: 1.5 * scale)
            drawCircuitTicks(context: &context, center: center, radius: radius, cyan: cyan, dim: dim, width: 1.2 * scale)
            drawTrace(context: &context, size: size, center: center, radius: radius, line: line, cyan: cyan, blue: blue, dim: dim, width: (layout == .watch ? 1.4 : 2.0))
        }
    }

    private func drawRing(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat,
        color: Color,
        width: CGFloat
    ) {
        let rect = CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
        context.stroke(Path(ellipseIn: rect), with: .color(color), lineWidth: width)
    }

    private func drawQuotaArc(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat,
        cyan: Color,
        critical: Color,
        width: CGFloat
    ) {
        guard !telemetry.signalLost, let remaining = telemetry.codexRemainingPercent else { return }
        let progress = min(max(remaining / 100, 0), 1)
        guard progress > 0 else { return }
        var path = Path()
        path.addArc(
            center: center,
            radius: radius,
            startAngle: .degrees(-90),
            endAngle: .degrees(-90 + progress * 360),
            clockwise: false
        )
        context.stroke(
            path,
            with: .color(telemetry.codexIsCritical && usesFullColor ? critical : cyan),
            style: StrokeStyle(lineWidth: width, lineCap: .round)
        )
    }

    private func drawSpokes(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat,
        cyan: Color,
        dim: Color,
        width: CGFloat
    ) {
        for index in 0..<8 {
            let angle = CGFloat(index) * .pi / 4
            let inner = radius * 0.50
            let outer = radius * 0.78
            let start = CGPoint(x: center.x + cos(angle) * inner, y: center.y + sin(angle) * inner)
            let end = CGPoint(x: center.x + cos(angle) * outer, y: center.y + sin(angle) * outer)
            var path = Path()
            path.move(to: start)
            path.addLine(to: end)
            let lit = !telemetry.signalLost && index < telemetry.illuminatedSpokes
            context.stroke(
                path,
                with: .color(lit ? cyan : dim),
                style: StrokeStyle(lineWidth: width, lineCap: .round)
            )
        }
    }

    private func drawCircuitTicks(
        context: inout GraphicsContext,
        center: CGPoint,
        radius: CGFloat,
        cyan: Color,
        dim: Color,
        width: CGFloat
    ) {
        for index in 0..<4 {
            let angle = CGFloat(index) * .pi / 2
            let startRadius = radius * 0.80
            let endRadius = radius * 1.06
            var path = Path()
            path.move(to: CGPoint(x: center.x + cos(angle) * startRadius, y: center.y + sin(angle) * startRadius))
            path.addLine(to: CGPoint(x: center.x + cos(angle) * endRadius, y: center.y + sin(angle) * endRadius))
            context.stroke(path, with: .color(telemetry.signalLost ? dim : cyan.opacity(0.72)), lineWidth: width)
        }
    }

    private func drawTrace(
        context: inout GraphicsContext,
        size: CGSize,
        center: CGPoint,
        radius: CGFloat,
        line: Color,
        cyan: Color,
        blue: Color,
        dim: Color,
        width: CGFloat
    ) {
        let startX = center.x + radius + size.width * (layout == .watch ? 0.025 : 0.035)
        let endX = size.width * 0.965
        let y = size.height * (layout == .watch ? 0.58 : 0.57)
        let amplitude = size.height * (layout == .watch ? 0.15 : 0.14)
        let span = endX - startX
        let normalized: [(CGFloat, CGFloat)] = [
            (0.00, 0.00), (0.12, 0.00), (0.20, -1.00), (0.30, 1.00),
            (0.42, -0.35), (0.52, 0.00), (0.63, 0.00), (0.72, -1.00),
            (0.82, 1.00), (0.90, 0.00), (1.00, 0.00),
        ]
        let points = normalized.map { CGPoint(x: startX + $0.0 * span, y: y + $0.1 * amplitude) }

        if telemetry.signalLost {
            strokePolyline(Array(points[0...4]), context: &context, color: line, width: width)
            strokePolyline(Array(points[6...10]), context: &context, color: line, width: width)
        } else {
            strokePolyline(points, context: &context, color: line, width: width)
        }

        let nodeIndices = [1, 4, 6, 9]
        for (offset, pointIndex) in nodeIndices.enumerated() {
            let state = telemetry.plugStates.indices.contains(offset) ? telemetry.plugStates[offset] : .unknown
            let fill: Color
            switch state {
            case .on: fill = cyan
            case .off: fill = usesFullColor ? blue.opacity(0.72) : Color.primary.opacity(0.58)
            case .unknown: fill = dim
            }
            let nodeRadius: CGFloat = layout == .watch ? 2.1 : 3.2
            context.fill(Path(ellipseIn: CGRect(
                x: points[pointIndex].x - nodeRadius,
                y: points[pointIndex].y - nodeRadius,
                width: nodeRadius * 2,
                height: nodeRadius * 2
            )), with: .color(fill))
        }

        let branchLength = size.height * (layout == .watch ? 0.18 : 0.16)
        let branchNodes = [4, 6]
        for (offset, index) in branchNodes.enumerated() {
            let direction: CGFloat = offset == 0 ? 1 : -1
            var branch = Path()
            branch.move(to: points[index])
            branch.addLine(to: CGPoint(x: points[index].x, y: points[index].y + direction * branchLength))
            branch.addLine(to: CGPoint(x: points[index].x + span * 0.08, y: points[index].y + direction * branchLength))
            context.stroke(branch, with: .color(dim), lineWidth: max(1, width * 0.55))
        }
    }

    private func strokePolyline(
        _ points: [CGPoint],
        context: inout GraphicsContext,
        color: Color,
        width: CGFloat
    ) {
        guard let first = points.first else { return }
        var path = Path()
        path.move(to: first)
        for point in points.dropFirst() { path.addLine(to: point) }
        context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
    }

    private func airQualityColor(cyan: Color) -> Color {
        guard usesFullColor, let pm25 = telemetry.pm25 else { return cyan }
        switch pm25 {
        case ...12: return cyan
        case 13...35: return .yellow
        case 36...55: return .orange
        default: return criticalRed
        }
    }
}
