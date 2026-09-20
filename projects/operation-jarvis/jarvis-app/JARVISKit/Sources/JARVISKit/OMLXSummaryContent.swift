import SwiftUI

/// Same heading and two single-line host rows as the original card. Details
/// rotate together; only overlong model names move, inside their clipped column.
public struct OMLXSummaryContent: View {
    private let rows: [OMLXServerSummary]
    private let compact: Bool
    private let motionActive: Bool
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityVoiceOverEnabled) private var voiceOver
    @Environment(\.isLuminanceReduced) private var luminanceReduced
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .caption2) private var watchRowSize = 11.0
    @ScaledMetric(relativeTo: .caption2) private var watchHeadingSize = 10.5
    @State private var page: OMLXDetailPage = .models(0)
    @State private var pageStartedAt = Date()
    @State private var measurements: [String: OMLXNameMeasurement] = [:]

    public init(rows: [OMLXServerSummary], compact: Bool = false, motionActive: Bool = false) {
        self.rows = rows
        self.compact = compact
        self.motionActive = motionActive
    }
    private var motion: OMLXMotionPolicy {
        .init(rows: rows, active: motionActive, sceneActive: scenePhase == .active,
              reduceMotion: reduceMotion, luminanceReduced: luminanceReduced)
    }
    private var cycles: Bool {
        motionActive && scenePhase == .active && !luminanceReduced && !voiceOver && rows.contains { $0.fresh }
    }
    private var pages: [OMLXDetailPage] {
        .init(OMLXDetailPage.sequence(
            modelCount: rows.compactMap { $0.details?.modelNames.count }.max() ?? 0,
            narrow: compact || dynamicTypeSize > .large
        ))
    }
    private var speed: Double { compact ? 18 : 24 }
    private var pageDuration: Double {
        guard case .models(let index) = page else { return OMLXMarqueeTiming.pageSeconds }
        return rows.reduce(OMLXMarqueeTiming.pageSeconds) { duration, row in
            guard let detail = row.details, let size = measurements[row.id],
                  size.text == detail.modelName(at: index) else { return duration }
            return max(duration, OMLXMarqueeTiming.duration(content: size.content, viewport: size.viewport,
                speed: speed, reduceMotion: reduceMotion))
        }
    }
    private var rotationKey: OMLXRotationKey {
        .init(page: page, pages: pages, names: rows.map { $0.details?.modelNames ?? [] },
              duration: pageDuration, enabled: cycles, reduceMotion: reduceMotion)
    }
    private var heading: String {
        guard rows.contains(where: { $0.fresh }) else { return "Status" }
        if case .models(let index) = page {
            let count = rows.compactMap { $0.details?.modelNames.count }.max() ?? 0
            return count > 1 ? "Models · \(index + 1)/\(count)" : "Models"
        }
        return page.title
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 3 : 6) {
            HStack(spacing: compact ? 4 : 5) {
                Image(systemName: "cpu")
                    .font(.system(size: compact ? watchHeadingSize - 1 : 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .activityIconPulse(active: motion.pulsesCPU)
                    .accessibilityHidden(true)
                Text("oMLX")
                    .font(compact ? .system(size: watchHeadingSize, weight: .semibold) : .subheadline.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)
                Circle().fill(Color.green)
                    .frame(width: compact ? 5 : 6, height: compact ? 5 : 6)
                    .opacity(rows.contains(where: \.updateAvailable) ? 1 : 0)
                    .accessibilityLabel("oMLX update available")
                    .accessibilityValue(rows.filter(\.updateAvailable).map { "Mac mini \($0.serverLabel)" }.joined(separator: ", "))
                    .accessibilityHidden(!rows.contains(where: \.updateAvailable))
                Spacer(minLength: 4)
                ViewThatFits(in: .horizontal) {
                    Text(heading).fixedSize()
                    Text(rows.contains(where: { $0.fresh }) ? page.shortTitle : "Status").fixedSize()
                }
                .font(compact ? .system(size: watchHeadingSize - 1) : .caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .accessibilityHidden(true)
            }
            ForEach(rows) { row in
                HStack(spacing: compact ? 4 : 7) {
                    Text(row.serverLabel).fontWeight(.medium).fixedSize()
                    statusDot(row)
                    detail(row)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .font(compact ? .system(size: watchRowSize) : .caption)
                .padding(.vertical, compact ? 0 : 2)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Mac mini, \(row.serverLabel)")
                .accessibilityValue(row.details.map { row.status + ". " + $0.accessibilityValue } ?? row.accessibilityValue)
            }
        }
        .monospacedDigit()
        .frame(maxWidth: .infinity, alignment: .leading)
        .onPreferenceChange(OMLXNameMeasurementKey.self) { values in
            // Removing the name view on a stats page must not erase its size and
            // reset the clock. Real metric samples never restart the rotation.
            for (id, value) in values where measurements[id] != value {
                measurements[id] = value
            }
        }
        .task(id: rotationKey) {
            guard cycles else { return }
            guard let index = pages.firstIndex(of: page) else {
                page = pages[0]
                return
            }
            pageStartedAt = Date()
            do { try await Task.sleep(for: .seconds(pageDuration)) } catch { return }
            guard !Task.isCancelled else { return }
            page = pages[(index + 1) % pages.count]
        }
    }

    @ViewBuilder private func detail(_ row: OMLXServerSummary) -> some View {
        if let details = row.details, row.fresh {
            if case .models(let index) = page {
                let text = details.modelName(at: index)
                OMLXModelName(text: text, rowID: row.id,
                    measurement: measurements[row.id].flatMap { $0.text == text ? $0 : nil },
                    startedAt: pageStartedAt, speed: speed, running: cycles,
                    reduceMotion: reduceMotion, compact: compact)
            } else {
                Text(details.text(for: page))
                    .lineLimit(1)
                    .foregroundStyle(.primary)
                    .contentTransition(.opacity)
                    .animation(motion.enabled ? .easeOut(duration: 0.25) : nil, value: details.text(for: page))
            }
        } else {
            // No name, rate, or memory sample survives the freshness gate.
            Text(row.status).foregroundStyle(.secondary).lineLimit(1)
        }
    }

    private func statusDot(_ row: OMLXServerSummary) -> some View {
        Circle().fill(row.fresh ? OMLXFormat.tone(row.phase) : .secondary)
            .frame(width: compact ? 4 : 5, height: compact ? 4 : 5)
            .activityStatusBreath(active: motion.enabled && row.breathesStatus,
                slow: row.phase == .loading, compact: compact)
            .accessibilityHidden(true)
    }
}

private struct OMLXRotationKey: Equatable {
    let page: OMLXDetailPage
    let pages: [OMLXDetailPage]
    let names: [[String]]
    let duration: Double
    let enabled: Bool
    let reduceMotion: Bool
}

private struct OMLXNameMeasurement: Equatable {
    let text: String
    let content: Double
    let viewport: Double
}
private struct OMLXNameMeasurementKey: PreferenceKey {
    static var defaultValue: [String: OMLXNameMeasurement] { [:] }
    static func reduce(value: inout [String: OMLXNameMeasurement], nextValue: () -> [String: OMLXNameMeasurement]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

private struct OMLXModelName: View {
    let text: String
    let rowID: String
    let measurement: OMLXNameMeasurement?
    let startedAt: Date
    let speed: Double
    let running: Bool
    let reduceMotion: Bool
    let compact: Bool

    private var overflows: Bool {
        guard let measurement else { return false }
        return OMLXMarqueeTiming.distance(content: measurement.content, viewport: measurement.viewport) > 0
    }
    var body: some View {
        // Intrinsic height stays exactly one ordinary row. The complete model
        // name is measured/rendered in an overlay, so it cannot widen the card.
        Text("Ag").hidden()
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay {
                GeometryReader { viewport in
                    TimelineView(.animation(minimumInterval: reduceMotion ? 1 : (compact ? 1.0 / 15 : 1.0 / 30),
                                            paused: !running || !overflows)) { context in
                        let offset = OMLXMarqueeTiming.offset(
                            elapsed: running ? context.date.timeIntervalSince(startedAt) : 0,
                            content: measurement?.content ?? 0, viewport: Double(viewport.size.width),
                            speed: speed, reduceMotion: reduceMotion)
                        Text(text)
                            .foregroundStyle(.primary)
                            .fixedSize(horizontal: true, vertical: false)
                            .background {
                                GeometryReader { content in
                                    Color.clear.preference(key: OMLXNameMeasurementKey.self, value: [
                                        rowID: .init(text: text, content: Double(content.size.width), viewport: Double(viewport.size.width))
                                    ])
                                }
                            }
                            .offset(x: -offset)
                            .frame(width: viewport.size.width, height: viewport.size.height, alignment: .leading)
                            .clipped()
                            .transaction { $0.animation = nil }
                    }
                }
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}
