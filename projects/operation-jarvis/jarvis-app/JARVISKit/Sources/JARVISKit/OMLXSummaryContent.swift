import SwiftUI

/// Display-only, fixed two-row status at phone and Watch densities.
public struct OMLXSummaryContent: View {
    private let rows: [OMLXServerSummary]
    private let compact: Bool
    private let motionActive: Bool
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .caption2) private var watchRowSize = 11.0
    @ScaledMetric(relativeTo: .caption2) private var watchHeadingSize = 10.5

    public init(rows: [OMLXServerSummary], compact: Bool = false, motionActive: Bool = false) {
        self.rows = rows
        self.compact = compact
        self.motionActive = motionActive
    }
    private var motion: OMLXMotionPolicy {
        .init(rows: rows, active: motionActive, sceneActive: scenePhase == .active,
              reduceMotion: reduceMotion, luminanceReduced: luminanceReduced)
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 3 : 6) {
            HStack(spacing: compact ? 4 : 5) {
                Image(systemName: "cpu")
                    .font(.system(size: compact ? watchHeadingSize - 1 : 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    // Fixed, slow decorative brightness pulse; no scaling/layout
                    // changes, custom timer or relationship to token speed.
                    .activityIconPulse(active: motion.pulsesCPU)
                    .accessibilityHidden(true)
                Text("oMLX")
                    .font(compact ? .system(size: watchHeadingSize, weight: .semibold) : .subheadline.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 4)
            }
            ForEach(rows) { row in
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: compact ? 4 : 7) {
                        host(row)
                        state(row)
                        Spacer(minLength: 2)
                        if let value = row.metric { metric(value, for: row).fixedSize() }
                    }
                    if dynamicTypeSize > .large {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 5) { host(row); state(row) }
                            if let value = row.metric { metric(value, for: row) }
                        }
                    } else {
                        // At ordinary sizes keep exactly two rows, even on a
                        // small Watch. Identity/state outrank an optional metric
                        // that will not fit; its full value remains in
                        // VoiceOver. Only larger text may grow vertically.
                        HStack(spacing: compact ? 4 : 7) {
                            host(row)
                            state(row)
                            Spacer(minLength: 2)
                        }
                    }
                }
                .font(compact ? .system(size: watchRowSize) : .caption)
                .padding(.vertical, compact ? 0 : 2)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Mac mini, \(row.serverLabel)")
                .accessibilityValue(row.accessibilityValue)
            }
        }
        .monospacedDigit()
        .frame(maxWidth: .infinity, alignment: .leading)
    }
    private func metric(_ value: String, for row: OMLXServerSummary) -> some View {
        Text(value)
            .foregroundStyle(.secondary)
            // Crossfade real samples, never interpolate fictional token counts.
            // Scoped to this text: state changes and metric removal stay immediate.
            .contentTransition(.opacity)
            .animation(motion.transitionsMetric(for: row) ? .easeInOut(duration: 0.25) : nil, value: value)
            // Replacing the text node also cancels an in-flight fade when gated off.
            .id(motion.transitionsMetric(for: row))
            .transaction { transaction in
                if !motion.transitionsMetric(for: row) {
                    transaction.animation = nil
                    transaction.disablesAnimations = true
                }
            }
    }

    private func host(_ row: OMLXServerSummary) -> some View {
        Text(row.serverLabel).fontWeight(.medium).fixedSize()
    }
    private func state(_ row: OMLXServerSummary) -> some View {
        let tone: Color = row.fresh ? OMLXFormat.tone(row.phase) : .secondary
        return HStack(spacing: compact ? 3 : 4) {
            Circle().fill(tone).frame(width: compact ? 4 : 5, height: compact ? 4 : 5)
                .activityStatusBreath(active: motion.enabled && row.breathesStatus,
                    slow: row.phase == .loading, compact: compact)
                .accessibilityHidden(true)
            Text(row.status).foregroundStyle(row.fresh && row.phase != .ready ? tone : .secondary)
        }
    }
}
