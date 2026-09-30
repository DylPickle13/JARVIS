import SwiftUI

/// One segment per cached check, not an invented percentage or utilisation score.
@MainActor
public struct SystemCurrentHealthRing: View {
    let presentation: SystemDashboardPresentation
    let diameter: CGFloat
    @Environment(\.colorScheme) private var scheme
    public init(presentation: SystemDashboardPresentation, diameter: CGFloat) {
        self.presentation = presentation; self.diameter = diameter
    }
    public var body: some View {
        let rows = Array(presentation.health.rows.prefix(24))
        let count = max(1, rows.count)
        ZStack {
            Circle().stroke(Color.secondary.opacity(0.12), lineWidth: diameter > 40 ? 5 : 3)
            ForEach(0..<count, id: \.self) { index in
                Circle().trim(from: CGFloat(index)/CGFloat(count)+0.009, to: CGFloat(index+1)/CGFloat(count)-0.009)
                    .stroke(ringColor(rows.isEmpty || !presentation.isConnected ? .unknown : rows[index].state),
                            style: StrokeStyle(lineWidth: diameter > 40 ? 5 : 3, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            }
            Image(systemName: presentation.state == .healthy ? "checkmark.shield" : presentation.state == .issue ? "exclamationmark.shield" : "questionmark.circle")
                .font(.system(size: diameter * 0.29, weight: .medium))
                .foregroundStyle(ringColor(presentation.state))
        }
        .frame(width: diameter, height: diameter).padding(3)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Current cached checks, \(presentation.summary). Segments are check statuses, not a percentage.")
    }
    private func ringColor(_ state: SystemHealthState) -> Color {
        switch state {
        case .healthy: return SystemHistoryPalette.color(.healthy, dark: scheme == .dark)
        case .issue: return .orange
        default: return .secondary
        }
    }
}

public enum SystemHistoryPalette {
    public static func color(_ state: SystemHistoryState, dark: Bool) -> Color {
        switch state {
        case .healthy: return dark ? Color(red: 0.40, green: 0.86, blue: 0.70) : Color(red: 0.04, green: 0.48, blue: 0.34)
        case .degraded: return .orange
        case .unavailable: return dark ? Color(red: 1, green: 0.38, blue: 0.51) : Color(red: 0.75, green: 0.10, blue: 0.24)
        case .unknown: return .secondary
        case .inactive: return Color.secondary.opacity(0.55)
        }
    }
}

/// Absolute-time buckets only. No green extension to the device's render clock.
/// A hatch means missing coverage; a thin coloured cap marks observed evidence
/// in a partial bucket, without inventing the order of events inside that bucket.
@MainActor
public struct SystemHistoryBand: View {
    public let series: SystemHistorySeries?
    public let height: CGFloat
    @Environment(\.colorScheme) private var scheme
    public init(series: SystemHistorySeries?, height: CGFloat = 12) { self.series = series; self.height = height }
    public var body: some View {
        Canvas { context, size in
            let buckets = series?.buckets ?? []
            let count = max(1, buckets.count)
            let cell = size.width / CGFloat(count)
            for index in 0..<count {
                let bucket = buckets.isEmpty ? nil : buckets[index]
                let rect = CGRect(x: CGFloat(index)*cell, y: 0, width: cell+0.15, height: size.height)
                let gap = bucket?.hasGap ?? true
                let color = SystemHistoryPalette.color(bucket?.state ?? .unknown, dark: scheme == .dark)
                context.fill(Path(rect), with: .color(gap ? Color.secondary.opacity(0.12) : color))
                if gap {
                    var clipped = context
                    clipped.clip(to: Path(rect))
                    var hatch = Path()
                    var x = rect.minX-size.height
                    while x < rect.maxX {
                        hatch.move(to: CGPoint(x: x, y: size.height));hatch.addLine(to: CGPoint(x: x+size.height, y: 0));x += 6
                    }
                    clipped.stroke(hatch, with: .color(Color.secondary.opacity(0.25)), lineWidth: 1)
                    if let observed = bucket?.observedState {
                        let cap = CGRect(x: rect.minX, y: 0, width: rect.width, height: min(3, size.height/3))
                        clipped.fill(Path(cap), with: .color(SystemHistoryPalette.color(observed, dark: scheme == .dark)))
                    }
                } else if bucket?.mixed == true {
                    // Worst observed state remains visible, with a mixed mark.
                    context.fill(Path(CGRect(x: rect.minX, y: size.height-2, width: rect.width, height: 2)), with: .color(Color.primary.opacity(0.25)))
                }
            }
        }
        .frame(height: height)
        .clipShape(RoundedRectangle(cornerRadius: 2))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
    }
    private var accessibilitySummary: String {
        guard let series else { return "No recorded history available" }
        let issues = series.buckets.filter { [.degraded, .unavailable].contains($0.state) }.count
        let gaps = series.buckets.filter(\.hasGap).count
        return "\(series.title) recorded history, \(issues) buckets with observed issues, \(gaps) buckets with missing coverage. Tap for times and evidence."
    }
}

@MainActor
public struct SystemHistoryDetails: View {
    let response: SystemHistoryResponse?
    let component: String
    let notice: String?
    public init(response: SystemHistoryResponse?, component: String, notice: String?) {
        self.response = response; self.component = component; self.notice = notice
    }
    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let notice { Text(notice).foregroundStyle(.orange) }
            Text("Recorded observations, not physical outages").font(.headline)
            Text("Hatches mean missing coverage. A coloured cap marks observed evidence in a partial bucket. Colours preserve the worst observation; they do not establish its exact duration or order within a bucket.")
                .font(.caption).foregroundStyle(.secondary)
            if let response, let series = response.series.first(where: { $0.id == component }) {
                Text(series.title).font(.headline)
                if let start = response.start, let end = response.end {
                    Text("\(start.formatted(date: .abbreviated, time: .shortened)) – \(end.formatted(date: .abbreviated, time: .shortened))").font(.caption)
                }
                if let text = response.earliestSampleAt, let date = SystemHistoryDates.parse(text) {
                    Text("Available history begins \(date.formatted(date: .abbreviated, time: .shortened)). Earlier periods have no chart coverage.").font(.caption)
                }
                SystemHistoryBand(series: series, height: 24)
                Text("One evaluation per minute. Unknown and uncovered periods are not healthy. Brief failures between samples may be missed. No automatic recovery.").font(.caption)
                ForEach(Array(series.buckets.enumerated().reversed()), id: \.offset) { item in
                    SystemHistoryBucketDisclosure(bucket: item.element)
                }
            } else { Text("History unavailable. No earlier observations are invented.").font(.caption) }
        }
    }
}

/// DisclosureGroup is unavailable on watchOS; this explicit button works on
/// both platforms and stays inside the scrolling, input-owning detail sheet.
@MainActor
private struct SystemHistoryBucketDisclosure: View {
    let bucket: SystemHistoryBucket
    @State private var expanded = false
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Button { expanded.toggle() } label: {
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        if let start = bucket.start, let end = bucket.end {
                            Text("\(start.formatted(date: .omitted, time: .shortened)) – \(end.formatted(date: .omitted, time: .shortened))").font(.caption.monospacedDigit())
                        }
                        Label(bucket.coverageSeconds == 0 ? "No coverage" : bucket.state.title,
                              systemImage: bucket.coverageSeconds == 0 ? "minus.circle" : bucket.state.symbol).font(.caption)
                    }
                    Spacer(minLength: 2)
                    Image(systemName: expanded ? "chevron.up" : "chevron.down").font(.caption2)
                }.contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityHint(expanded ? "Collapse evidence" : "Inspect covered states and missing seconds")
            if expanded {
                VStack(alignment: .leading, spacing: 7) {
                    Text("UTC interval: \(bucket.from) – \(bucket.to)").font(.caption.monospaced())
                    Text("Covered evidence: \(bucket.coverageSeconds.formatted(.number.precision(.fractionLength(0...3))))s")
                    Text("Missing coverage: \(bucket.missingSeconds.formatted(.number.precision(.fractionLength(0...3))))s")
                    ForEach(bucket.stateSeconds.keys.sorted(), id: \.self) { key in
                        Text("\(SystemHistoryState(rawValue: key)?.title ?? "Unverified"): \(bucket.stateSeconds[key, default: 0].formatted(.number.precision(.fractionLength(0...3))))s of covered evidence")
                    }
                    if let text = bucket.sourceObservedAt, let date = SystemHistoryDates.parse(text) {
                        Text("Newest represented source: \(date.formatted(date: .abbreviated, time: .standard))")
                    }
                    ForEach(bucket.reasonCodes, id: \.self) { reason in Text(reason.replacingOccurrences(of: "_", with: " ")) }
                    if bucket.mixed { Text("Mixed bucket—not an outage lasting the whole interval.") }
                }.font(.caption).padding(.vertical, 5)
            }
        }
    }
}
