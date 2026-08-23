import Foundation
import SwiftUI
import JARVISKit

struct HomeView: View {
    @EnvironmentObject var app: AppState
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var fanLocal: Double = 2
    @State private var isDraggingFan = false
    @State private var pendingServiceAction: PendingServiceAction?
    @State private var runtimeServicesExpanded = false
    @State private var scheduledJobsExpanded = false

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
                        codexQuotaCard(state)
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

    private var statusHeader: some View {
        Card {
            Group {
                if usesAccessibilityLayout {
                    VStack(alignment: .leading, spacing: 14) {
                        pulseIdentity
                        pulseMetadata
                    }
                } else {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(spacing: 14) {
                            pulseIdentity
                            Spacer(minLength: 8)
                            connectionStatusPill
                        }
                        pulseMetadata
                    }
                }
            }
        }
        .overlay(alignment: .topTrailing) {
            Circle()
                .fill(JarvisPalette.cyan.opacity(0.13))
                .frame(width: 116, height: 116)
                .blur(radius: 32)
                .offset(x: 26, y: -34)
                .allowsHitTesting(false)
        }
        .accessibilityElement(children: .contain)
    }

    private var pulseIdentity: some View {
        HStack(spacing: 13) {
            JARVISMark(size: 50)
            VStack(alignment: .leading, spacing: 3) {
                Text("JARVIS")
                    .font(.headline.weight(.bold))
                    .tracking(1.6)
                Text(pulseTitle)
                    .font(.title3.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
                Text(statusDetail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder
    private var pulseMetadata: some View {
        if usesAccessibilityLayout {
            VStack(alignment: .leading, spacing: 8) {
                connectionStatusPill
                Label(freshnessLabel, systemImage: app.lastState?.stale == true ? "clock.badge.exclamationmark" : "clock")
                    .font(.caption)
                    .foregroundStyle(app.lastState?.stale == true ? JarvisPalette.warning : .secondary)
            }
        } else {
            HStack {
                Label(freshnessLabel, systemImage: app.lastState?.stale == true ? "clock.badge.exclamationmark" : "clock")
                    .font(.caption)
                    .foregroundStyle(app.lastState?.stale == true ? JarvisPalette.warning : .secondary)
                Spacer()
                if app.isStateLoading {
                    ProgressView()
                        .controlSize(.small)
                        .accessibilityLabel("Refreshing JARVIS status")
                } else {
                    Text("BUILD \(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "—")")
                        .font(.caption2.weight(.semibold))
                        .tracking(0.8)
                        .foregroundStyle(.tertiary)
                }
            }
        }
    }

    private var connectionStatusPill: some View {
        StatusPill(text: connectionPillText, color: connectionColor)
    }

    private var pulseTitle: String {
        switch app.connectionState {
        case .connected:
            if app.lastState?.stale == true { return "Telemetry needs attention" }
            if app.operationErrorMessage != nil { return "Action needs attention" }
            return "Systems online"
        case .connecting: return "Establishing link"
        case .failed: return "JARVIS offline"
        case .idle: return "Ready to connect"
        }
    }

    private var statusDetail: String {
        switch app.connectionState {
        case .connected:
            return app.isStateLoading ? "Connected · refreshing" : "Connected via \(networkLabel)"
        case .connecting: return "Searching LAN and Tailscale"
        case .failed: return "Open Settings to review the connection"
        case .idle: return "Connection has not started"
        }
    }

    private var connectionPillText: String {
        switch app.connectionState {
        case .connected: return app.lastState?.stale == true ? "STALE" : networkLabel.uppercased()
        case .connecting: return "LINKING"
        case .failed: return "OFFLINE"
        case .idle: return "IDLE"
        }
    }

    private var connectionColor: Color {
        switch app.connectionState {
        case .connected: return app.lastState?.stale == true ? JarvisPalette.warning : JarvisPalette.cyan
        case .connecting: return JarvisPalette.warning
        case .failed: return .red
        case .idle: return .secondary
        }
    }

    private var freshnessLabel: String {
        if app.lastState?.stale == true { return "Status is stale" }
        return JarvisFormat.freshness(ageSeconds: app.lastState?.ageSeconds)
    }

    private var networkLabel: String {
        guard let host = app.currentEndpoint?.host else { return "—" }
        if host.hasPrefix("100.") || host.hasSuffix(".ts.net") { return "Tailscale" }
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
                Image(systemName: "terminal.fill")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(JarvisPalette.cyan)
                    .frame(width: 42, height: 42)
                    .background(JarvisPalette.cyan.opacity(0.12), in: Circle())
                VStack(alignment: .leading, spacing: 2) {
                    Text("Pi sessions").font(.headline)
                    Text("\(active) active").font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                Text("\(active)")
                    .font(.title2.weight(.bold))
                    .monospacedDigit()
                    .foregroundStyle(JarvisPalette.cyan)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Pi sessions: \(active) active")
        if pi.stale == true {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Pi session data is stale.") })
        }
        return AnyView(content)
    }

    // MARK: - Codex quota

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
        let content = Card {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 10) {
                    Label("Codex usage", systemImage: "chevron.left.forwardslash.chevron.right")
                        .font(.headline)
                        .foregroundStyle(.primary)
                    Spacer()
                    StatusPill(text: codexPlanLabel(quota.planType), color: color, symbol: "sparkles")
                }

                Group {
                    if usesAccessibilityLayout {
                        VStack(alignment: .leading, spacing: 14) {
                            codexQuotaRing(remaining: remaining, color: color)
                            codexQuotaDetails(quota, remaining: remaining, color: color)
                        }
                    } else {
                        HStack(spacing: 18) {
                            codexQuotaRing(remaining: remaining, color: color)
                            codexQuotaDetails(quota, remaining: remaining, color: color)
                        }
                    }
                }
            }
        }
        .overlay(alignment: .topTrailing) {
            Circle()
                .fill(color.opacity(0.10))
                .frame(width: 112, height: 112)
                .blur(radius: 28)
                .offset(x: 22, y: -32)
                .allowsHitTesting(false)
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
            Circle()
                .stroke(color.opacity(0.16), lineWidth: 8)
            Circle()
                .trim(from: 0, to: CGFloat(min(max(remaining / 100, 0.01), 1)))
                .stroke(color, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: 0) {
                Text("\(Int(remaining.rounded()))%")
                    .font(.title2.weight(.bold))
                    .monospacedDigit()
                Text("REMAINING")
                    .font(.system(size: 8, weight: .bold))
                    .tracking(0.7)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(width: 82, height: 82)
    }

    private func codexQuotaDetails(
        _ quota: CodexQuotaSubsystem,
        remaining: Double,
        color: Color
    ) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("Weekly capacity")
                .font(.title3.weight(.semibold))
            ProgressView(value: remaining, total: 100)
                .tint(color)
                .accessibilityHidden(true)
            Label(codexQuotaResetLabel(quota.weekly), systemImage: "calendar.badge.clock")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Label(codexFiveHourLabel(quota), systemImage: "clock")
                if let credits = codexCreditsLabel(quota.creditBalance) {
                    Label(credits, systemImage: "bolt.circle")
                }
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func codexQuotaColor(_ remaining: Double) -> Color {
        JarvisPalette.electricBlue
    }

    private func codexPlanLabel(_ plan: String?) -> String {
        guard let plan, !plan.isEmpty else { return "CODEX" }
        return plan.replacingOccurrences(of: "_", with: " ").uppercased()
    }

    private func codexQuotaResetLabel(_ window: CodexQuotaWindow?) -> String {
        let seconds: Int?
        if let resetAt = window?.resetAt,
           let date = JarvisFormat.parseISO8601(resetAt) {
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
                        HStack(alignment: .center) {
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
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .stroke(purifierQualityColor(purifier.pm25).opacity(0.18), lineWidth: 6)
                Circle()
                    .trim(from: 0, to: purifierQualityProgress(purifier.pm25))
                    .stroke(
                        purifierQualityColor(purifier.pm25),
                        style: StrokeStyle(lineWidth: 6, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))
                Text(purifier.pm25.map(String.init) ?? "—")
                    .font(.headline.weight(.bold))
                    .monospacedDigit()
            }
            .frame(width: 58, height: 58)

            VStack(alignment: .leading, spacing: 2) {
                Text(purifierQualityLabel(purifier.pm25))
                    .font(.headline)
                Text("PM2.5 · µg/m³")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Air quality \(purifierQualityLabel(purifier.pm25)), PM2.5 \(purifier.pm25.map(String.init) ?? "unavailable") micrograms per cubic meter")
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
        case ...12: return JarvisPalette.cyan
        case ...35: return .green
        case ...55: return JarvisPalette.warning
        default: return .red
        }
    }

    private func purifierQualityProgress(_ value: Int?) -> CGFloat {
        guard let value else { return 0 }
        return min(max(CGFloat(value) / 75, 0.04), 1)
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

    private var runtimeServiceSummary: String {
        guard app.servicesLoaded else { return "Loading" }
        guard !sortedServices.isEmpty else { return "No runtimes" }
        let running = sortedServices.filter { $0.service.running == true }.count
        return "\(running) of \(sortedServices.count) running"
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

            DisclosureGroup(isExpanded: $runtimeServicesExpanded) {
                VStack(alignment: .leading, spacing: 8) {
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
                }
                .padding(.top, 8)
            } label: {
                HStack {
                    Label("Runtime services", systemImage: "server.rack")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    if app.servicesErrorMessage != nil {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(JarvisPalette.warning)
                    }
                    Text(runtimeServiceSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }
            .padding(.horizontal, 4)
            .accessibilityHint(runtimeServicesExpanded ? "Double tap to collapse runtime services" : "Double tap to expand runtime services")

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
        VStack(alignment: .leading, spacing: 13) {
            HStack(alignment: .top) {
                ZStack {
                    Circle()
                        .fill(iconColor.opacity(0.13))
                    if isBusy {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: JarvisFormat.plugSymbol(name))
                            .font(.headline.weight(.semibold))
                            .foregroundStyle(iconColor)
                    }
                }
                .frame(width: 42, height: 42)

                Spacer(minLength: 8)

                HStack(spacing: 5) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 7, height: 7)
                        .shadow(color: isOn == true ? JarvisPalette.cyan.opacity(0.65) : .clear, radius: 4)
                    Text(stateLabel)
                        .font(.caption2.weight(.bold))
                        .tracking(0.5)
                }
                .foregroundStyle(statusColor)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(statusColor.opacity(0.10), in: Capsule())
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(JarvisFormat.displayName(name))
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? 2 : 1)
                    .minimumScaleFactor(0.8)
                    .fixedSize(horizontal: false, vertical: true)
                Text(isBusy ? "Applying desired state" : (isOn.map { $0 ? "Power available" : "Power inactive" } ?? "State unavailable"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(15)
        .frame(maxWidth: .infinity, minHeight: 116, alignment: .leading)
        .background(tileFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(isOn == true ? JarvisPalette.cyan.opacity(0.30) : Color.primary.opacity(0.065), lineWidth: 0.8)
        }
        .shadow(color: isOn == true ? JarvisPalette.cyan.opacity(0.10) : Color.black.opacity(0.045), radius: 12, y: 5)
        .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var iconColor: Color {
        isOn == true ? JarvisPalette.cyan : .secondary
    }

    private var statusColor: Color {
        if isBusy { return JarvisPalette.warning }
        if isOn == true { return JarvisPalette.cyan }
        return .secondary
    }

    private var stateLabel: String {
        if isBusy { return "UPDATING" }
        return isOn.map { $0 ? "ON" : "OFF" } ?? "UNKNOWN"
    }

    private var tileFill: AnyShapeStyle {
        if isOn == true {
            return AnyShapeStyle(
                LinearGradient(
                    colors: [JarvisPalette.cyan.opacity(0.13), JarvisPalette.surface],
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
