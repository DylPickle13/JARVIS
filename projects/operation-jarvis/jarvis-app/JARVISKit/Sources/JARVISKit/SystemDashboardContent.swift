import SwiftUI

/// A fixed, Home-style overview. Only explicitly opened detail sheets scroll.
/// Platforms retain ownership of visibility, refresh policy and networking.
public struct SystemDashboardContent: View {
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
                onRefresh: (() -> Void)? = nil,
                onDetailVisibilityChanged: @escaping (Bool) -> Void = { _ in }) {
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
        VStack(alignment: .leading, spacing: 4) {
            Button { selectedDetail = .overview } label: {
                panel {
                    HStack(spacing: 4) {
                        Text("System").font(.system(size: 14, weight: .semibold)).foregroundStyle(accent)
                        Spacer(minLength: 0)
                        let requestWarning = connectionError != nil && presentation.state == .healthy
                        Image(systemName: symbol(requestWarning ? .issue : presentation.state))
                            .foregroundStyle(color(requestWarning ? .issue : presentation.state))
                        Text(requestWarning ? "Warning" : presentation.isConnected ? presentation.summary : "Offline")
                            .foregroundStyle(color(requestWarning ? .issue : presentation.state))
                            .lineLimit(1).minimumScaleFactor(0.8)
                    }
                    .font(.system(size: 10, weight: .medium))
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("System health, \(presentation.summary), \(connectionLabel)")
            .accessibilityHint("Opens connection details. \(connectionError ?? "")")
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
                            .font(.system(size: 10, weight: .medium)).frame(minHeight: 18)
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
                            ForEach(presentation.subsystemRows.filter { $0.id != "backend" }) { row in
                                HStack(spacing: 3) {
                                    Image(systemName: symbol(row.state)).foregroundStyle(color(row.state))
                                    Text(shortTitle(row)).lineLimit(1).minimumScaleFactor(0.8)
                                    Spacer(minLength: 0)
                                }
                                .font(.system(size: 9, weight: .medium)).frame(minHeight: 15)
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

    private func overview(dense: Bool, horizontal: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("System", systemImage: "server.rack")
                    .font(.title2.weight(.semibold)).foregroundStyle(accent)
                Spacer(minLength: 4)
                if horizontal {
                    Button(presentation.summary) { selectedDetail = .overview }
                        .font(.caption.weight(.semibold)).foregroundStyle(color(presentation.state))
                        .buttonStyle(.plain)
                        .accessibilityLabel("System health, \(presentation.summary), \(connectionLabel)")
                }
                if let onRefresh {
                    Button(action: onRefresh) {
                        Image(systemName: "arrow.clockwise").frame(width: 44, height: 36)
                    }
                    .buttonStyle(.plain).foregroundStyle(accent).disabled(refreshing)
                    .accessibilityLabel(refreshing ? "Refreshing cached state" : "Refresh cached state")
                }
            }
            if !horizontal {
                Button { selectedDetail = .overview } label: {
                    panel {
                        VStack(alignment: .leading, spacing: 5) {
                            HStack(spacing: 5) {
                                Image(systemName: symbol(presentation.state))
                                Text(presentation.summary).fontWeight(.semibold)
                                    .lineLimit(1).minimumScaleFactor(0.75)
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.right").font(.caption2)
                            }
                            .foregroundStyle(color(presentation.state)).font(.subheadline)
                            HStack {
                                Text(connectionLabel)
                                Spacer(minLength: 4)
                                Text("\(presentation.services.count) services")
                            }
                            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            if connectionError != nil {
                                Label("Last request failed · tap for details", systemImage: "exclamationmark.triangle")
                                    .font(.caption2).foregroundStyle(warning).lineLimit(1)
                            }
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("System health, \(presentation.summary), \(connectionLabel)")
                .accessibilityHint("Opens connection and cached observation details")
            }
            let layout = horizontal
                ? AnyLayout(HStackLayout(alignment: .top, spacing: 10))
                : AnyLayout(VStackLayout(alignment: .leading, spacing: 10))
            layout {
                phoneServices(dense: dense)
                phoneIntegrations(dense: dense)
            }
            Text("Cached checks · read-only · tap a row for details")
                .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
        }
    }

    private func phoneServices(dense: Bool) -> some View {
        panel {
            VStack(alignment: .leading, spacing: 7) {
                sectionHeading("Services", symbol: "gearshape.2")
                let limit = dense ? 2 : 4
                if presentation.services.isEmpty {
                    Text("Service inventory unavailable").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(Array(presentation.services.prefix(limit))) { service in
                    Button { selectedDetail = .service(service.id) } label: {
                        HStack(spacing: 8) {
                            Image(systemName: symbol(service.row.state))
                                .foregroundStyle(color(service.row.state)).accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(service.row.title).font(.subheadline.weight(.medium))
                                    .lineLimit(1).minimumScaleFactor(0.75)
                                if !dense {
                                    Text("\(service.requirement) · \(service.executionMode)")
                                        .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                                }
                            }
                            Spacer(minLength: 0)
                            statusBadge(service.row, service: true)
                            Image(systemName: "chevron.right").font(.system(size: 10))
                                .foregroundStyle(.secondary).accessibilityHidden(true)
                        }
                        .frame(minHeight: dense ? 32 : 42).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(service.row.title), \(service.row.state.rawValue), \(service.row.detail), \(service.row.ageText)")
                    .accessibilityHint("Opens last observed service details")
                    .accessibilityIdentifier("system-service-\(service.id)-details")
                }
                if presentation.services.count > limit {
                    Button("All \(presentation.services.count) services…") { selectedDetail = .services }
                        .font(.caption).foregroundStyle(accent)
                        .accessibilityHint("Includes services not shown in this overview")
                }
            }
        }
    }

    private func phoneIntegrations(dense: Bool) -> some View {
        panel {
            VStack(alignment: .leading, spacing: 7) {
                sectionHeading("Integrations", symbol: "waveform.path.ecg")
                if dense {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 6) {
                        ForEach(presentation.subsystemRows) { row in
                            Button { selectedDetail = .subsystem(row.id) } label: {
                                HStack(spacing: 4) {
                                    Image(systemName: symbol(row.state)).foregroundStyle(color(row.state))
                                        .accessibilityHidden(true)
                                    Text(shortTitle(row)).lineLimit(1).minimumScaleFactor(0.75)
                                    Spacer(minLength: 0)
                                }
                                .font(.caption.weight(.medium)).frame(minHeight: 30).contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(row.title), \(row.state.rawValue), \(row.detail), \(row.ageText)")
                            .accessibilityIdentifier("system-integration-\(row.id)")
                        }
                    }
                } else {
                    ForEach(presentation.subsystemRows) { row in
                        Button { selectedDetail = .subsystem(row.id) } label: {
                            HStack(spacing: 8) {
                                Image(systemName: symbol(row.state)).foregroundStyle(color(row.state))
                                    .accessibilityHidden(true)
                                Text(shortTitle(row)).font(.subheadline).lineLimit(1).minimumScaleFactor(0.8)
                                Spacer(minLength: 4)
                                Text(age(row)).font(.caption2).monospacedDigit().foregroundStyle(.secondary)
                                statusBadge(row, service: false)
                            }
                            .frame(minHeight: 30).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(row.title), \(row.state.rawValue), \(row.detail), \(row.ageText)")
                        .accessibilityIdentifier("system-integration-\(row.id)")
                    }
                }
            }
        }
    }

    private func panel<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        content().frame(maxWidth: .infinity, alignment: .leading)
            .padding(compact ? 5 : 12)
            .background(surface, in: RoundedRectangle(cornerRadius: compact ? 10 : 14, style: .continuous))
    }

    private func sectionHeading(_ title: String, symbol: String) -> some View {
        Label(title, systemImage: symbol)
            .font(compact ? .system(size: 10, weight: .semibold) : .subheadline.weight(.semibold))
            .foregroundStyle(.secondary)
    }

    private func statusBadge(_ row: SystemHealthRow, service: Bool) -> some View {
        Text(status(row, service: service))
            .font(.caption2.weight(.medium)).lineLimit(1)
            .foregroundStyle(color(row.state))
            .padding(.horizontal, 6).padding(.vertical, 3)
            .background(color(row.state).opacity(0.08), in: RoundedRectangle(cornerRadius: 5))
    }

    private func status(_ row: SystemHealthRow, service: Bool) -> String {
        switch row.state {
        case .healthy: return service ? "Healthy" : "Current"
        case .issue: return row.detail.hasPrefix("Stale") ? "Stale" : "Issue"
        case .checking: return "Checking"
        case .unknown: return "Unknown"
        case .inactive: return "Inactive"
        }
    }

    private func shortTitle(_ row: SystemHealthRow) -> String {
        switch row.id {
        case "services": return "Service data"
        case "pi": return "Pi sessions"
        case "plugs": return "Plugs"
        case "purifier": return "Purifiers"
        case "network": return "Network"
        case "codexQuota": return compact ? "Codex" : "Codex usage"
        default: return row.title
        }
    }

    private func age(_ row: SystemHealthRow) -> String {
        guard let age = row.ageSeconds, age.isFinite, age >= 0 else { return "—" }
        if age < 60 { return "\(Int(age))s" }
        if age < 3600 { return "\(Int(age / 60))m" }
        if age < 86400 { return "\(Int(age / 3600))h" }
        return "\(Int(min(age / 86400, 999999)))d"
    }

    @ViewBuilder
    private func detailContent(_ route: Detail) -> some View {
        switch route {
        case .overview:
            VStack(alignment: .leading, spacing: 12) {
                Label(presentation.summary, systemImage: symbol(presentation.state)).foregroundStyle(color(presentation.state))
                Text(connectionLabel)
                if let backend = presentation.subsystemRows.first(where: { $0.id == "backend" }) {
                    Label(backend.detail, systemImage: symbol(backend.state)).foregroundStyle(color(backend.state))
                }
                if let connectionError { Text(connectionError).foregroundStyle(warning) }
                Text("Services: \(presentation.healthyServiceCount) healthy · \(presentation.issueServiceCount) issues · \(presentation.unknownServiceCount) unknown · \(presentation.inactiveServiceCount) inactive")
                if let uptime = presentation.uptimeText { Text("Snapshot uptime: \(uptime)") }
                if let version = presentation.backendVersion { Text("Backend version: \(version)").font(.caption.monospaced()) }
                Text("Cached software and integration checks—not a live connectivity or security guarantee. No automatic recovery. Scheduled job results remain in Jobs.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        case .service(let id):
            if let service = presentation.services.first(where: { $0.id == id }) { serviceDetails(service) }
            else { Text("Service no longer present in the cached inventory.") }
        case .services:
            VStack(alignment: .leading, spacing: 20) {
                ForEach(presentation.services) { service in serviceDetails(service) }
            }
        case .integrations:
            VStack(alignment: .leading, spacing: 20) {
                ForEach(presentation.subsystemRows) { row in integrationDetails(row) }
            }
        case .subsystem(let id):
            if let row = presentation.subsystemRows.first(where: { $0.id == id }) {
                integrationDetails(row)
            } else { Text("Integration no longer present in the snapshot.") }
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
        case overview, services, integrations, service(String), subsystem(String)
        var id: String {
            switch self {
            case .overview: return "overview"
            case .services: return "services"
            case .integrations: return "integrations"
            case .service(let id): return "service:\(id)"
            case .subsystem(let id): return "subsystem:\(id)"
            }
        }
    }
}
