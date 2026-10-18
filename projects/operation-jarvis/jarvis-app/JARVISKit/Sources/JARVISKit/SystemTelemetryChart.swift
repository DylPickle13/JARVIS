import SwiftUI

/// Local drawing/inspection only. No networking, timers or Watch navigation gestures.
@MainActor
public struct SystemTelemetryChart: View {
    public let window: SystemTelemetryWindow
    public let compact: Bool
    public let active: Bool
    public let height: CGFloat
    @Environment(\.colorScheme) private var scheme
    @Environment(\.colorSchemeContrast) private var contrast
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.isLuminanceReduced) private var dimmed
    @State private var beacon = SystemTelemetryBeacon()
    @State private var pulse: CGFloat = 0
    @State private var selection: Int?

    public init(window: SystemTelemetryWindow, compact: Bool, active: Bool, height: CGFloat) {
        self.window = window; self.compact = compact; self.active = active; self.height = height
    }
    private var motionAllowed: Bool { active && scenePhase == .active && !reduceMotion && !dimmed && !window.muted }
    private struct PulseInput: Equatable { let source: Date?; let allowed: Bool }
    private var pulseInput: PulseInput { .init(source: window.beaconSource, allowed: motionAllowed) }
    private var selected: SystemHistoryBucket? {
        guard let selection, window.buckets.indices.contains(selection) else { return nil }
        return window.buckets[selection]
    }
    private var cyan: Color { scheme == .dark ? Color(red: 0.43, green: 0.89, blue: 0.93) : Color(red: 0.02, green: 0.39, blue: 0.46) }
    private func color(_ state: SystemHistoryState) -> Color {
        guard !window.muted else { return .secondary }
        switch state {
        case .healthy: return cyan
        case .degraded: return scheme == .dark ? .orange : Color(red: 0.62, green: 0.28, blue: 0.02)
        case .unavailable: return .red
        case .unknown, .inactive: return .secondary
        }
    }
    nonisolated private func level(_ state: SystemHistoryState) -> Double {
        switch state { case .healthy: return 0.08; case .degraded: return 0.42
        case .unavailable: return 0.66; case .inactive: return 0.78; case .unknown: return 0.92 }
    }

    public var body: some View {
        VStack(spacing: 4) {
            interactivePlot
                .frame(height: height)
                .overlay(alignment: .top) {
                    if let selected {
                        VStack(spacing: 2) {
                            Text(timeRange(selected)).font(.caption2.monospacedDigit())
                            Text(selected.hasGap ? "Partial / missing evidence" : selected.mixed ? "Mixed observations" : selected.state.title)
                                .font(.caption2).foregroundStyle(color(selected.state))
                        }
                        .padding(6)
                        .background(scheme == .dark ? Color(red: 0.07, green: 0.15, blue: 0.20) : Color.white,
                                    in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(cyan.opacity(0.4), lineWidth: 0.7))
                        .allowsHitTesting(false)
                    }
                }
            HStack {
                Text(window.start?.formatted(date: .omitted, time: .shortened) ?? "—")
                Spacer(minLength: 4)
                Text(window.end?.formatted(date: .omitted, time: .shortened) ?? "—")
            }.font(.system(size: compact ? 8 : 10, design: .monospaced)).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(window.title). Cached observations, not physical uptime. \(window.notice ?? "")")
        .accessibilityValue(selected.map(SystemTelemetryWindow.evidence)
            ?? window.buckets.map(SystemTelemetryWindow.evidence).joined(separator: ". "))
        .accessibilityHint("Adjust to inspect recorded time buckets. Hatching means gaps; caps mark partial or mixed evidence.")
        .accessibilityAdjustableAction { direction in
            guard !window.buckets.isEmpty else { return }
            let current = selection ?? (direction == .increment ? -1 : window.buckets.count)
            selection = min(window.buckets.count - 1, max(0, current + (direction == .increment ? 1 : -1)))
        }
        .accessibilityIdentifier("system-health-history")
        .onChange(of: window) { _ in selection = nil }
        .task(id: pulseInput) {
            pulse = 0
            guard beacon.receive(pulseInput.source, allowed: pulseInput.allowed) else { return }
            withAnimation(.easeOut(duration: 0.22)) { pulse = 1 }
            do { try await Task.sleep(for: .milliseconds(240)) } catch { pulse = 0; return }
            guard !Task.isCancelled, motionAllowed else { pulse = 0; return }
            withAnimation(.easeOut(duration: 0.45)) { pulse = 0 }
        }
        .onDisappear { pulse = 0; selection = nil }
    }

    @ViewBuilder private var interactivePlot: some View {
        #if os(iOS)
        if !compact {
            GeometryReader { geometry in
                plot.contentShape(Rectangle())
                    // A short hold distinguishes inspection from ordinary vertical scrolling.
                    .gesture(LongPressGesture(minimumDuration: 0.25).sequenced(before: DragGesture(minimumDistance: 0))
                        .onChanged { value in
                            guard active else { return }
                            if case .second(true, let drag?) = value {
                                let left: CGFloat = 49
                                let fraction = Double((drag.location.x - left) / max(1, geometry.size.width - left - 9))
                                if let bucket = window.bucket(at: fraction) { selection = window.buckets.firstIndex(of: bucket) }
                            }
                        }.onEnded { _ in selection = nil })
            }
        } else { plot }
        #else
        plot
        #endif
    }

    private var plot: some View {
        Canvas { context, size in
            let left: CGFloat = compact ? 27 : 49
            let rect = CGRect(x: left, y: 5, width: max(1, size.width - left - 9), height: max(1, size.height - 12))
            func y(_ state: SystemHistoryState) -> CGFloat { rect.minY + rect.height * level(state) }
            func line(_ a: CGPoint, _ b: CGPoint) -> Path { var p = Path(); p.move(to: a); p.addLine(to: b); return p }
            for tick in 0...6 {
                let x = rect.minX + rect.width * Double(tick) / 6
                context.stroke(line(.init(x: x, y: rect.minY), .init(x: x, y: rect.maxY)), with: .color(.secondary.opacity(0.13)), lineWidth: 0.5)
                context.stroke(line(.init(x: x, y: rect.maxY - 2), .init(x: x, y: rect.maxY + 2)), with: .color(.secondary.opacity(0.5)), lineWidth: 0.7)
            }
            for (state, label) in [(SystemHistoryState.healthy, compact ? "OK" : "Healthy"), (.degraded, "Issue"), (.unavailable, "Unavail."), (.unknown, "?")] {
                let yy = y(state)
                context.stroke(line(.init(x: rect.minX, y: yy), .init(x: rect.maxX, y: yy)), with: .color(.secondary.opacity(0.17)), lineWidth: 0.5)
                // Dense Watch plots retain all state levels; full labels are spoken by VoiceOver.
                if !compact || state != .unavailable {
                    context.draw(Text(label).font(.system(size: compact ? 7 : 9)).foregroundColor(.secondary), at: .init(x: 0, y: yy), anchor: .leading)
                }
            }
            guard let start = window.start, let end = window.end, end > start else {
                context.draw(Text("Awaiting evidence").font(.caption2).foregroundColor(.secondary), at: .init(x: rect.midX, y: rect.midY))
                return
            }
            func x(_ date: Date) -> CGFloat { rect.minX + rect.width * date.timeIntervalSince(start) / end.timeIntervalSince(start) }
            for (index, bucket) in window.buckets.enumerated() {
                guard let lo = bucket.start, let hi = bucket.end else { continue }
                let a = x(lo), b = x(hi), tint = color(bucket.state), yy = y(bucket.state)
                if !SystemTelemetryWindow.isSolid(bucket) {
                    var clipped = context
                    let cell = CGRect(x: a, y: rect.minY, width: b - a, height: rect.height)
                    clipped.clip(to: Path(cell))
                    var hatch = Path(); var xx = a - rect.height
                    while xx < b { hatch.move(to: .init(x: xx, y: rect.maxY)); hatch.addLine(to: .init(x: xx + rect.height, y: rect.minY)); xx += 6 }
                    clipped.stroke(hatch, with: .color(.secondary.opacity(0.3)), lineWidth: 0.7)
                    if let observed = bucket.observedState {
                        // Cap only: the order/duration within partial or mixed buckets is unknown.
                        clipped.stroke(line(.init(x: a, y: rect.minY + 1), .init(x: b, y: rect.minY + 1)), with: .color(color(observed)), lineWidth: 2)
                    }
                } else {
                    let fill = CGRect(x: a, y: yy, width: max(0, b - a), height: max(0, rect.maxY - yy))
                    context.fill(Path(fill), with: .linearGradient(Gradient(colors: [tint.opacity(0.15), tint.opacity(0.005)]), startPoint: .init(x: a, y: yy), endPoint: .init(x: a, y: rect.maxY)))
                    var path = line(.init(x: a, y: yy), .init(x: b, y: yy))
                    if index + 1 < window.buckets.count {
                        let next = window.buckets[index + 1]
                        if next.start == hi && SystemTelemetryWindow.isSolid(next) {
                            path.addLine(to: .init(x: b, y: y(next.state)))
                        }
                    }
                    if !dimmed && contrast != .increased { context.stroke(path, with: .color(tint.opacity(0.10)), lineWidth: 5) }
                    context.stroke(path, with: .color(tint), lineWidth: contrast == .increased ? 2 : 1.3)
                    if bucket.state == .inactive {
                        context.draw(Text("Ⅱ").font(.system(size: 8)).foregroundColor(.secondary), at: .init(x: (a+b)/2, y: yy))
                    }
                }
                if selection == index {
                    let xx = (a+b)/2
                    context.stroke(line(.init(x: xx, y: rect.minY), .init(x: xx, y: rect.maxY)), with: .color(cyan.opacity(0.65)), style: StrokeStyle(lineWidth: 0.8, dash: [3, 3]))
                }
            }
            if window.beaconSource != nil, let last = window.buckets.last {
                let center = CGPoint(x: rect.maxX, y: y(last.state)), tint = color(last.state)
                let radius: CGFloat = dimmed ? 3 : 4 + pulse * 3
                if !dimmed {
                    context.fill(Path(ellipseIn: CGRect(x: center.x - radius*2, y: center.y - radius*2, width: radius*4, height: radius*4)), with: .radialGradient(Gradient(colors: [tint.opacity(0.25), .clear]), center: center, startRadius: 0, endRadius: radius*2))
                }
                context.stroke(Path(ellipseIn: CGRect(x: center.x-3.5, y: center.y-3.5, width: 7, height: 7)), with: .color(tint), lineWidth: 1)
                context.fill(Path(ellipseIn: CGRect(x: center.x-1, y: center.y-1, width: 2, height: 2)), with: .color(tint))
            }
        }
    }

    private func timeRange(_ bucket: SystemHistoryBucket) -> String {
        "\(bucket.start?.formatted(date: .omitted, time: .shortened) ?? "?")–\(bucket.end?.formatted(date: .omitted, time: .shortened) ?? "?")"
    }
}
