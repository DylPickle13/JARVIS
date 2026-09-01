import Foundation
import SwiftUI
import JARVISKit

enum PiSessionIndicatorTone: Equatable {
    case running
    case idle
    case unknown

    var color: Color {
        switch self {
        case .running: return .green
        case .idle: return .purple
        case .unknown: return JarvisPalette.warning
        }
    }
}

struct PiSessionIndicatorPresentation: Equatable {
    let label: String
    let tone: PiSessionIndicatorTone

    init(active: Bool?) {
        switch active {
        case true:
            label = "Running"
            tone = .running
        case false:
            label = "Idle"
            tone = .idle
        case nil:
            label = "Unknown"
            tone = .unknown
        }
    }
}

enum RuntimeServiceDisplayState: Equatable {
    case running
    case scheduled
    case stopped
    case unloaded
    case unconfigured
    case unknown

    var label: String {
        switch self {
        case .running: return "Running"
        case .scheduled: return "Scheduled"
        case .stopped: return "Stopped"
        case .unloaded: return "Unloaded"
        case .unconfigured: return "Unconfigured"
        case .unknown: return "Unknown"
        }
    }

    var isAvailable: Bool {
        self == .running || self == .scheduled
    }

    var color: Color {
        switch self {
        case .running: return .green
        case .scheduled: return JarvisPalette.accent
        case .unconfigured, .unknown: return JarvisPalette.warning
        case .stopped, .unloaded: return .secondary
        }
    }
}

enum RuntimeServicePresentation {
    private static let periodicServiceNames: Set<String> = ["jobs-scheduler"]

    static func state(name: String, service: ServiceActionResult) -> RuntimeServiceDisplayState {
        guard service.ok else { return .unknown }
        let isLoaded = service.loaded == true
        if service.configured == false && !isLoaded { return .unconfigured }
        if service.running == true { return .running }
        if periodicServiceNames.contains(name), isLoaded { return .scheduled }
        return isLoaded ? .stopped : .unloaded
    }

    static func summary(
        servicesLoaded: Bool,
        services: [(name: String, service: ServiceActionResult)]
    ) -> String {
        guard servicesLoaded else { return "Loading" }
        guard !services.isEmpty else { return "No services" }
        let available = services.filter { state(name: $0.name, service: $0.service).isAvailable }.count
        return "\(available) of \(services.count) available"
    }
}

struct HomeView: View {
    @EnvironmentObject var app: AppState
    let onOpenJobs: () -> Void
    let onOpenPiTerminal: (JARVISTerminalSlot) -> Void

    init(
        onOpenJobs: @escaping () -> Void = {},
        onOpenPiTerminal: @escaping (JARVISTerminalSlot) -> Void = { _ in }
    ) {
        self.onOpenJobs = onOpenJobs
        self.onOpenPiTerminal = onOpenPiTerminal
    }
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var fanLocal: Double = 2
    @State private var isDraggingFan = false
    @State private var pendingServiceAction: PendingServiceAction?

    private struct PendingServiceAction {
        let name: String
        let displayName: String
        let action: String
        let message: String
    }

    private var usesAccessibilityLayout: Bool { dynamicTypeSize.isAccessibilitySize }
    private var gridColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 8), count: usesAccessibilityLayout ? 1 : 2)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    compactConnectionStrip

                    if let operationError = app.operationErrorMessage {
                        OperationErrorCard(message: operationError)
                    }

                    if app.connectionState == .connecting || (app.connectionState == .connected && app.lastState == nil) {
                        loadingCard
                    } else if app.connectionState == .connected, let state = app.lastState {
                        if state.loading == true && state.subsystems == nil {
                            loadingCard
                        } else {
                            piCard(state)
                            codexQuotaCard(state)
                            plugsSection(state)
                            purifierSection(state)
                            systemSection
                        }
                    } else {
                        compactOfflineCard
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 6)
            }
            .scrollIndicators(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle("JARVIS")
            .refreshable { await app.refreshHome() }
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

    // MARK: - Compact overview

    private var compactConnectionStrip: some View {
        HStack(spacing: 9) {
            Circle()
                .fill(connectionColor)
                .frame(width: 9, height: 9)
                .shadow(color: connectionColor.opacity(0.45), radius: 3)

            Text(connectionHeadline)
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)

            Spacer(minLength: 8)

            if app.isAwaitingFreshState || app.connectionState == .connecting {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel("Refreshing JARVIS status")
            }

            Text(freshnessLabel)
                .font(.caption)
                .foregroundStyle(
                    app.isAwaitingFreshState || app.lastState?.stale == true
                        ? JarvisPalette.warning
                        : .secondary
                )
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .padding(.horizontal, 12)
        .frame(minHeight: 42)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 13, style: .continuous)
                .stroke(connectionColor.opacity(0.14), lineWidth: 0.75)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(connectionHeadline), \(freshnessLabel)")
    }

    private var connectionHeadline: String {
        switch app.connectionState {
        case .connected:
            if purifierConfirmationIsPrimaryStatus { return "Online · confirming purifier" }
            if app.isAwaitingFreshState { return "Online · refreshing" }
            return app.lastState?.stale == true ? "Connected · stale" : "Online · \(networkLabel)"
        case .connecting: return "Connecting"
        case .failed: return "Offline"
        case .idle: return "Ready to connect"
        }
    }

    private var connectionColor: Color {
        switch app.connectionState {
        case .connected:
            return app.isAwaitingFreshState || app.lastState?.stale == true
                ? JarvisPalette.warning
                : JarvisPalette.accent
        case .connecting: return JarvisPalette.warning
        case .failed: return .red
        case .idle: return .secondary
        }
    }

    private var freshnessLabel: String {
        if purifierConfirmationIsPrimaryStatus { return "Applying change" }
        if app.isAwaitingFreshState { return "Updating status" }
        if app.lastState?.stale == true { return "Needs refresh" }
        if app.connectionState == .connected, app.lastState != nil, app.lastState?.ageSeconds == nil {
            return "Status current"
        }
        return JarvisFormat.freshness(ageSeconds: app.lastState?.ageSeconds)
    }

    private var networkLabel: String {
        guard let host = app.currentEndpoint?.host else { return "—" }
        if host.hasPrefix("100.") || host.hasSuffix(".ts.net") { return "Tailscale" }
        if host.hasPrefix("192.168") || host.hasPrefix("10.") || host.hasPrefix("172.") { return "LAN" }
        return host
    }

    private var purifierConfirmationIsPrimaryStatus: Bool {
        guard app.lastState?.subsystems?.purifier?.verificationPending == true,
              let metadata = app.lastState?.subsystemsMeta else { return false }
        return !metadata.contains { name, value in
            name != "purifier" && name != "codexQuota" && value.stale == true
        }
    }

    private var loadingCard: some View {
        MinimalCard {
            HStack(spacing: 10) {
                ProgressView()
                Text("Loading JARVIS status…")
                    .font(.subheadline.weight(.medium))
                Spacer()
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var compactOfflineCard: some View {
        MinimalCard {
            HStack(spacing: 12) {
                Image(systemName: "antenna.radiowaves.left.and.right.slash")
                    .foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(app.connectionState == .failed ? "JARVIS is offline" : "JARVIS is not connected")
                        .font(.subheadline.weight(.semibold))
                    if let error = app.errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                Spacer(minLength: 8)
                Button("Connect") { Task { await app.connect() } }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
            }
        }
    }

    // MARK: - Plugs

    private func plugsSection(_ state: StateSnapshot) -> some View {
        let subsystem = state.subsystems?.plugs
        let plugs = subsystem?.plugs ?? [:]
        let items = plugs.keys.sorted().map { (name: $0, isOn: plugs[$0]?.isOn) }
        let unavailable = subsystem?.ok != true
        // A routine foreground state read keeps presenting the last confirmed
        // control state. Only jarvisd's authoritative stale/refreshing flags
        // disable hardware writes and show refresh messaging.
        let stale = state.stale == true || subsystem?.stale == true
        let refreshing = stale && (state.refreshing == true || subsystem?.refreshing == true)

        return VStack(alignment: .leading, spacing: 7) {
            MinimalSectionHeader(
                title: "Plugs",
                systemImage: "powerplug",
                detail: unavailable ? "Unavailable" : plugCountLabel(subsystem)
            )

            if unavailable || items.isEmpty {
                MinimalCard {
                    compactUnavailableRow(
                        title: unavailable ? "Plug status unavailable" : "No plugs configured",
                        detail: subsystem?.lastError ?? subsystem?.error
                    )
                }
            } else {
                LazyVGrid(columns: gridColumns, spacing: 8) {
                    ForEach(items, id: \.name) { item in
                        Button {
                            guard let isOn = item.isOn else { return }
                            Task { await app.setPlug(item.name, isOn: !isOn) }
                        } label: {
                            PlugCard(
                                name: item.name,
                                isOn: item.isOn,
                                isBusy: app.isOperationBusy("plug:\(item.name)")
                            )
                        }
                        .buttonStyle(.plain)
                        .disabled(
                            item.isOn == nil || stale || app.isOperationBusy("plug:\(item.name)")
                        )
                        .accessibilityLabel("\(JarvisFormat.displayName(item.name)) plug")
                        .accessibilityValue(item.isOn.map { $0 ? "on" : "off" } ?? "unavailable")
                        .accessibilityHint(
                            item.isOn == nil
                                ? "State unavailable"
                                : (refreshing
                                    ? "State is refreshing; wait before changing it"
                                    : (stale ? "State is stale; refresh before changing it" : "Double tap to set the opposite state"))
                        )
                    }
                }
            }

            if refreshing {
                staleCaption("Refreshing plug data…")
            } else if stale {
                staleCaption("Plug data is stale.")
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func plugCountLabel(_ subsystem: PlugsSubsystem?) -> String {
        guard let on = subsystem?.onCount, let total = subsystem?.count else { return "—" }
        return "\(on) of \(total) on"
    }

    // MARK: - Purifier

    @ViewBuilder
    private func purifierSection(_ state: StateSnapshot) -> some View {
        if let purifier = state.subsystems?.purifier, purifier.ok == true {
            let isOn = purifier.isOn
            let mode = ["auto", "manual", "sleep", "pet"].contains(purifier.mode ?? "")
                ? (purifier.mode ?? "auto")
                : "auto"
            let fan = purifier.fanSetLevel ?? purifier.fanLevel
            let pending = purifier.verificationPending == true
            let busy = app.isOperationBusy("purifier") || pending
            let stale = state.stale == true || purifier.stale == true
            let refreshing = stale && (state.refreshing == true || purifier.refreshing == true)

            MinimalCard {
                VStack(spacing: 9) {
                    HStack(spacing: 10) {
                        Label("Air purifier", systemImage: "wind")
                            .font(.subheadline.weight(.semibold))
                        Spacer(minLength: 6)
                        purifierReading(purifier)
                        if busy {
                            ProgressView().controlSize(.small)
                        }
                        Toggle("Power", isOn: powerBinding)
                            .labelsHidden()
                            .tint(JarvisPalette.accent)
                            .accessibilityLabel("Air purifier power")
                            .disabled(isOn == nil || stale || busy)
                    }

                    Divider()

                    if usesAccessibilityLayout {
                        VStack(alignment: .leading, spacing: 8) {
                            purifierModePicker(isOn: isOn, stale: stale, busy: busy)
                            purifierFanControl(isOn: isOn, mode: mode, stale: stale, busy: busy, fan: fan)
                        }
                    } else {
                        HStack(spacing: 10) {
                            purifierModePicker(isOn: isOn, stale: stale, busy: busy)
                            Spacer(minLength: 4)
                            purifierFanControl(isOn: isOn, mode: mode, stale: stale, busy: busy, fan: fan)
                        }
                    }
                }
            }

            if pending {
                purifierConfirmationCaption(purifier.pendingCommand)
            } else if refreshing {
                staleCaption("Refreshing air-purifier data…")
            } else if stale {
                staleCaption("Air-purifier data is stale.")
            }
        } else {
            VStack(alignment: .leading, spacing: 7) {
                MinimalSectionHeader(title: "Air purifier", systemImage: "wind")
                MinimalCard {
                    compactUnavailableRow(
                        title: "Air purifier unavailable",
                        detail: state.subsystems?.purifier?.lastError ?? state.subsystems?.purifier?.error
                    )
                }
            }
        }
    }

    private func purifierModePicker(isOn: Bool?, stale: Bool, busy: Bool) -> some View {
        HStack(spacing: 4) {
            Text("Mode")
                .font(.caption)
                .foregroundStyle(.secondary)
            Picker("Mode", selection: modeBinding) {
                Text("Auto").tag("auto")
                Text("Manual").tag("manual")
                Text("Sleep").tag("sleep")
                Text("Pet").tag("pet")
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .tint(JarvisPalette.accent)
            .disabled(isOn != true || stale || busy)
            .accessibilityLabel("Air purifier mode")
        }
    }

    @ViewBuilder
    private func purifierFanControl(
        isOn: Bool?,
        mode: String,
        stale: Bool,
        busy: Bool,
        fan: Int?
    ) -> some View {
        if mode == "manual" {
            HStack(spacing: 7) {
                Text("Fan")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                purifierFanSlider(isOn: isOn, mode: mode, stale: stale, busy: busy, fan: fan)
                    .frame(minWidth: 72, maxWidth: 120)
                Text(isDraggingFan ? "\(Int(fanLocal))" : (fan.map(String.init) ?? "—"))
                    .font(.caption.monospacedDigit())
                    .frame(width: 14)
            }
        } else {
            Text("Fan \(fan.map(String.init) ?? "—")")
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospacedDigit()
        }
    }

    private func purifierReading(_ purifier: PurifierSubsystem) -> some View {
        HStack(spacing: 7) {
            ZStack {
                Circle()
                    .stroke(purifierQualityColor(purifier.pm25).opacity(0.16), lineWidth: 4)
                Circle()
                    .trim(from: 0, to: purifierQualityProgress(purifier.pm25))
                    .stroke(
                        purifierQualityColor(purifier.pm25),
                        style: StrokeStyle(lineWidth: 4, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))
                Text(purifier.pm25.map(String.init) ?? "—")
                    .font(.caption.weight(.bold))
                    .monospacedDigit()
            }
            .frame(width: 34, height: 34)

            Text(purifierQualityLabel(purifier.pm25))
                .font(.caption.weight(.medium))
                .foregroundStyle(purifierQualityColor(purifier.pm25))
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "Air quality \(purifierQualityLabel(purifier.pm25)), PM2.5 \(purifier.pm25.map(String.init) ?? "unavailable") micrograms per cubic meter"
        )
    }

    private func purifierQualityLabel(_ value: Int?) -> String {
        guard let value else { return "Unavailable" }
        switch value {
        case ...12: return "Excellent"
        case ...35: return "Good"
        case ...55: return "Moderate"
        default: return "Poor"
        }
    }

    private func purifierQualityColor(_ value: Int?) -> Color {
        guard let value else { return .secondary }
        switch value {
        case ...12: return JarvisPalette.accent
        case ...35: return .green
        case ...55: return JarvisPalette.warning
        default: return .red
        }
    }

    private func purifierQualityProgress(_ value: Int?) -> CGFloat {
        CGFloat(AirQualityGauge.cleanlinessProgress(pm25: value))
    }

    private func purifierConfirmationCaption(_ command: PurifierPendingCommand?) -> some View {
        Label(purifierConfirmationText(command), systemImage: "clock.arrow.circlepath")
            .font(.caption.weight(.medium))
            .foregroundStyle(JarvisPalette.warning)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityLabel(purifierConfirmationText(command))
    }

    private func purifierConfirmationText(_ command: PurifierPendingCommand?) -> String {
        guard let command else { return "Applying air-purifier change… Waiting for confirmation." }
        switch command.setting {
        case "mode":
            return "Switching to \(command.value?.capitalized ?? "the selected mode")… Waiting for confirmation."
        case "power":
            return "Turning air purifier \(command.value ?? "on or off")… Waiting for confirmation."
        case "speed":
            return "Setting fan to \(command.level.map(String.init) ?? "the selected level")… Waiting for confirmation."
        default:
            return "Applying air-purifier change… Waiting for confirmation."
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
        .tint(JarvisPalette.accent)
        .disabled(isOn != true || mode != "manual" || stale || busy)
    }

    // MARK: - System summary

    private var systemSection: some View {
        MinimalCard {
            VStack(spacing: 0) {
                MinimalSectionHeader(title: "System", systemImage: "server.rack")
                    .padding(.bottom, 5)

                Divider()

                NavigationLink {
                    servicesDetail
                } label: {
                    systemSummaryRow(
                        title: "Services",
                        systemImage: "gearshape.2",
                        value: runtimeServiceSummary,
                        color: app.servicesErrorMessage == nil ? .secondary : JarvisPalette.warning,
                        showsChevron: true
                    )
                }
                .buttonStyle(.plain)

                compactDivider

                Button(action: onOpenJobs) {
                    systemSummaryRow(
                        title: "Scheduled jobs",
                        systemImage: "calendar.badge.clock",
                        value: scheduledJobsSummary,
                        color: app.scheduledJobsErrorMessage == nil ? .secondary : JarvisPalette.warning,
                        showsChevron: true
                    )
                }
                .buttonStyle(.plain)
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func systemSummaryRow(
        title: String,
        systemImage: String,
        value: String,
        color: Color,
        showsChevron: Bool = false
    ) -> some View {
        HStack(spacing: 9) {
            Image(systemName: systemImage)
                .font(.caption.weight(.semibold))
                .foregroundStyle(color == .secondary ? JarvisPalette.accent : color)
                .frame(width: 20)
            Text(title)
                .font(.subheadline)
                .foregroundStyle(.primary)
            Spacer(minLength: 8)
            Text(value)
                .font(.caption.weight(.medium))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .monospacedDigit()
            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
        }
        .frame(minHeight: 35)
        .contentShape(Rectangle())
    }

    private var compactDivider: some View {
        Divider().padding(.leading, 29)
    }

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

    private var runtimeServiceSummary: String {
        RuntimeServicePresentation.summary(
            servicesLoaded: app.servicesLoaded,
            services: sortedServices
        )
    }

    private var scheduledJobsSummary: String {
        guard app.scheduledJobsLoaded else { return "Loading" }
        guard let summary = app.scheduledJobsSummary else { return "No jobs" }
        return "\(summary.enabled) of \(summary.total) enabled"
    }

    // MARK: - Pi and Codex overview cards

    private func piCard(_ state: StateSnapshot) -> AnyView {
        guard let pi = state.subsystems?.pi, pi.ok == true else {
            return AnyView(
                MinimalCard {
                    compactUnavailableRow(title: "Pi sessions unavailable", detail: state.subsystems?.pi?.error)
                }
            )
        }

        let isStale = pi.stale == true
        let content = MinimalCard {
            HStack(spacing: 0) {
                ForEach(1...3, id: \.self) { sessionID in
                    if sessionID > 1 {
                        Divider()
                            .frame(height: 42)
                    }
                    Button {
                        guard let slot = JARVISTerminalSlot(rawValue: sessionID) else { return }
                        onOpenPiTerminal(slot)
                    } label: {
                        piSessionStatusSection(
                            sessionID: sessionID,
                            active: isStale
                                ? nil
                                : pi.mobileSessions?.first(where: { $0.sessionID == sessionID })?.active
                        )
                    }
                    .buttonStyle(.plain)
                    .accessibilityHint("Opens Pi \(sessionID)'s terminal on the JARVIS tab")
                }
            }
        }

        if isStale {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Pi session data is stale.") })
        }
        return AnyView(content)
    }

    private func piSessionStatusSection(sessionID: Int, active: Bool?) -> some View {
        let presentation = PiSessionIndicatorPresentation(active: active)
        let status = presentation.label
        let color = presentation.tone.color

        return VStack(spacing: 5) {
            HStack(spacing: 5) {
                Image(systemName: "terminal.fill")
                    .font(.caption2.weight(.bold))
                Text("Pi \(sessionID)")
                    .font(.caption.weight(.semibold))
            }
            .foregroundStyle(color)

            HStack(spacing: 4) {
                Circle()
                    .fill(color)
                    .frame(width: 6, height: 6)
                Text(status)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 42)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Pi session \(sessionID), \(status.lowercased())")
    }

    private func codexQuotaCard(_ state: StateSnapshot) -> AnyView {
        guard let quota = state.subsystems?.codexQuota,
              quota.available == true,
              let remaining = quota.weekly?.remainingPercent else {
            return AnyView(
                unavailableCard(
                    title: "Codex quota unavailable",
                    detail: state.subsystems?.codexQuota?.lastError ?? state.subsystems?.codexQuota?.error
                )
            )
        }
        let color = codexQuotaColor(remaining)
        let content = MinimalCard {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Label("Codex usage", systemImage: "chevron.left.forwardslash.chevron.right")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    StatusPill(text: codexPlanLabel(quota.planType), color: color, symbol: "sparkles")
                        .controlSize(.small)
                }

                Group {
                    if usesAccessibilityLayout {
                        VStack(alignment: .leading, spacing: 8) {
                            codexQuotaRing(remaining: remaining, color: color)
                            codexQuotaDetails(quota, remaining: remaining, color: color)
                        }
                    } else {
                        HStack(spacing: 12) {
                            codexQuotaRing(remaining: remaining, color: color)
                            codexQuotaDetails(quota, remaining: remaining, color: color)
                        }
                    }
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "Codex weekly quota, \(Int(remaining.rounded())) percent remaining, " +
            "\(codexQuotaResetLabel(quota.weekly)), \(codexFiveHourLabel(quota))"
        )
        if quota.stale == true {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Codex quota data is stale.") })
        }
        return AnyView(content)
    }

    private func codexQuotaRing(remaining: Double, color: Color) -> some View {
        ZStack {
            Circle().stroke(color.opacity(0.16), lineWidth: 8)
            Circle()
                .trim(from: 0, to: CGFloat(min(max(remaining / 100, 0.01), 1)))
                .stroke(color, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: 0) {
                Text("\(Int(remaining.rounded()))%")
                    .font(.headline.weight(.bold))
                    .monospacedDigit()
                    .foregroundStyle(color)
                Text("REMAINING")
                    .font(.system(size: 6, weight: .bold))
                    .tracking(0.45)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(width: 58, height: 58)
    }

    private func codexQuotaDetails(
        _ quota: CodexQuotaSubsystem,
        remaining: Double,
        color: Color
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Weekly capacity")
                .font(.subheadline.weight(.semibold))
            ProgressView(value: remaining, total: 100)
                .tint(color)
                .accessibilityHidden(true)
            Label(codexQuotaResetLabel(quota.weekly), systemImage: "calendar.badge.clock")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(spacing: 8) {
                Label(codexFiveHourLabel(quota), systemImage: "clock")
                if let credits = codexCreditsLabel(quota.creditBalance) {
                    Label(credits, systemImage: "bolt.circle")
                }
            }
            .font(.caption2.weight(.medium))
            .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func codexQuotaColor(_ remaining: Double) -> Color {
        CodexQuotaPresentationPolicy.isCritical(remainingPercent: remaining)
            ? JarvisPalette.critical
            : JarvisPalette.accent
    }

    private func codexPlanLabel(_ plan: String?) -> String {
        guard let plan, !plan.isEmpty else { return "CODEX" }
        return plan.replacingOccurrences(of: "_", with: " ").uppercased()
    }

    private func codexQuotaResetLabel(_ window: CodexQuotaWindow?) -> String {
        let seconds: Int?
        if let resetAt = window?.resetAt, let date = JarvisFormat.parseISO8601(resetAt) {
            seconds = max(0, Int(date.timeIntervalSinceNow))
        } else {
            seconds = window?.resetAfterSeconds
        }
        guard let seconds else { return "Reset time unavailable" }
        if seconds < 60 { return "Resets in less than a minute" }
        if seconds < 3_600 { return "Resets in \(seconds / 60)m" }
        if seconds < 86_400 { return "Resets in \(seconds / 3_600)h \((seconds % 3_600) / 60)m" }
        return "Resets in \(seconds / 86_400)d \((seconds % 86_400) / 3_600)h"
    }

    private func codexFiveHourLabel(_ quota: CodexQuotaSubsystem) -> String {
        if let remaining = quota.fiveHour?.remainingPercent {
            return "5-hour \(Int(remaining.rounded()))% left"
        }
        if quota.fiveHourEnforced == false { return "5-hour paused" }
        return "5-hour unavailable"
    }

    private func codexCreditsLabel(_ balance: Double?) -> String? {
        guard let balance else { return nil }
        if balance >= 1_000 { return String(format: "%.1fK credits", balance / 1_000) }
        return "\(Int(balance.rounded())) credits"
    }

    // MARK: - Service detail

    private var servicesDetail: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
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
                daemonCard
            }
            .padding(16)
        }
        .background(JarvisBackdrop())
        .navigationTitle("Services")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await app.refreshHome() }
    }

    private func serviceCard(name: String, service: ServiceActionResult) -> some View {
        let presentation = RuntimeServicePresentation.state(name: name, service: service)
        let isKnown = service.ok
        let isRunning = presentation == .running
        let isScheduled = presentation == .scheduled
        let isUnconfigured = presentation == .unconfigured
        let busy = app.isOperationBusy("service:\(name)")
        let allowed = Set(service.allowedActions ?? [])
        let displayName = service.displayName ?? JarvisFormat.displayName(name)
        let status = presentation.label
        let color = presentation.color

        return Card {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline, spacing: 9) {
                    Circle().fill(color).frame(width: 9, height: 9)
                    Text(displayName).font(.headline)
                    Spacer(minLength: 8)
                    Text(status).font(.subheadline).foregroundStyle(color)
                }
                if let description = service.description, !description.isEmpty {
                    Text(description).font(.subheadline).foregroundStyle(.secondary)
                }
                if isRunning, let pid = service.pid {
                    Text("PID \(pid)").font(.caption).foregroundStyle(.tertiary)
                } else if isScheduled {
                    Text("Loaded; wakes periodically and exits between checks.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                } else if isUnconfigured {
                    Text("LaunchAgent configuration is unavailable.").font(.caption).foregroundStyle(JarvisPalette.warning)
                } else if !isKnown, let error = service.error {
                    Text(error).font(.caption).foregroundStyle(JarvisPalette.warning)
                }

                if allowed.isEmpty {
                    Label("Read-only status", systemImage: "eye")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    HStack(spacing: 10) {
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
                    ProgressView("Applying action…").font(.caption)
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    private var daemonCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 7) {
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

    // MARK: - Detail helpers and actions

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
        case "jobs-scheduler":
            return "This will \(action) future scheduled-job dispatch. Work already running may continue."
        case "room-audio-server":
            return "This will \(action) \(displayName) and temporarily interrupt room voice access."
        default:
            return "This will \(action) \(displayName) now."
        }
    }

    private func performServiceAction(_ name: String, _ action: String) async {
        _ = await app.runServiceAction(name, action)
    }

    @ViewBuilder
    private func unavailableCard(title: String, detail: String?) -> some View {
        Card {
            compactUnavailableRow(title: title, detail: detail)
        }
    }

    private func compactUnavailableRow(title: String, detail: String?) -> some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold))
                if let detail, !detail.isEmpty {
                    Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
            }
        } icon: {
            Image(systemName: "questionmark.circle").foregroundStyle(.secondary)
        }
    }

    private func staleCaption(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(JarvisPalette.warning)
            .frame(maxWidth: .infinity, alignment: .leading)
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

    var body: some View {
        HStack(spacing: 8) {
            ZStack {
                Circle().fill(iconColor.opacity(0.12))
                if isBusy {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: JarvisFormat.plugSymbol(name))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(iconColor)
                }
            }
            .frame(width: 30, height: 30)

            Text(JarvisFormat.displayName(name))
                .font(.caption.weight(.semibold))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .minimumScaleFactor(0.72)

            Spacer(minLength: 4)

            Text(stateLabel)
                .font(.caption2.weight(.bold))
                .foregroundStyle(statusColor)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .frame(maxWidth: .infinity, minHeight: 54, maxHeight: 54)
        .background(tileFill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(isOn == true ? JarvisPalette.accent.opacity(0.28) : Color.primary.opacity(0.055), lineWidth: 0.75)
        }
        .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var iconColor: Color {
        isOn == true ? JarvisPalette.accent : .secondary
    }

    private var statusColor: Color {
        if isBusy { return JarvisPalette.warning }
        if isOn == true { return JarvisPalette.accent }
        return .secondary
    }

    private var stateLabel: String {
        if isBusy { return "…" }
        return isOn.map { $0 ? "ON" : "OFF" } ?? "—"
    }

    private var tileFill: AnyShapeStyle {
        if isOn == true {
            return AnyShapeStyle(
                LinearGradient(
                    colors: [JarvisPalette.accent.opacity(0.11), JarvisPalette.surface],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
        }
        return AnyShapeStyle(JarvisPalette.surface)
    }
}

#Preview {
    HomeView().environmentObject(AppState())
}
