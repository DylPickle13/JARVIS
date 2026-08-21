import SwiftUI
import JARVISKit

struct HomeView: View {
    @EnvironmentObject var app: AppState
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var fanLocal: Double = 2
    @State private var isDraggingFan = false
    @State private var pendingServiceAction: PendingServiceAction?
    @State private var scheduledJobsExpanded = true

    private struct PendingServiceAction {
        let name: String
        let displayName: String
        let action: String
        let message: String
    }

    private var usesAccessibilityLayout: Bool { dynamicTypeSize.isAccessibilitySize }
    private var gridColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 12), count: usesAccessibilityLayout ? 1 : 2)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    statusHeader
                    if let operationError = app.operationErrorMessage {
                        OperationErrorCard(message: operationError)
                    }

                    if app.connectionState == .connecting || (app.connectionState == .connected && app.lastState == nil) {
                        loadingCard
                    } else if app.connectionState == .connected, let state = app.lastState {
                        if state.loading == true && state.subsystems == nil {
                            loadingCard
                        }
                        piCard(state)
                        plugsSection(state)
                        purifierSection(state)
                        servicesSection
                    } else {
                        notConnectedCard
                    }
                }
                .padding(.horizontal)
                .padding(.bottom, 8)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("JARVIS")
            .refreshable { await refreshHome() }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await refreshHome() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh home status")
                    .disabled(app.isStateLoading || app.servicesLoading || app.connectionState != .connected)
                }
            }
            .confirmationDialog(
                serviceConfirmationTitle,
                isPresented: Binding(
                    get: { pendingServiceAction != nil },
                    set: { if !$0 { pendingServiceAction = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button(
                    pendingServiceAction?.action.capitalized ?? "Continue",
                    role: pendingServiceAction?.action == "stop" ? .destructive : nil
                ) {
                    if let target = pendingServiceAction {
                        Task { await performServiceAction(target.name, target.action) }
                    }
                    pendingServiceAction = nil
                }
                Button("Cancel", role: .cancel) { pendingServiceAction = nil }
            } message: {
                Text(pendingServiceAction?.message ?? "")
            }
        }
    }

    @ViewBuilder
    private var statusHeader: some View {
        if usesAccessibilityLayout {
            VStack(alignment: .leading, spacing: 6) {
                ConnectionBadge(state: app.connectionState, detail: statusDetail)
                if let ip = app.currentEndpoint?.host, ip != networkLabel {
                    Text(ip)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 4)
        } else {
            HStack {
                ConnectionBadge(state: app.connectionState, detail: statusDetail)
                Spacer()
                if let ip = app.currentEndpoint?.host {
                    Text(ip).font(.caption.monospaced()).foregroundStyle(.secondary)
                }
            }
            .padding(.top, 4)
        }
    }

    private var statusDetail: String {
        switch app.connectionState {
        case .connected:
            return app.isStateLoading ? "Connected · refreshing" : "Connected · \(networkLabel)"
        case .connecting: return "Connecting…"
        case .failed: return "Offline"
        case .idle: return "Not connected"
        }
    }

    private var networkLabel: String {
        guard let host = app.currentEndpoint?.host else { return "—" }
        if host.hasPrefix("100.") { return "Tailscale" }
        if host.hasPrefix("192.168") || host.hasPrefix("10.") || host.hasPrefix("172.") { return "LAN" }
        return host
    }

    private var loadingCard: some View {
        Card {
            HStack(spacing: 12) {
                ProgressView()
                VStack(alignment: .leading, spacing: 2) {
                    Text("Loading status…")
                        .font(.headline)
                    Text("jarvisd is connected; subsystem data is arriving.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }

    // MARK: - Pi

    private func piCard(_ state: StateSnapshot) -> some View {
        guard let pi = state.subsystems?.pi, pi.ok == true, let active = pi.active else {
            return AnyView(unavailableCard(title: "Pi sessions unavailable", detail: state.subsystems?.pi?.error))
        }
        let content = Card {
            HStack(spacing: 14) {
                Image(systemName: "terminal").font(.title2).foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Pi sessions").font(.headline)
                    Text("\(active) active").font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Pi sessions: \(active) active")
        if pi.stale == true {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Pi session data is stale.") })
        }
        return AnyView(content)
    }

    // MARK: - Purifier

    private func purifierSection(_ state: StateSnapshot) -> AnyView {
        guard let purifier = state.subsystems?.purifier, purifier.ok == true else {
            return AnyView(unavailableCard(title: "Air purifier unavailable", detail: state.subsystems?.purifier?.lastError ?? state.subsystems?.purifier?.error))
        }
        let isOn = purifier.isOn
        let mode = ["auto", "manual", "sleep", "pet"].contains(purifier.mode ?? "") ? (purifier.mode ?? "auto") : "auto"
        let fan = purifier.fanSetLevel ?? purifier.fanLevel
        let busy = app.isOperationBusy("purifier")
        let stale = state.stale == true || purifier.stale == true
        let content = VStack(alignment: .leading, spacing: 8) {
            if usesAccessibilityLayout {
                VStack(alignment: .leading, spacing: 8) {
                    Label("Air purifier", systemImage: "wind").font(.headline)
                    Toggle("Power", isOn: powerBinding)
                        .accessibilityLabel("Air purifier power")
                        .disabled(isOn == nil || stale || busy)
                }
                .padding(.horizontal, 4)
            } else {
                HStack {
                    Label("Air purifier", systemImage: "wind").font(.headline)
                    Spacer()
                    Toggle("Power", isOn: powerBinding)
                        .labelsHidden()
                        .accessibilityLabel("Air purifier power")
                        .disabled(isOn == nil || stale || busy)
                }
                .padding(.horizontal, 4)
            }

            Card {
                VStack(alignment: .leading, spacing: 14) {
                    if usesAccessibilityLayout {
                        VStack(alignment: .leading, spacing: 8) {
                            purifierReading(purifier)
                            Text("\(mode.capitalized) · fan \(fan.map(String.init) ?? "—")")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    } else {
                        HStack(alignment: .firstTextBaseline) {
                            purifierReading(purifier)
                            Spacer()
                            Text("\(mode.capitalized) · fan \(fan.map(String.init) ?? "—")")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if usesAccessibilityLayout {
                        Picker("Mode", selection: modeBinding) {
                            Text("Auto").tag("auto")
                            Text("Manual").tag("manual")
                            Text("Sleep").tag("sleep")
                            Text("Pet").tag("pet")
                        }
                        .pickerStyle(.menu)
                        .disabled(isOn != true || stale || busy)
                        .accessibilityLabel("Air purifier mode")
                    } else {
                        Picker("Mode", selection: modeBinding) {
                            Text("Auto").tag("auto")
                            Text("Manual").tag("manual")
                            Text("Sleep").tag("sleep")
                            Text("Pet").tag("pet")
                        }
                        .pickerStyle(.segmented)
                        .disabled(isOn != true || stale || busy)
                        .accessibilityLabel("Air purifier mode")
                    }

                    if usesAccessibilityLayout {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Fan \(isDraggingFan ? "\(Int(fanLocal))" : (fan.map(String.init) ?? "—"))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            purifierFanSlider(isOn: isOn, mode: mode, stale: stale, busy: busy, fan: fan)
                        }
                    } else {
                        HStack(spacing: 10) {
                            Text("Fan").font(.caption).foregroundStyle(.secondary)
                            purifierFanSlider(isOn: isOn, mode: mode, stale: stale, busy: busy, fan: fan)
                            Text(isDraggingFan ? "\(Int(fanLocal))" : (fan.map(String.init) ?? "—"))
                                .font(.body.monospacedDigit())
                                .frame(width: 18)
                        }
                    }
                }
            }
        }
        .accessibilityElement(children: .contain)
        if stale {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Air-purifier data is stale.") })
        }
        return AnyView(content)
    }

    private func purifierReading(_ purifier: PurifierSubsystem) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(purifier.pm25.map { "\($0) µg/m³" } ?? "—")
                .font(.title2.weight(.medium))
                .monospacedDigit()
            Text("PM2.5").font(.caption).foregroundStyle(.secondary)
        }
    }

    private func purifierFanSlider(
        isOn: Bool?,
        mode: String,
        stale: Bool,
        busy: Bool,
        fan: Int?
    ) -> some View {
        Slider(
            value: Binding(
                get: { isDraggingFan ? fanLocal : Double(fan ?? 2) },
                set: { fanLocal = $0 }
            ),
            in: 1...4,
            step: 1
        ) { editing in
            isDraggingFan = editing
            if !editing {
                let level = Int(fanLocal.rounded())
                Task { await app.setPurifierFan(level) }
            }
        }
        .disabled(isOn != true || mode != "manual" || stale || busy)
    }

    // MARK: - Plugs

    private func plugsSection(_ state: StateSnapshot) -> some View {
        guard let subsystem = state.subsystems?.plugs, subsystem.ok == true else {
            return AnyView(unavailableCard(title: "Plugs unavailable", detail: state.subsystems?.plugs?.lastError ?? state.subsystems?.plugs?.error))
        }
        let plugs = subsystem.plugs ?? [:]
        let items = plugs.keys.sorted().map { (name: $0, isOn: plugs[$0]?.isOn) }
        return AnyView(VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Plugs", systemImage: "powerplug").font(.headline)
                Spacer()
                if let on = subsystem.onCount, let total = subsystem.count {
                    Text("\(on) / \(total) on")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }
            .padding(.horizontal, 4)

            if items.isEmpty {
                Card { Text("No plugs configured.").foregroundStyle(.secondary) }
            } else {
                LazyVGrid(columns: gridColumns, spacing: 12) {
                    ForEach(items, id: \.name) { item in
                        Button {
                            guard let isOn = item.isOn else { return }
                            Task { await app.setPlug(item.name, isOn: !isOn) }
                        } label: {
                            PlugCard(name: item.name, isOn: item.isOn, isBusy: app.isOperationBusy("plug:\(item.name)"))
                        }
                        .buttonStyle(.plain)
                        .disabled(item.isOn == nil || state.stale == true || subsystem.stale == true || app.isOperationBusy("plug:\(item.name)"))
                        .accessibilityLabel("\(JarvisFormat.displayName(item.name)) plug")
                        .accessibilityValue(item.isOn.map { $0 ? "on" : "off" } ?? "unavailable")
                        .accessibilityHint(item.isOn == nil ? "State unavailable" : (state.stale == true || subsystem.stale == true ? "State is stale; refresh before changing it" : "Double tap to set the opposite state"))
                    }
                }
            }
            if state.stale == true || subsystem.stale == true { staleCaption("Plug data is stale.") }
        }
        .accessibilityElement(children: .contain))
    }

    // MARK: - Services

    private var sortedServices: [(name: String, service: ServiceActionResult)] {
        app.lastServices.map { (name: $0.key, service: $0.value) }.sorted { left, right in
            let leftOrder = left.service.sortOrder ?? 1_000
            let rightOrder = right.service.sortOrder ?? 1_000
            if leftOrder != rightOrder { return leftOrder < rightOrder }
            let leftName = left.service.displayName ?? JarvisFormat.displayName(left.name)
            let rightName = right.service.displayName ?? JarvisFormat.displayName(right.name)
            return leftName.localizedCaseInsensitiveCompare(rightName) == .orderedAscending
        }
    }

    @ViewBuilder
    private var servicesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Services", systemImage: "gearshape.2").font(.headline)
                Spacer()
                if app.servicesLoading || app.scheduledJobsLoading {
                    ProgressView()
                        .controlSize(.small)
                        .accessibilityLabel("Refreshing services and scheduled jobs")
                }
            }
            .padding(.horizontal, 4)

            Text("Runtime services")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 4)

            if let error = app.servicesErrorMessage {
                statusErrorCard(title: "Runtime status unavailable", message: error)
            }
            if !app.servicesLoaded {
                loadingStatusCard("Loading runtime services…")
            } else if sortedServices.isEmpty {
                Card { Text("No registered runtime services.").foregroundStyle(.secondary) }
            } else {
                ForEach(sortedServices, id: \.name) { item in
                    serviceCard(name: item.name, service: item.service)
                }
            }

            scheduledJobsSection
            daemonCard
        }
        .accessibilityElement(children: .contain)
    }

    private func serviceCard(name: String, service: ServiceActionResult) -> some View {
        let isKnown = service.ok
        let isLoaded = service.loaded == true
        let isRunning = service.running == true
        let isUnconfigured = service.configured == false && !isLoaded
        let busy = app.isOperationBusy("service:\(name)")
        let allowed = Set(service.allowedActions ?? [])
        let displayName = service.displayName ?? JarvisFormat.displayName(name)
        let status = !isKnown ? "Unknown" : (isRunning ? "Running" : (isUnconfigured ? "Unconfigured" : (isLoaded ? "Stopped" : "Unloaded")))
        let color: Color = !isKnown || isUnconfigured ? .orange : (isRunning ? .green : .secondary)
        return Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Circle()
                        .fill(color)
                        .frame(width: 10, height: 10)
                    Text(displayName)
                        .font(.headline)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    Text(status)
                        .font(.subheadline)
                        .foregroundStyle(color)
                }
                if let description = service.description, !description.isEmpty {
                    Text(description)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if isRunning, let pid = service.pid {
                    Text("PID \(pid)").font(.caption).foregroundStyle(.tertiary)
                } else if isUnconfigured {
                    Text("LaunchAgent configuration is unavailable.")
                        .font(.caption)
                        .foregroundStyle(.orange)
                } else if !isKnown, let error = service.error {
                    Text(error).font(.caption).foregroundStyle(.orange)
                }

                if allowed.isEmpty {
                    Label("Read-only status", systemImage: "eye")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    HStack(spacing: 12) {
                        if isRunning, allowed.contains("stop") {
                            Button(role: .destructive) {
                                requestServiceAction(name: name, service: service, action: "stop")
                            } label: {
                                Label("Stop", systemImage: "stop.fill").frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .disabled(busy)
                        } else if !isRunning, allowed.contains("start") {
                            Button {
                                requestServiceAction(name: name, service: service, action: "start")
                            } label: {
                                Label("Start", systemImage: "play.fill").frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(busy || !isKnown || isUnconfigured)
                        }
                        if allowed.contains("restart") {
                            Button {
                                requestServiceAction(name: name, service: service, action: "restart")
                            } label: {
                                Label("Restart", systemImage: "arrow.clockwise").frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .disabled(busy || !isKnown || isUnconfigured)
                        }
                    }
                }
                if busy {
                    ProgressView("Applying action…")
                        .font(.caption)
                        .accessibilityLabel("Applying service action")
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var scheduledJobsSection: some View {
        DisclosureGroup(isExpanded: $scheduledJobsExpanded) {
            VStack(alignment: .leading, spacing: 8) {
                if let error = app.scheduledJobsErrorMessage {
                    statusErrorCard(title: "Scheduled jobs unavailable", message: error)
                }
                if !app.scheduledJobsLoaded {
                    loadingStatusCard("Loading scheduled jobs…")
                } else if app.lastScheduledJobs.isEmpty {
                    Card { Text("No scheduled jobs configured.").foregroundStyle(.secondary) }
                } else {
                    ForEach(app.lastScheduledJobs) { job in
                        scheduledJobCard(job)
                    }
                }
            }
            .padding(.top, 8)
        } label: {
            HStack {
                Label("Scheduled jobs", systemImage: "calendar.badge.clock")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                if let summary = app.scheduledJobsSummary {
                    Text("\(summary.enabled) of \(summary.total) enabled")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }
        }
        .padding(.horizontal, 4)
        .accessibilityHint(scheduledJobsExpanded ? "Double tap to collapse scheduled jobs" : "Double tap to expand scheduled jobs")
    }

    private func scheduledJobCard(_ job: ScheduledJob) -> some View {
        let status = job.lastStatus ?? "never run"
        return Card {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Circle()
                        .fill(job.enabled ? scheduledJobStatusColor(job.lastStatus) : Color.secondary)
                        .frame(width: 10, height: 10)
                    Text(JarvisFormat.displayName(job.name))
                        .font(.headline)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    Text(job.enabled ? "Enabled" : "Disabled")
                        .font(.subheadline)
                        .foregroundStyle(job.enabled ? .green : .secondary)
                }
                Text(JarvisFormat.scheduleDescription(kind: job.kind, schedule: job.schedule))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let description = job.description, !description.isEmpty {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let next = JarvisFormat.localDateTime(job.nextRunAt) {
                    LabeledContent("Next", value: next)
                        .font(.caption)
                } else {
                    LabeledContent("Next", value: job.enabled ? "Pending" : "Not scheduled")
                        .font(.caption)
                }
                HStack {
                    Text("Last: \(status)")
                        .foregroundStyle(scheduledJobStatusColor(job.lastStatus))
                    Spacer()
                    if !JarvisFormat.relativeTime(job.lastRunAt).isEmpty {
                        Text("\(JarvisFormat.relativeTime(job.lastRunAt)) ago")
                    }
                    Text("· \(job.runCount) runs")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospacedDigit()
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(scheduledJobAccessibilityLabel(job))
    }

    private func scheduledJobStatusColor(_ status: String?) -> Color {
        switch status {
        case "success": return .green
        case "error": return .red
        case "running": return .orange
        default: return .secondary
        }
    }

    private func scheduledJobAccessibilityLabel(_ job: ScheduledJob) -> String {
        let enabled = job.enabled ? "enabled" : "disabled"
        let next = JarvisFormat.localDateTime(job.nextRunAt) ?? "not scheduled"
        let last = job.lastStatus ?? "never run"
        return "\(JarvisFormat.displayName(job.name)), \(enabled). \(JarvisFormat.scheduleDescription(kind: job.kind, schedule: job.schedule)). Next \(next). Last status \(last). \(job.runCount) runs."
    }

    private func loadingStatusCard(_ message: String) -> some View {
        Card {
            HStack(spacing: 12) {
                ProgressView()
                Text(message).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func statusErrorCard(title: String, message: String) -> some View {
        Card {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.subheadline.weight(.semibold))
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var daemonCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                Label("jarvisd", systemImage: "server.rack").font(.headline)
                if let version = app.lastHealth?.version {
                    LabeledContent("Version", value: version).font(.subheadline)
                }
                if let uptime = app.lastHealth?.uptimeSeconds {
                    LabeledContent("Uptime", value: JarvisFormat.uptime(uptime)).font(.subheadline)
                }
                if app.lastHealth == nil {
                    Text("Daemon info unavailable.").font(.subheadline).foregroundStyle(.secondary)
                }
            }
        }
    }

    private var serviceConfirmationTitle: String {
        guard let target = pendingServiceAction else { return "Confirm service action" }
        return "\(target.action.capitalized) \(target.displayName)?"
    }

    private func requestServiceAction(name: String, service: ServiceActionResult, action: String) {
        let displayName = service.displayName ?? JarvisFormat.displayName(name)
        let requiresConfirmation = action == "stop" || (action == "restart" && service.critical == true)
        guard requiresConfirmation else {
            Task { await performServiceAction(name, action) }
            return
        }
        pendingServiceAction = PendingServiceAction(
            name: name,
            displayName: displayName,
            action: action,
            message: serviceImpactMessage(name: name, displayName: displayName, action: action)
        )
    }

    private func serviceImpactMessage(name: String, displayName: String, action: String) -> String {
        switch name {
        case "discord-bot":
            return "This will \(action) the Discord bot and interrupt active text or voice responses."
        case "discord-cron-scheduler":
            return "This will \(action) future scheduled-job dispatch. Work already running may continue."
        case "room-audio-server":
            return "This will \(action) \(displayName) and temporarily interrupt room voice access."
        default:
            return "This will \(action) \(displayName) now."
        }
    }

    private func refreshHome() async {
        async let state: Void = app.fetchState()
        async let services: Void = app.fetchServices()
        async let jobs: Void = app.fetchScheduledJobs()
        async let health: Void = app.fetchHealth()
        _ = await (state, services, jobs, health)
    }

    private func performServiceAction(_ name: String, _ action: String) async {
        _ = await app.runServiceAction(name, action)
    }

    // MARK: - Connection/error cards

    private var notConnectedCard: some View {
        Card {
            VStack(spacing: 12) {
                Image(systemName: "antenna.radiowaves.left.and.right.slash")
                    .font(.system(size: 34))
                    .foregroundStyle(.secondary)
                Text(app.connectionState == .failed ? "Offline" : "Not connected").font(.headline)
                if let error = app.errorMessage {
                    Text(error).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
                Button {
                    Task { await app.connect() }
                } label: {
                    Label("Connect", systemImage: "link").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func unavailableCard(title: String, detail: String?) -> some View {
        Card {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.headline)
                    if let detail, !detail.isEmpty {
                        Text(detail).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
                    } else {
                        Text("No current telemetry is available.").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
            } icon: {
                Image(systemName: "questionmark.circle").foregroundStyle(.secondary)
            }
        }
    }

    private func staleCaption(_ text: String) -> some View {
        Text(text).font(.caption).foregroundStyle(.orange).frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Bindings

    private var powerBinding: Binding<Bool> {
        Binding(
            get: { app.lastState?.subsystems?.purifier?.isOn ?? false },
            set: { value in Task { await app.setPurifierPower(value) } }
        )
    }

    private var modeBinding: Binding<String> {
        Binding(
            get: {
                let value = app.lastState?.subsystems?.purifier?.mode ?? "auto"
                return ["auto", "manual", "sleep", "pet"].contains(value) ? value : "auto"
            },
            set: { value in Task { await app.setPurifierMode(value) } }
        )
    }
}

struct PlugCard: View {
    let name: String
    let isOn: Bool?
    let isBusy: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                if isBusy {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "power")
                        .foregroundStyle(isOn == true ? Color.accentColor : .secondary)
                }
                Spacer()
                Circle()
                    .fill(isOn == true ? Color.green : Color.secondary.opacity(0.4))
                    .frame(width: 8, height: 8)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(JarvisFormat.displayName(name))
                    .font(.subheadline.weight(.medium))
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? 2 : 1)
                    .minimumScaleFactor(0.8)
                    .fixedSize(horizontal: false, vertical: true)
                Text(isOn.map { $0 ? "ON" : "OFF" } ?? "UNAVAILABLE")
                    .font(.caption)
                    .foregroundStyle(isOn == true ? Color.accentColor : .secondary)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .contentShape(Rectangle())
    }
}

#Preview {
    HomeView().environmentObject(AppState())
}
