import SwiftUI

/// The same minimal two-row design at phone and Watch densities. Details live
/// behind the containing button, never in this summary's layout tree.
public struct OMLXSummaryContent: View {
    private let rows: [OMLXServerSummary]
    private let compact: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .caption2) private var watchRowSize = 11.0
    @ScaledMetric(relativeTo: .caption2) private var watchHeadingSize = 10.5

    public init(rows: [OMLXServerSummary], compact: Bool = false) {
        self.rows = rows
        self.compact = compact
    }
    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 3 : 6) {
            HStack {
                Text("oMLX").font(compact ? .system(size: watchHeadingSize, weight: .semibold) : .subheadline.weight(.semibold))
                Spacer(minLength: 4)
                Image(systemName: "chevron.right").font(.system(size: compact ? 8 : 10, weight: .semibold))
                    .foregroundStyle(.secondary).accessibilityHidden(true)
            }
            ForEach(rows) { row in
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: compact ? 4 : 7) {
                        host(row)
                        state(row)
                        Spacer(minLength: 2)
                        if let metric = row.metric { Text(metric).foregroundStyle(.secondary).fixedSize() }
                    }
                    if dynamicTypeSize > .large {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 5) { host(row); state(row) }
                            if let metric = row.metric { Text(metric).foregroundStyle(.secondary) }
                        }
                    } else {
                        // At ordinary sizes keep exactly two rows, even on a
                        // small Watch. Identity/state outrank an optional metric
                        // that will not fit; its full value remains in details
                        // and VoiceOver. Only larger text may grow vertically.
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
    private func host(_ row: OMLXServerSummary) -> some View {
        Text(row.serverLabel).fontWeight(.medium).fixedSize()
    }
    private func state(_ row: OMLXServerSummary) -> some View {
        let tone: Color = row.fresh ? OMLXFormat.tone(row.phase) : .secondary
        return HStack(spacing: compact ? 3 : 4) {
            Circle().fill(tone).frame(width: compact ? 4 : 5, height: compact ? 4 : 5).accessibilityHidden(true)
            Text(row.status).foregroundStyle(tone)
        }
    }
}
