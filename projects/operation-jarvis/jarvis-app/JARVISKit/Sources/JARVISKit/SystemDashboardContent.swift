import SwiftUI

/// A fixed, Home-style overview. Only explicitly opened detail sheets scroll.
/// Platforms retain ownership of visibility, refresh policy and networking.
@MainActor
public struct SystemDashboardContent: View {
    @ObservedObject private var historyModel: SystemHistoryModel
    @Environment(\.colorScheme) private var scheme
    public let presentation: SystemDashboardPresentation
    public let connectionLabel: String
    public let compact: Bool
    public let accent: Color
    public let warning: Color
    public let surface: Color
    public let connectionError: String?
    public let refreshing: Bool
    public let onRefresh: (() -> Void)?
    public let onDetailVisibilityChanged: (Bool) -> Void
    @State private var selectedDetail: Detail?

    public init(presentation: SystemDashboardPresentation, connectionLabel: String,
                compact: Bool = false, accent: Color, warning: Color, surface: Color,
                connectionError: String? = nil, refreshing: Bool = false,
                onRefresh: (() -> Void)? = nil, historyModel: SystemHistoryModel? = nil,
                onDetailVisibilityChanged: @escaping (Bool) -> Void = { _ in }) {
        self.historyModel = historyModel ?? SystemHistoryModel()
        self.presentation = presentation
        self.connectionLabel = connectionLabel
        self.compact = compact
        self.accent = accent
        self.warning = warning
        self.surface = surface
        self.connectionError = connectionError
        self.refreshing = refreshing
        self.onRefresh = onRefresh
        self.onDetailVisibilityChanged = onDetailVisibilityChanged
    }

    public var body: some View {
        Group {
            if compact {
                compactOverview
            } else {
                ViewThatFits(in: .vertical) {
                    overview(dense: false).fixedSize(horizontal: false, vertical: true)
                    overview(dense: true).fixedSize(horizontal: false, vertical: true)
                    overview(dense: true, condensed: true).fixedSize(horizontal: false, vertical: true)
                    overview(dense: true, horizontal: true).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .top)
        .accessibilityIdentifier("system-dashboard")
        .sheet(item: $selectedDetail) { route in
            NavigationStack {
                // Detail text remains readable at the owner's full Dynamic Type
                // size without making the overview taller or moving its rows.
                ScrollView {
                    detailContent(route)
                        .padding(compact ? 10 : 16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .navigationTitle("Details")
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { selectedDetail = nil }
                    }
                }
                .tint(accent)
            }
        }
        .onChange(of: selectedDetail?.id) { value in onDetailVisibilityChanged(value != nil) }
        .onDisappear { onDetailVisibilityChanged(false) }
    }

    /// Large group tap targets, rather than tiny buttons for every Watch chip.
    /// Six integrations and the two registered services fit the 40mm canvas.
    private var compactOverview: some View {
        VStack(alignment: .leading, spacing: 3) {
            panel {
                VStack(alignment: .leading, spacing: 3) {
                    Button { selectedDetail = .overview } label: {
                        HStack(spacing: 4) {
                            Text("System").font(.system(size: 14, weight: .semibold)).foregroundStyle(accent)
                            Spacer(minLength: 0)
                            let requestWarning = connectionError != nil && presentation.state == .healthy
                            Text(requestWarning ? "Warning" : presentation.isConnected ? presentation.summary : "Offline")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(color(requestWarning ? .issue : presentation.state))
                                .lineLimit(1).minimumScaleFactor(0.8)
                            SystemCurrentHealthRing(presentation: presentation, diameter: 16)
                        }
                    }.buttonStyle(.plain)
                        .accessibilityLabel("System health, \(presentation.summary), \(connectionLabel). \(connectionError ?? "")")
                    Button { selectedDetail = .history("overall") } label: {
                        VStack(spacing: 2) {
                            SystemHistoryBand(series: historyModel.snapshot?.series.first { $0.id == "overall" }, height: 7)
                            HStack {
                                Text(historyModel.notice != nil || historyModel.isStale() || !historyModel.isPolling ? "Cached / unavailable" : "Past hour")
                                Spacer(minLength: 0)
                                Text(historyEndTime)
                            }.font(.system(size: 7)).foregroundStyle(.secondary)
                        }
                    }.buttonStyle(.plain).accessibilityHint("Opens recorded times, coverage and observation details")
                }
            }
            Button { selectedDetail = .services } label: {
                panel {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            sectionHeading("Services", symbol: "gearshape.2")
                            Spacer(minLength: 0)
                            if presentation.services.count > 2 {
                                Text("+\(presentation.services.count - 2)").font(.system(size: 9)).foregroundStyle(accent)
                            }
                            Image(systemName: "chevron.right").font(.system(size: 7)).foregroundStyle(.secondary)
                        }
                        if presentation.services.isEmpty {
                            Text("Inventory unavailable").font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                        ForEach(Array(presentation.services.prefix(2))) { service in
                            HStack(spacing: 4) {
                                Image(systemName: symbol(service.row.state)).foregroundStyle(color(service.row.state))
                                Text(service.row.title).lineLimit(1).minimumScaleFactor(0.8)
                                Spacer(minLength: 0)
                            }
                            .font(.system(size: 10, weight: .medium)).frame(minHeight: 15)
                        }
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(presentation.services.count) services. " + presentation.services.map {
                "\($0.row.title), \($0.row.state.rawValue), \($0.row.detail)"
            }.joined(separator: ". "))
            .accessibilityHint("Opens all service details")
            Button { selectedDetail = .integrations } label: {
                panel {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            sectionHeading("Integrations", symbol: "waveform.path.ecg")
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.right").font(.system(size: 7)).foregroundStyle(.secondary)
                        }
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 4) {
                            // Backend request failure is already prominent in the
                            // aggregate header; its full explanation is in Details.
                            ForEach(presentation.compactSubsystemRows) { row in
                                HStack(spacing: 3) {
                                    Image(systemName: symbol(row.state)).foregroundStyle(color(row.state))
                                    Text(shortTitle(row)).lineLimit(1).minimumScaleFactor(0.8)
                                    Spacer(minLength: 0)
                                }
                                .font(.system(size: 9, weight: .medium)).frame(minHeight: 12)
                            }
                        }
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Integrations. " + presentation.subsystemRows.map {
                "\($0.title), \($0.state.rawValue), \($0.detail)"
            }.joined(separator: ". "))
            .accessibilityHint("Opens integration freshness details")
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private func overview(dense: Bool, horizontal: Bool = false, condensed: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("System", systemImage: "server.rack")
                    .font(.title2.weight(.semibold)).foregroundStyle(accent)
                Spacer(minLength: 4)
                if horizontal {
                    Button { selectedDetail = .overview } label: {
                        HStack(spacing: 4) {
                            SystemCurrentHealthRing(presentation: presentation, diameter: 26)
                            Text(presentation.summary)
                        }
                    }
                        .font(.caption.weight(.semibold)).foregroundStyle(color(presentation.state))
                        .buttonStyle(.plain)
                        .accessibilityLabel("System health, \(presentation.summary), \(connectionLabel)")
                }
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
            if !horizontal {
                Button { selectedDetail = .overview } label: {
                    panel {
                        HStack(spacing: dense ? 10 : 16) {
                            SystemCurrentHealthRing(presentation: presentation, diameter: condensed ? 36 : dense ? 48 : 60)
                            VStack(alignment: .leading, spacing: 5) {
                            Text("CURRENT CACHED CHECKS").font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
                            HStack(spacing: 5) {
                                Image(systemName: symbol(presentation.state))
                                Text(connectionError == nil ? presentation.summary : "Warning · cached checks").fontWeight(.semibold)
                                    .lineLimit(1).minimumScaleFactor(0.75)
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.right").font(.caption2)
                            }
                            .foregroundStyle(color(connectionError == nil ? presentation.state : .issue))
                            .font(dense ? .system(size: 13, weight: .semibold) : .title3.weight(.semibold))
                            HStack {
                                Text(connectionLabel)
                                Spacer(minLength: 4)
                                Text("\(presentation.services.count) services")
                            }
                            .font(.system(size: dense ? 10 : 11)).foregroundStyle(.secondary).lineLimit(1)
                            if connectionError != nil {
                                Label("Last request failed · tap for details", systemImage: "exclamationmark.triangle")
                                    .font(.system(size: 9)).foregroundStyle(warning).lineLimit(1)
                            }
                            }
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("System health, \(presentation.summary), \(connectionLabel)")
                .accessibilityHint("Opens connection and cached observation details")
            }
            // History owns the phone overview; current inventories live only in
            // the health inspector rather than repeating the same categories.
            phoneHistory(dense: dense)
            Text("Read-only observations · tap history to inspect coverage")
                .font(.system(size: 9)).foregroundStyle(.secondary).lineLimit(1)
        }
    }

    private var historyEndTime: String {
        historyModel.snapshot?.end?.formatted(date: .omitted, time: .shortened) ?? "—"
    }

    private func phoneHistory(dense: Bool) -> some View {
        panel {
            VStack(alignment: .leading, spacing: dense ? 4 : 6) {
                HStack {
                    sectionHeading("Health history", symbol: "clock.arrow.circlepath")
                    Spacer(minLength: 0)
                    Text("24h").font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(accent).padding(.horizontal, 7).padding(.vertical, 3)
                        .background(accent.opacity(0.1), in: Capsule())
                }
                ForEach(["services", "pi", "network", "devices"], id: \.self) { id in
                    let series = historyModel.snapshot?.series.first { $0.id == id }
                    Button { selectedDetail = .history(id) } label: {
                        HStack(spacing: 6) {
                            Text(series?.title ?? (id == "pi" ? "Pi" : id.capitalized))
                                .font(.system(size: dense ? 9 : 11)).foregroundStyle(.secondary)
                                .frame(width: dense ? 46 : 56, alignment: .leading)
                            SystemHistoryBand(series: series, height: dense ? 8 : 12)
                        }
                        .frame(minHeight: dense ? 12 : 18)
                    }.buttonStyle(.plain)
                        .accessibilityLabel("\(series?.title ?? id) historical observations")
                        .accessibilityHint("Opens bucket times, observed states and missing coverage")
                }
                HStack {
                    Text("−24h")
                    Spacer(minLength: 0)
                    Text("Through \(historyEndTime)")
                }.font(.system(size: 8)).foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    historyKey("Healthy", state: .healthy)
                    historyKey("Degraded", state: .degraded)
                    historyKey("Unavailable", state: .unavailable)
                    historyKey("Unknown", state: .unknown)
                }
                Text(historyModel.notice ?? (historyModel.isLoading && historyModel.snapshot == nil ? "Loading recorded history…" :
                    historyModel.snapshot == nil ? "No history loaded · no invented coverage" :
                    historyModel.snapshot?.latestSample == nil ? "No observations in this window" :
                    historyModel.isStale() || !historyModel.isPolling ? "Cached history · hatches mark gaps" : "Hatches: gaps · cap: partial evidence"))
                    .font(.system(size: dense ? 8 : 9)).foregroundStyle(.secondary).lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
        }
        .accessibilityIdentifier("system-health-history")
    }

    private func historyKey(_ title: String, state: SystemHistoryState) -> some View {
        Label { Text(title) } icon: {
            Image(systemName: state.symbol).foregroundStyle(SystemHistoryPalette.color(state, dark: scheme == .dark))
        }.font(.system(size: 7)).foregroundStyle(.secondary)
    }

    private func panel<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        Group {
            if compact {
                content().frame(maxWidth: .infinity, alignment: .leading)
                    .padding(4)
                    .background(surface, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            } else {
                content().frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .jarvisGlassSurface(surface,
                        in: RoundedRectangle(cornerRadius: 14, style: .continuous), glass: true)
            }
        }
    }

    private func sectionHeading(_ title: String, symbol: String) -> some View {
        Label(title, systemImage: symbol)
            .font(.system(size: compact ? 9 : 12, weight: .semibold))
            .foregroundStyle(.secondary)
    }

    private func shortTitle(_ row: SystemHealthRow) -> String {
        switch row.id {
        case "services": return "Service data"
        case "pi": return "Pi sessions"
        case "plugs": return "Plugs"
        case "purifier": return "Purifiers"
        case "security": return compact ? "Sensors" : "Sensor reads"
        case "backendHealth": return "Backend health"
        case "network": return "Network"
        case "codexQuota": return compact ? "Codex" : "Codex usage"
        default: return row.title
        }
    }

    @ViewBuilder
    private func detailContent(_ route: Detail) -> some View {
        switch route {
        case .history(let id):
            SystemHistoryDetails(response: historyModel.snapshot, component: id, notice: historyModel.notice)
        case .overview:
            VStack(alignment: .leading, spacing: 12) {
                Label(presentation.summary, systemImage: symbol(presentation.state)).foregroundStyle(color(presentation.state))
                Text(connectionLabel)
                ForEach(presentation.subsystemRows.filter { ["backend", "backendHealth", "security"].contains($0.id) }) { row in
                    Label(row.detail, systemImage: symbol(row.state)).foregroundStyle(color(row.state))
                }
                if let connectionError { Text(connectionError).foregroundStyle(warning) }
                Text("Services: \(presentation.healthyServiceCount) healthy · \(presentation.issueServiceCount) issues · \(presentation.unknownServiceCount) unknown · \(presentation.inactiveServiceCount) inactive")
                if let uptime = presentation.uptimeText { Text("Snapshot uptime: \(uptime)") }
                if let version = presentation.backendVersion { Text("Backend version: \(version)").font(.caption.monospaced()) }
                Text("Cached software and integration checks—not a live connectivity or security guarantee. No automatic recovery. Scheduled job results remain in Jobs.")
                    .font(.caption).foregroundStyle(.secondary)
                if !compact {
                    // Keep exact current failure/freshness metadata reachable
                    // without duplicating the historical categories on the page.
                    Divider()
                    Text("Current service checks").font(.headline)
                    ForEach(presentation.services) { service in serviceDetails(service) }
                    Divider()
                    Text("Current integration checks").font(.headline)
                    ForEach(presentation.subsystemRows) { row in integrationDetails(row) }
                }
            }
        case .services:
            VStack(alignment: .leading, spacing: 20) {
                ForEach(presentation.services) { service in serviceDetails(service) }
            }
        case .integrations:
            VStack(alignment: .leading, spacing: 20) {
                ForEach(presentation.subsystemRows) { row in integrationDetails(row) }
            }
        }
    }

    private func integrationDetails(_ row: SystemHealthRow) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(row.title).font(.headline)
            Label(row.detail, systemImage: symbol(row.state)).foregroundStyle(color(row.state))
            Text(row.ageText).font(.caption).foregroundStyle(.secondary)
            if let limit = SystemHealthPresentation.freshnessLimits[row.id] {
                Text("Freshness limit: \(Int(limit)) seconds").font(.caption)
            }
            Text("Cached collector observation, not a live device connectivity guarantee.").font(.caption)
        }
    }

    private func serviceDetails(_ service: SystemDashboardService) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(service.row.title).font(.headline)
            Label(service.row.detail, systemImage: symbol(service.row.state)).foregroundStyle(color(service.row.state))
            Text(service.row.ageText).font(.caption).foregroundStyle(.secondary)
            Text("\(service.requirement) · \(service.executionMode)").font(.caption)
            if let description = service.description { Text(description).font(.caption) }
            Text("Last observed details").font(.subheadline.weight(.semibold))
            ForEach(service.technicalDetails, id: \.self) { Text($0).font(.caption.monospaced()) }
        }
    }

    private func color(_ state: SystemHealthState) -> Color {
        switch state { case .healthy: return .green; case .issue: return warning; default: return .secondary }
    }

    private func symbol(_ state: SystemHealthState) -> String {
        switch state {
        case .healthy: return "checkmark.circle"
        case .issue: return "exclamationmark.triangle"
        case .unknown: return "questionmark.circle"
        case .checking: return "clock"
        case .inactive: return "pause.circle"
        }
    }

    private enum Detail: Identifiable {
        case overview, services, integrations, history(String)
        var id: String {
            switch self {
            case .history(let id): return "history:\(id)"
            case .overview: return "overview"
            case .services: return "services"
            case .integrations: return "integrations"
            }
        }
    }
}
