import SwiftUI

/// Shared heading and single-line host rows. Watch retains both rows;
/// iPhone can opt into activity-only rows without losing peer health warnings.
public struct OMLXSummaryContent: View {
    private let rows: [OMLXServerSummary]
    private let compact: Bool
    private let motionActive: Bool
    private let activeRowsOnly: Bool
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced
    @ScaledMetric(relativeTo: .caption2) private var watchRowSize = 11.0
    @ScaledMetric(relativeTo: .caption2) private var watchHeadingSize = 10.5

    public init(rows: [OMLXServerSummary], compact: Bool = false, motionActive: Bool = false,
                activeRowsOnly: Bool = false) {
        self.rows = rows
        self.compact = compact
        self.motionActive = motionActive
        self.activeRowsOnly = activeRowsOnly
    }
    private var motion: OMLXMotionPolicy {
        .init(rows: rows, active: motionActive, sceneActive: scenePhase == .active,
              reduceMotion: reduceMotion, luminanceReduced: luminanceReduced)
    }
    // Fixed metric widths match the heading and both rows, never expanding the
    // card for wider values. The model takes the remaining space and truncates.
    private var speedWidth: CGFloat { compact ? 19 : 34 }
    private var memoryWidth: CGFloat { compact ? 22 : 34 }
    private var gap: CGFloat { compact ? 3 : 7 }

    public var body: some View {
        let home = OMLXHomePresentation(rows: rows)
        let visibleRows = activeRowsOnly ? home.visibleRows : rows
        VStack(alignment: .leading, spacing: compact ? 3 : 6) {
            HStack(spacing: gap) {
                HStack(spacing: compact ? 4 : 5) {
                    Image(systemName: "cpu")
                        .font(.system(size: compact ? watchHeadingSize - 1 : 12, weight: .medium))
                        .foregroundStyle(.secondary)
                        .activityIconPulse(active: motion.pulsesCPU)
                        .accessibilityHidden(true)
                    Text("oMLX")
                        .font(compact ? .system(size: watchHeadingSize, weight: .semibold) : .subheadline.weight(.semibold))
                        .lineLimit(1)
                        .foregroundStyle(.primary)
                        .accessibilityAddTraits(.isHeader)
                    Circle().fill(Color.green)
                        .frame(width: compact ? 5 : 6, height: compact ? 5 : 6)
                        .opacity(rows.contains(where: \.updateAvailable) ? 1 : 0)
                        .accessibilityLabel("oMLX update available")
                        .accessibilityValue(rows.filter(\.updateAvailable).map { "Mac mini \($0.serverLabel)" }.joined(separator: ", "))
                        .accessibilityHidden(!rows.contains(where: \.updateAvailable))
                    if activeRowsOnly, let status = home.status {
                        Text(status)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                    }
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if !activeRowsOnly || !visibleRows.isEmpty {
                    column("t/s", width: speedWidth)
                    column("RAM", width: memoryWidth)
                }
            }
            .font(compact ? .system(size: watchHeadingSize - 1) : .caption2)
            .foregroundStyle(.secondary)
            ForEach(visibleRows) { row in
                HStack(spacing: gap) {
                    HStack(spacing: compact ? 3 : 4) {
                        statusDot(row)
                        Text(row.compactServerLabel).fontWeight(.medium).fixedSize()
                    }
                    Text(row.modelLabel)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .foregroundStyle(row.fresh ? .primary : .secondary)
                    column(row.speedText, width: speedWidth)
                    column(row.hostMemoryText, width: memoryWidth)
                }
                .font(compact ? .system(size: watchRowSize) : .caption)
                .padding(.vertical, compact ? 0 : 2)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Mac mini, \(row.serverLabel)")
                .accessibilityValue(row.cardAccessibilityValue)
            }
        }
        .monospacedDigit()
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func column(_ text: String, width: CGFloat) -> some View {
        Text(text)
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .frame(width: width, alignment: .trailing)
            .clipped()
    }

    private func statusDot(_ row: OMLXServerSummary) -> some View {
        Circle().fill(row.fresh ? OMLXFormat.tone(row.phase) : .secondary)
            .frame(width: compact ? 4 : 5, height: compact ? 4 : 5)
            .activityStatusBreath(active: motion.enabled && row.breathesStatus,
                slow: row.phase == .loading, compact: compact)
            .accessibilityHidden(true)
    }
}
