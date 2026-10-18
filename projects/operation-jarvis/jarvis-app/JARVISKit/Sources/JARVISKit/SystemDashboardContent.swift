import SwiftUI

/// Cached Telemetry overview. Platforms retain detail sheets, scrolling, Crown,
/// lifecycle and refresh ownership; this view never requests or changes device state.
@MainActor
public struct SystemDashboardContent: View {
    @ObservedObject private var historyModel: SystemHistoryModel
    @Environment(\.colorScheme) private var scheme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.isLuminanceReduced) private var dimmed
    public let presentation: SystemDashboardPresentation
    public let connectionLabel: String
    public let compact: Bool
    public let showsHeader: Bool
    public let accent: Color
    public let warning: Color
    public let surface: Color
    public let connectionError: String?
    public let refreshing: Bool
    public let active: Bool
    public let onRefresh: (() -> Void)?
    public let onServices: (() -> Void)?
    public let onMinecraft: (() -> Void)?
    public let onDetailVisibilityChanged: (Bool) -> Void

    public init(presentation: SystemDashboardPresentation, connectionLabel: String,
                compact: Bool = false, showsHeader: Bool = true, accent: Color, warning: Color, surface: Color,
                connectionError: String? = nil, refreshing: Bool = false,
                onRefresh: (() -> Void)? = nil, historyModel: SystemHistoryModel? = nil,
                onServices: (() -> Void)? = nil, onMinecraft: (() -> Void)? = nil,
                active: Bool = true,
                onDetailVisibilityChanged: @escaping (Bool) -> Void = { _ in }) {
        self.historyModel = historyModel ?? SystemHistoryModel()
        self.presentation = presentation; self.connectionLabel = connectionLabel
        self.compact = compact; self.showsHeader = showsHeader
        self.accent = accent; self.warning = warning; self.surface = surface
        self.connectionError = connectionError; self.refreshing = refreshing
        self.onRefresh = onRefresh; self.onServices = onServices; self.onMinecraft = onMinecraft
        self.active = active; self.onDetailVisibilityChanged = onDetailVisibilityChanged
    }

    private var current: SystemHealthState {
        if !presentation.isConnected { return .unknown }
        if connectionError != nil { return .issue }
        return presentation.state
    }
    private var status: String {
        if !presentation.isConnected { return "Offline" }
        switch current { case .healthy: return "Healthy"; case .issue: return "Issue"
        case .checking: return "Checking"; case .inactive: return "Inactive"; case .unknown: return "Unknown" }
    }
    private var currentTrusted: Bool {
        presentation.isConnected && connectionError == nil
            && presentation.observationDate.map { $0 <= Date() } == true
    }
    private var telemetry: SystemTelemetryWindow {
        historyModel.telemetryWindow(current: current,
            currentTrusted: currentTrusted && (current == .healthy || current == .issue))
    }
    private var exceptions: [SystemVisualGroup] { presentation.telemetryExceptions }
    private var tint: Color {
        if !presentation.isConnected || (current != .healthy && current != .issue) { return .secondary }
        if current == .issue { return scheme == .dark ? warning : Color(red: 0.62, green: 0.28, blue: 0.02) }
        return scheme == .dark ? Color(red: 0.43, green: 0.89, blue: 0.93) : Color(red: 0.02, green: 0.39, blue: 0.46)
    }
    private var motionAllowed: Bool { active && scenePhase == .active && !reduceMotion && !dimmed }
    private var notice: String? {
        if !presentation.isConnected { return "Offline · cached evidence" }
        if connectionError != nil { return "State request failed" }
        // Overall-only failures must not vanish simply because all visible groups are healthy.
        if let exception = presentation.visualException, exception.hasPrefix("Backend summary") { return exception }
        if let notice = historyModel.notice { return notice }
        if historyModel.isStale() || !historyModel.isPolling, historyModel.snapshot != nil { return "History cached or paused" }
        return telemetry.notice
    }
    private struct Input: Equatable {
        let current: SystemHealthState
        let observedAt: Date?
        let historyEnd: Date?
        let trusted: Bool
        let polling: Bool
        let notice: String?
    }
    private var input: Input {
        .init(current: current, observedAt: presentation.observationDate, historyEnd: historyModel.snapshot?.end,
              trusted: currentTrusted, polling: historyModel.isPolling, notice: historyModel.notice)
    }
    private func observe() {
        historyModel.observeTelemetry(current: current, observedAt: presentation.observationDate,
                                      currentTrusted: currentTrusted)
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 0 : 10) {
            if !compact && showsHeader {
                HStack {
                    Label("System", systemImage: "server.rack").font(.title2.weight(.semibold)).foregroundStyle(accent)
                    Spacer(minLength: 0)
                    if let onRefresh {
                        Button(action: onRefresh) {
                            Image(systemName: "arrow.clockwise").frame(width: 44, height: 44)
                        }.buttonStyle(.plain).foregroundStyle(accent)
                            .disabled(refreshing).accessibilityLabel("Refresh cached state")
                    }
                }
            }
            visualCard
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("system-dashboard")
        .onAppear { onDetailVisibilityChanged(false); observe() }
        .onChange(of: input) { _ in observe() }
        .onDisappear { onDetailVisibilityChanged(false) }
    }

    private var visualCard: some View {
        VStack(alignment: .leading, spacing: compact ? 5 : 12) {
            HStack(alignment: .center, spacing: 6) {
                Text(status).font(compact ? .headline : .largeTitle.weight(.light))
                    .foregroundStyle(current == .issue ? tint : .primary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityLabel("\(status). Current cached checks, not live connectivity or home security. \(connectionLabel). \(connectionError ?? "")")
                Spacer(minLength: 0)
            }
            if !compact { Divider().overlay(tint.opacity(0.1)) }
            Text(telemetry.title.uppercased() + (compact ? " · CACHED" : ""))
                .font(compact ? .system(size: 8, design: .monospaced) : .caption2.monospaced())
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            SystemTelemetryChart(window: telemetry, compact: compact,
                                 active: active && scenePhase == .active && !dimmed,
                                 height: compact ? (exceptions.isEmpty ? 72 : 52) : (exceptions.isEmpty ? 170 : 122))
            if let notice {
                Text(notice).font(compact ? .caption2 : .footnote).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !exceptions.isEmpty {
                if !compact { Divider() }
                VStack(spacing: compact ? 3 : 5) {
                    ForEach(exceptions) { group in exceptionRow(group).transition(.opacity) }
                }
                // Animate confirmed removals only; no morphing of historical evidence.
                .animation(motionAllowed ? .easeOut(duration: 0.2) : nil, value: exceptions.map(\.id))
            }
        }
        .padding(compact ? 7 : 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .jarvisGlassSurface(surface, in: RoundedRectangle(cornerRadius: compact ? 14 : 23, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: compact ? 14 : 23).stroke(tint.opacity(dimmed ? 0.12 : 0.32), lineWidth: 0.8))
        .accessibilityIdentifier("system-visual-card")
    }

    @ViewBuilder private func exceptionRow(_ group: SystemVisualGroup) -> some View {
        if (group.id == "services" && onServices != nil) || (group.id == "minecraft" && onMinecraft != nil) {
            Button(action: { if group.id == "services" { onServices?() } else { onMinecraft?() } }) {
                exceptionContent(group, actionable: true)
            }.buttonStyle(.plain)
                .accessibilityIdentifier(group.id == "services" ? "system-services-button" : "system-minecraft-button")
                .accessibilityHint("Shows read-only status")
        } else { exceptionContent(group, actionable: false) }
    }

    private func exceptionContent(_ group: SystemVisualGroup, actionable: Bool) -> some View {
        let color: Color = group.state == .issue ? tintForIssue : .secondary
        return HStack(spacing: compact ? 5 : 8) {
            Image(systemName: symbol(group.state))
                .font(.system(size: compact ? 12 : 16, weight: .medium)).foregroundStyle(color)
            VStack(alignment: .leading, spacing: 2) {
                Text(group.title).font(compact ? .caption2.weight(.medium) : .subheadline.weight(.medium))
                if dynamicTypeSize.isAccessibilitySize { Text(label(group.state)).font(.caption2).foregroundStyle(color) }
            }.fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 2)
            if !dynamicTypeSize.isAccessibilitySize {
                Text(label(group.state)).font(.caption2).foregroundStyle(color)
            }
            if actionable { Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.secondary) }
        }
        .padding(.horizontal, compact ? 5 : 9).padding(.vertical, 4)
        .frame(maxWidth: .infinity, minHeight: actionable ? (compact ? 32 : 44) : nil, alignment: .leading)
        .background(color.opacity(0.055), in: RoundedRectangle(cornerRadius: compact ? 6 : 9))
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(group.accessibilityText + serviceEvidence(group))
    }
    private var tintForIssue: Color { scheme == .dark ? warning : Color(red: 0.62, green: 0.28, blue: 0.02) }
    private func label(_ state: SystemHealthState) -> String {
        switch state { case .issue: return "Issue"; case .unknown: return "Unverified"
        case .checking: return "Checking"; case .inactive: return "Inactive"; case .healthy: return "Healthy" }
    }
    private func symbol(_ state: SystemHealthState) -> String {
        switch state { case .issue: return "exclamationmark.triangle"; case .unknown: return "questionmark.circle"
        case .checking: return "clock"; case .inactive: return "pause.circle"; case .healthy: return "circle" }
    }
    private func serviceEvidence(_ group: SystemVisualGroup) -> String {
        let services = group.id == "services" ? presentation.backgroundServices : group.id == "minecraft" ? presentation.minecraftServices : []
        return ". " + services.map { "\($0.row.title). \($0.requirement), \($0.executionMode). \($0.description ?? ""). \($0.technicalDetails.joined(separator: ". "))" }.joined(separator: ". ")
    }
}
