import SwiftUI

/// Static visual health summary. No card actions, sheets, scrolling or input ownership.
/// Platforms retain visibility, refresh policy, networking and Watch gestures.
@MainActor
public struct SystemDashboardContent: View {
    @ObservedObject private var historyModel: SystemHistoryModel
    @Environment(\.colorScheme) private var scheme
    public let presentation: SystemDashboardPresentation
    public let connectionLabel: String
    public let compact: Bool
    public let showsHeader: Bool
    public let accent: Color
    public let warning: Color
    public let surface: Color
    public let connectionError: String?
    public let refreshing: Bool
    public let onRefresh: (() -> Void)?
    public let onDetailVisibilityChanged: (Bool) -> Void

    public init(presentation: SystemDashboardPresentation, connectionLabel: String,
                compact: Bool = false, showsHeader: Bool = true, accent: Color, warning: Color, surface: Color,
                connectionError: String? = nil, refreshing: Bool = false,
                onRefresh: (() -> Void)? = nil, historyModel: SystemHistoryModel? = nil,
                onDetailVisibilityChanged: @escaping (Bool) -> Void = { _ in }) {
        self.historyModel = historyModel ?? SystemHistoryModel()
        self.presentation = presentation
        self.connectionLabel = connectionLabel
        self.compact = compact
        self.showsHeader = showsHeader
        self.accent = accent
        self.warning = warning
        self.surface = surface
        self.connectionError = connectionError
        self.refreshing = refreshing
        self.onRefresh = onRefresh
        self.onDetailVisibilityChanged = onDetailVisibilityChanged
    }

    private var status: String {
        if !presentation.isConnected { return "Offline" }
        if connectionError != nil || presentation.state == .issue { return "Issue" }
        if presentation.state != .healthy { return "Unknown" }
        return "Healthy"
    }
    private var exception: String? {
        if !presentation.isConnected { return "Offline · cached evidence" }
        if connectionError != nil { return "State request failed" }
        if let problem = presentation.visualException { return problem }
        if historyModel.notice != nil || historyModel.snapshot == nil { return "History unavailable" }
        if historyModel.isStale() || !historyModel.isPolling { return "History cached" }
        return nil
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 0 : 10) {
            if !compact && showsHeader {
                HStack {
                    Label("System", systemImage: "server.rack")
                        .font(.title2.weight(.semibold)).foregroundStyle(accent)
                    Spacer(minLength: 0)
                    if let onRefresh {
                        Button(action: onRefresh) {
                            Image(systemName: "arrow.clockwise").frame(width: 44, height: 36)
                        }
                        .buttonStyle(.plain).foregroundStyle(accent)
                        .jarvisGlassSurface(surface, in: Capsule(), glass: true)
                        .disabled(refreshing)
                        .accessibilityLabel(refreshing ? "Refreshing cached state" : "Refresh cached state")
                    }
                }
            }
            visualCard
        }
        .frame(maxWidth: .infinity, alignment: .top)
        .accessibilityIdentifier("system-dashboard")
        // Compatibility with platform lifecycle gates; this view never covers itself.
        .onAppear { onDetailVisibilityChanged(false) }
        .onDisappear { onDetailVisibilityChanged(false) }
    }

    private var visualCard: some View {
        VStack(alignment: .leading, spacing: compact ? 5 : (presentation.includesDeviceCoverage ? 8 : 12)) {
            HStack(spacing: compact ? 7 : 12) {
                SystemCurrentHealthRing(presentation: presentation, diameter: compact ? 28 : 48)
                    .accessibilityHidden(true)
                Text(status).font(.system(size: compact ? 14 : 22, weight: .semibold))
                    .lineLimit(1).minimumScaleFactor(0.85)
                Spacer(minLength: 0)
                if !compact {
                    Text("Cached").font(.system(size: 10)).foregroundStyle(.secondary)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(status). Current cached checks, not live connectivity or home security. \(connectionLabel). \(connectionError ?? "")")

            timeline

            LazyVGrid(columns: presentation.visualGroups.count > 5
                      ? [GridItem(.adaptive(minimum: compact ? 40 : 62), spacing: compact ? 3 : 8)]
                      : Array(repeating: GridItem(.flexible(), spacing: compact ? 3 : 8), count: compact ? 3 : 5),
                      spacing: compact ? 4 : 8) {
                ForEach(presentation.visualGroups) { group in
                    VStack(spacing: compact ? 1 : 4) {
                        Image(systemName: symbol(group.state))
                            .font(.system(size: compact ? 12 : 20, weight: .medium))
                            .foregroundStyle(color(group.state))
                        Text(compact && group.id == "cast" ? "Cast" : group.title)
                            .font(.system(size: compact ? 8 : 11))
                            .lineLimit(1).minimumScaleFactor(0.8)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(group.accessibilityText + serviceEvidence(group))
                }
            }
            if let exception {
                Text(exception).font(.system(size: compact ? 9 : 11, weight: .medium))
                    .foregroundStyle(.secondary).lineLimit(1).minimumScaleFactor(0.85)
                    .accessibilityLabel(exception + ". " + (historyModel.notice ?? ""))
            }
        }
        .padding(compact ? 6 : (presentation.includesDeviceCoverage ? 12 : 14))
        .frame(maxWidth: .infinity, alignment: .leading)
        .jarvisGlassSurface(surface,
            in: RoundedRectangle(cornerRadius: compact ? 10 : 14, style: .continuous), glass: true)
        .accessibilityIdentifier("system-visual-card")
    }

    private var timeline: some View {
        let series = historyModel.snapshot?.series.first { $0.id == "overall" }
        return VStack(spacing: compact ? 2 : 4) {
            SystemHistoryBand(series: series, height: compact ? 10 : 22)
            HStack {
                Text("−1h")
                Spacer(minLength: 0)
                Text(historyModel.isStale() || !historyModel.isPolling ? "Cached" : compact ? "Cached · 1h" : "Past hour")
                Spacer(minLength: 0)
                Text(historyModel.snapshot?.end?.formatted(date: .omitted, time: .shortened) ?? "—")
            }.font(.system(size: compact ? 7 : 9)).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Past hour of cached observations. One-minute buckets. Hatching means gaps; caps mean partial evidence. "
            + (historyModel.isStale() || !historyModel.isPolling ? "History stale or paused. " : "")
            + (historyModel.notice ?? "") + ". " + (series?.inlineSummary ?? "No recorded history.")
            + ". " + (series?.buckets.map { bucket in
                "\(bucket.start?.formatted(date: .omitted, time: .shortened) ?? "?") to \(bucket.end?.formatted(date: .omitted, time: .shortened) ?? "?"): \(bucket.state.title), \(Int(bucket.coverageSeconds)) seconds observed, \(Int(bucket.missingSeconds)) seconds missing. "
                + bucket.reasonCodes.joined(separator: ", ")
            }.joined(separator: ". ") ?? ""))
        .accessibilityIdentifier("system-health-history")
    }

    private func serviceEvidence(_ group: SystemVisualGroup) -> String {
        guard group.id == "services" else { return "" }
        return ". " + presentation.services.map {
            "\($0.row.title). \($0.requirement), \($0.executionMode). \($0.description ?? ""). \($0.technicalDetails.joined(separator: ". "))"
        }.joined(separator: ". ")
    }

    private func color(_ state: SystemHealthState) -> Color {
        switch state {
        case .healthy: return SystemHistoryPalette.color(.healthy, dark: scheme == .dark)
        case .issue: return warning
        default: return .secondary
        }
    }
    private func symbol(_ state: SystemHealthState) -> String {
        switch state {
        case .healthy: return "checkmark.circle.fill"
        case .issue: return "exclamationmark.triangle.fill"
        case .unknown: return "questionmark.circle"
        case .checking: return "clock"
        case .inactive: return "pause.circle"
        }
    }
}
