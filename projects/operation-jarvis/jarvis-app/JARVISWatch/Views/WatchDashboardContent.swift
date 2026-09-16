import Foundation
import SwiftUI
import JARVISKit

struct WatchDashboardContent: View {
    @ObservedObject var model: WatchConnectModel
    @ObservedObject var jobs: WatchJobsModel
    let isDashboardCovered: Bool
    let terminalRequestSequence: Int
    let requestedJobRoute: ScheduledJobNavigationRequest?
    let onJobRouteConsumed: (ScheduledJobNavigationRequest) -> Void
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.scenePhase) private var scenePhase
    @State private var selectedPage: WatchDashboardPage = .terminal
    @State private var showsPurifierModeChoices = false
    @State private var showsPurifierFanChoices = false
    private struct PurifierDetailRoute: Identifiable {
        let deviceID: String?
        var id: String { deviceID ?? "legacy" }
    }
    @State private var purifierDetail: PurifierDetailRoute?

    private var overlayOwnsInput: Bool {
        showsPurifierModeChoices || showsPurifierFanChoices || purifierDetail != nil || isDashboardCovered
    }
    private var systemInteractive: Bool { scenePhase == .active && selectedPage == .system }

    private static let iso8601 = Date.ISO8601FormatStyle(includingFractionalSeconds: true)

    private let plugOrder = ["family-room-light", "lamp", "pedalboard", "tv"]
    private let gridColumns = [
        GridItem(.flexible(), spacing: 7),
        GridItem(.flexible(), spacing: 7),
    ]

    var body: some View {
        ZStack {
            WatchJarvisStyle.background
                .ignoresSafeArea()

            selectedPageContent
                .id(selectedPage)
                .transition(.opacity.combined(with: .scale(scale: 0.94)))

            pageIndicator
        }
        // Keep the gradient sized to the full status-bar-free Watch canvas.
        // The shorter Plugs grid must not collapse the page before the bottom edge.
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        // The recognizer belongs to this stable viewport, outside the changing
        // page identity and its scroll/layout coordinate spaces.
        .highPriorityGesture(
            pageDragGesture(page: selectedPage),
            including: overlayOwnsInput ? .none : (selectedPage == .terminal ? .subviews : .all)
        )
        .tint(WatchJarvisStyle.accent)
        .interactionTransition(value: selectedPage, allowed: !overlayOwnsInput, duration: 0.32)
        .onAppear {
            #if DEBUG && targetEnvironment(simulator)
            if CommandLine.arguments.contains("-jarvisOpenWatchSystem") {
                selectedPage = .system
            } else if CommandLine.arguments.contains("-jarvisOpenWatchJobs") {
                selectedPage = .jobs
            }
            #endif
            model.setJobsPageVisible(selectedPage == .jobs)
            updateOMLXPresentation()
        }
        .onChange(of: selectedPage) { _, page in
            model.setJobsPageVisible(page == .jobs)
            updateOMLXPresentation()
            if page == .system {
                Task { await model.refreshCodexQuotaWhenVisible() }
                Task { await model.refreshPurifierReadings() }
            } else {
                model.cancelCodexQuotaViewRefresh()
            }
        }
        .onChange(of: showsPurifierModeChoices) { _, _ in updateOMLXPresentation() }
        .onChange(of: showsPurifierFanChoices) { _, _ in updateOMLXPresentation() }
        .onChange(of: purifierDetail?.id) { _, _ in updateOMLXPresentation() }
        .sheet(item: $purifierDetail) { route in purifierDetailView(route) }
        .onChange(of: isDashboardCovered) { _, _ in updateOMLXPresentation() }
        .onChange(of: terminalRequestSequence) { oldValue, newValue in
            guard newValue != oldValue else { return }
            selectedPage = .terminal
        }
        .task(id: requestedJobRoute?.id) {
            guard let route = requestedJobRoute else { return }
            selectedPage = .jobs
            if await model.resolveScheduledJobRoute(route), !Task.isCancelled {
                onJobRouteConsumed(route)
            }
        }
        .onDisappear {
            model.setJobsPageVisible(false)
            model.setOMLXPresentation(systemVisible: false, covered: true)
        }
    }

    private func updateOMLXPresentation() {
        model.setOMLXPresentation(systemVisible: selectedPage == .system,
            covered: showsPurifierModeChoices || showsPurifierFanChoices || purifierDetail != nil || isDashboardCovered)
    }

    @ViewBuilder
    private var selectedPageContent: some View {
        switch selectedPage {
        case .terminal:
            WatchTerminalView(
                controller: model.terminal,
                isActive: true,
                onAdvancePage: { selectedPage = .plugs }
            )
        case .plugs:
            resolvedPlugsPage
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
        case .system:
            resolvedSystemPage
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
        case .jobs:
            WatchJobsView(
                model: jobs,
                onPreviousPage: { selectedPage = .system },
                resolveRoute: model.resolveScheduledJobRoute,
                onRouteConsumed: onJobRouteConsumed
            )
        }
    }

    private var pageIndicator: some View {
        VStack(spacing: 5) {
            ForEach(WatchDashboardPage.allCases, id: \.self) { page in
                Circle()
                    .fill(pageIndicatorColor(for: page))
                    .frame(width: page == selectedPage ? 6 : 5, height: page == selectedPage ? 6 : 5)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .trailing)
        .padding(.trailing, 1)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func pageIndicatorColor(for page: WatchDashboardPage) -> Color {
        if page == selectedPage { return .white }
        if page == .jobs, jobs.unreadJobCount > 0 { return WatchJarvisStyle.accent }
        return Color.secondary.opacity(0.55)
    }

    private func pageDragGesture(page: WatchDashboardPage) -> some Gesture {
        DragGesture(minimumDistance: 24, coordinateSpace: .global)
            .onEnded { value in
                // An outgoing view must never navigate the newly selected page.
                guard selectedPage == page, !overlayOwnsInput,
                      let destination = page.destination(
                        verticalTranslation: Double(value.translation.height),
                        horizontalTranslation: Double(value.translation.width)
                      ) else { return }
                selectedPage = destination
            }
    }

    @ViewBuilder
    private var resolvedPlugsPage: some View {
        if dynamicTypeSize.isAccessibilitySize {
            accessibilityPlugsPage
        } else {
            plugsPage
        }
    }

    @ViewBuilder
    private var resolvedSystemPage: some View {
        WatchSystemCrownViewport(active: systemInteractive && !overlayOwnsInput) {
            if dynamicTypeSize.isAccessibilitySize {
                accessibilitySystemPage
            } else {
                systemPage
            }
        }
    }

    // MARK: - Plug controls

    private var plugsPage: some View {
        VStack(alignment: .leading, spacing: 7) {
            pageHeader("Plugs", symbol: "powerplug.fill")

            if availablePlugNames.isEmpty {
                unavailablePanel("Plug status unavailable", symbol: "powerplug")
            } else {
                GeometryReader { geometry in
                    let rowCount = max(1, (availablePlugNames.count + gridColumns.count - 1) / gridColumns.count)
                    let rowSpacing = CGFloat(rowCount - 1) * 7
                    let tileHeight = max(72, (geometry.size.height - rowSpacing) / CGFloat(rowCount))

                    LazyVGrid(columns: gridColumns, spacing: 7) {
                        ForEach(availablePlugNames, id: \.self) { name in
                            plugButton(name, minimumHeight: tileHeight)
                        }
                    }
                }
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
    }

    private func plugButton(_ name: String, minimumHeight: CGFloat) -> some View {
        let state = model.lastState?.subsystems?.plugs?.plugs?[name]?.isOn
        let stale = model.isPlugStateStale(name)
        let busy = model.busyPlug == name
        return Button {
            guard let state else { return }
            Task { await model.setPlug(name, isOn: !state) }
        } label: {
            WatchPlugTile(
                name: name,
                isOn: state,
                isBusy: busy,
                isStale: stale,
                minimumHeight: minimumHeight
            )
        }
        .buttonStyle(JarvisPressStyle())
        .disabled(state == nil || stale || model.busyPlug != nil)
        .accessibilityLabel("\(WatchFormat.displayName(name)) plug")
        .accessibilityValue(busy ? "updating" : (stale ? "stale" : (state.map { $0 ? "on" : "off" } ?? "unavailable")))
        .accessibilityHint(stale ? "Wait for automatic refresh before changing this plug" : "Double tap to set the opposite state")
    }

    // MARK: - System

    private var systemPage: some View {
        VStack(spacing: 7) {
            pageHeader("System", symbol: "waveform.path.ecg")
            purifierPanel
            codexQuotaPanel
            omlxCard

            if model.shouldShowRetry {
                retryButton
            }

            if let message = model.errorMessage, !message.isEmpty {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(WatchJarvisStyle.warning)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .accessibilityLabel("JARVIS warning: \(message)")
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
    }

    private var purifierPanel: some View {
        CompactWatchPurifierCard(
            purifier: model.lastState?.subsystems?.purifier,
            unavailable: model.connectionState != .connected || model.isStale,
            busyDeviceID: model.busyPurifierDeviceID,
            accent: WatchJarvisStyle.accent, surface: WatchJarvisStyle.surface
        ) { deviceID in
            model.selectedPurifierID = deviceID
            purifierDetail = PurifierDetailRoute(deviceID: deviceID)
        }
    }

    private func purifierDetailView(_ route: PurifierDetailRoute) -> some View {
        let purifier = model.lastState?.subsystems?.purifier?.selected(route.deviceID)
        let stale = model.isPurifierStateStale(deviceID: route.deviceID)
        let mode = normalizedPurifierMode(purifier?.mode)
        return NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(purifier?.name ?? "Purifier unavailable").font(.headline)
                    Text("PM₂.₅ \(purifier?.pm25.map(String.init) ?? "—") µg/m³")
                        .font(.title3).monospacedDigit()
                    Text("Filter life: \(purifier?.filterLife.map { "\($0)%" } ?? "unavailable")")
                    if purifier?.verificationPending == true {
                        Text(purifierPendingSummary(purifier?.pendingCommand)).foregroundStyle(WatchJarvisStyle.warning)
                    } else if stale {
                        Text("Readings unavailable or stale. Refresh before changing settings.").foregroundStyle(.secondary)
                    }
                    if let error = purifier?.lastError, !error.isEmpty {
                        Text(error).font(.caption).foregroundStyle(WatchJarvisStyle.warning)
                    }
                    Button(purifier?.isOn == true ? "Turn off" : "Turn on", systemImage: "power") {
                        guard let isOn = purifier?.isOn else { return }
                        Task { await model.setPurifierPower(!isOn, deviceID: route.deviceID) }
                    }
                    .disabled(stale || model.purifierBusy || purifier?.isOn == nil)
                    Button("Mode: \(mode.capitalized)", systemImage: "dial.medium") { showsPurifierModeChoices = true }
                        .disabled(stale || model.purifierBusy || purifier?.isOn != true)
                        .confirmationDialog("Purifier mode", isPresented: $showsPurifierModeChoices, titleVisibility: .visible) {
                            ForEach(WatchPurifierCommand.supportedModes, id: \.self) { option in
                                Button(option.capitalized) { Task { await model.setPurifierMode(option, deviceID: route.deviceID) } }
                            }
                        }
                    Button("Fan: \((purifier?.fanSetLevel ?? purifier?.fanLevel).map(String.init) ?? "—")", systemImage: "fan.fill") {
                        showsPurifierFanChoices = true
                    }
                    .disabled(stale || model.purifierBusy || purifier?.isOn != true || mode != "manual")
                    .confirmationDialog("Fan level", isPresented: $showsPurifierFanChoices, titleVisibility: .visible) {
                        ForEach(1...4, id: \.self) { level in
                            Button("Fan \(level)") { Task { await model.setPurifierFan(level, deviceID: route.deviceID) } }
                        }
                    }
                    Button("Refresh readings", systemImage: "arrow.clockwise") {
                        Task { await model.refreshPurifierReadings() }
                    }.disabled(model.purifierBusy)
                    if (purifier?.lastError ?? "").localizedCaseInsensitiveContains("backoff") {
                        Button("Read once despite local cooldown") {
                            Task { await model.refreshPurifierReadings(retry: true) }
                        }.disabled(model.purifierBusy)
                    }
                    if let message = model.errorMessage, !message.isEmpty {
                        Text(message).font(.caption).foregroundStyle(WatchJarvisStyle.warning)
                    }
                }.padding(.horizontal, 8).padding(.bottom, 12)
            }
            .navigationTitle("Purifier")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Done") { purifierDetail = nil } } }
            .onDisappear { showsPurifierModeChoices = false; showsPurifierFanChoices = false }
        }
    }

    @ViewBuilder
    private var codexQuotaPanel: some View {
        if let quota = model.lastState?.subsystems?.codexQuota,
           quota.available == true,
           let remaining = quota.weekly?.remainingPercent {
            let color = codexQuotaColor(remaining)
            let isCritical = CodexQuotaPresentationPolicy.isCritical(remainingPercent: remaining)
            let panelColors = isCritical
                ? [color.opacity(0.16), WatchJarvisStyle.surface]
                : [WatchJarvisStyle.surface, WatchJarvisStyle.surface]
            HStack(spacing: 10) {
                ZStack {
                    Circle()
                        .stroke(color.opacity(0.18), lineWidth: 5)
                    Circle()
                        .trim(from: 0, to: CGFloat(min(max(remaining / 100, 0.015), 1)))
                        .stroke(color, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    VStack(spacing: -1) {
                        Text("\(Int(remaining.rounded()))%")
                            .font(.system(size: 13, weight: .bold, design: .rounded))
                            .monospacedDigit()
                            .foregroundStyle(color)
                        Text("LEFT")
                            .font(.system(size: 6, weight: .bold))
                            .tracking(0.5)
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 4) {
                        Text("WEEKLY")
                            .font(.system(size: 8, weight: .bold))
                            .tracking(0.7)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 2)
                        Text(codexPlanLabel(quota.planType))
                            .font(.system(size: 7, weight: .bold))
                            .foregroundStyle(color)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 2)
                            .background(color.opacity(0.12), in: Capsule())
                    }
                    Text(codexResetLabel(quota.weekly))
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(isCritical ? color : Color.primary)
                        .lineLimit(1)
                    HStack(spacing: 4) {
                        Text(codexFiveHourCompactLabel(quota))
                            .padding(.horizontal, 4)
                            .padding(.vertical, 2)
                            .background(Color.secondary.opacity(0.12), in: Capsule())
                        if let credits = codexCreditsLabel(quota.creditBalance) {
                            Text(credits)
                                .padding(.horizontal, 4)
                                .padding(.vertical, 2)
                                .background(Color.secondary.opacity(0.12), in: Capsule())
                        }
                    }
                    .font(.system(size: 7.5, weight: .bold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, minHeight: 72)
            .background(
                LinearGradient(colors: panelColors, startPoint: .topLeading, endPoint: .bottomTrailing),
                in: RoundedRectangle(cornerRadius: 16, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(color.opacity(0.16), lineWidth: 0.75)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Codex weekly quota, \(Int(remaining.rounded())) percent remaining, \(codexResetLabel(quota.weekly)), \(codexFiveHourLabel(quota))")
        } else {
            HStack(spacing: 9) {
                Image(systemName: "chart.bar.xaxis")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 34, height: 34)
                    .background(Color.secondary.opacity(0.12), in: Circle())
                VStack(alignment: .leading, spacing: 2) {
                    Text("Codex quota")
                        .font(.caption.weight(.semibold))
                    Text(model.lastState?.subsystems?.codexQuota?.refreshing == true ? "Checking usage…" : "Usage unavailable")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                if model.lastState?.subsystems?.codexQuota?.refreshing == true {
                    ProgressView().controlSize(.small)
                }
            }
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, minHeight: 60)
            .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Codex quota unavailable")
        }
    }

    private var retryButton: some View {
        Button {
            Task { await model.connect() }
        } label: {
            Label("Retry now", systemImage: "arrow.clockwise")
                .font(.caption.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 31)
        }
        .buttonStyle(.borderedProminent)
        .buttonBorderShape(.capsule)
        .disabled(model.isRefreshing)
    }

    // MARK: - Accessibility pages

    private var accessibilityPlugsPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                pageHeader("Plugs", symbol: "powerplug.fill")
                if availablePlugNames.isEmpty {
                    unavailablePanel("Plug status unavailable", symbol: "powerplug")
                } else {
                    ForEach(availablePlugNames, id: \.self) { name in
                        accessiblePlugButton(name)
                    }
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
        }
    }

    private var omlxCard: some View {
        WatchOMLXCard(model: model.omlx, active: systemInteractive && !overlayOwnsInput)
    }

    private var accessibilitySystemPage: some View {
        VStack(alignment: .leading, spacing: 10) {
            pageHeader("System", symbol: "waveform.path.ecg")
            purifierPanel
            codexQuotaPanel
            omlxCard
            if model.shouldShowRetry { retryButton }
            if let message = model.errorMessage, !message.isEmpty {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(WatchJarvisStyle.warning)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
    }

    private func accessiblePlugButton(_ name: String) -> some View {
        let state = model.lastState?.subsystems?.plugs?.plugs?[name]?.isOn
        let stale = model.isPlugStateStale(name)
        let busy = model.busyPlug == name
        return Button {
            guard let state else { return }
            Task { await model.setPlug(name, isOn: !state) }
        } label: {
            HStack(spacing: 10) {
                Image(systemName: WatchJarvisStyle.plugSymbol(name))
                    .foregroundStyle(state == true ? WatchJarvisStyle.accent : .secondary)
                    .frame(width: 30, height: 30)
                    .background((state == true ? WatchJarvisStyle.accent : Color.secondary).opacity(0.14), in: Circle())
                VStack(alignment: .leading) {
                    Text(WatchFormat.displayName(name)).font(.headline)
                    Text(busy ? "Updating" : (stale ? "Stale" : (state.map { $0 ? "On" : "Off" } ?? "Unavailable")))
                        .font(.caption)
                        .foregroundStyle(stale ? WatchJarvisStyle.warning : .secondary)
                }
                Spacer()
                if busy { ProgressView().controlSize(.small) }
            }
            .padding(10)
            .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
        }
        .buttonStyle(JarvisPressStyle())
        .disabled(state == nil || stale || model.busyPlug != nil)
    }

    // MARK: - Helpers

    private func pageHeader(_ title: String, symbol: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol)
                .foregroundStyle(WatchJarvisStyle.accent)
            Text(title)
                .font(.headline.weight(.bold))
            Spacer()
        }
    }

    private func unavailablePanel(_ text: String, symbol: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: symbol)
                .font(.title2)
                .foregroundStyle(.secondary)
            Text(text)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 126)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var availablePlugNames: [String] {
        guard model.lastState?.subsystems?.plugs?.ok == true else { return [] }
        let keys = Set(model.lastState?.subsystems?.plugs?.plugs?.keys.map { $0 } ?? [])
        let preferred = plugOrder.filter(keys.contains)
        return preferred + keys.filter { !plugOrder.contains($0) }.sorted()
    }

    private func codexQuotaColor(_ remaining: Double) -> Color {
        CodexQuotaPresentationPolicy.isCritical(remainingPercent: remaining)
            ? WatchJarvisStyle.critical
            : WatchJarvisStyle.accent
    }

    private func codexPlanLabel(_ plan: String?) -> String {
        guard let plan, !plan.isEmpty else { return "CODEX" }
        return plan.replacingOccurrences(of: "_", with: " ").uppercased()
    }

    private func codexResetLabel(_ window: CodexQuotaWindow?) -> String {
        let seconds: Int?
        if let resetAt = window?.resetAt,
           let date = try? Self.iso8601.parse(resetAt) {
            seconds = max(0, Int(date.timeIntervalSinceNow))
        } else {
            seconds = window?.resetAfterSeconds
        }
        guard let seconds else { return "Reset unavailable" }
        if seconds < 60 { return "<1m to reset" }
        if seconds < 3_600 { return "\(seconds / 60)m to reset" }
        if seconds < 86_400 { return "\(seconds / 3_600)h \((seconds % 3_600) / 60)m to reset" }
        return "\(seconds / 86_400)d \((seconds % 86_400) / 3_600)h to reset"
    }

    private func codexFiveHourCompactLabel(_ quota: CodexQuotaSubsystem) -> String {
        if let remaining = quota.fiveHour?.remainingPercent {
            return "5H \(Int(remaining.rounded()))%"
        }
        if quota.fiveHourEnforced == false { return "5H PAUSED" }
        return "5H —"
    }

    private func codexFiveHourLabel(_ quota: CodexQuotaSubsystem) -> String {
        if let remaining = quota.fiveHour?.remainingPercent {
            return "5H \(Int(remaining.rounded()))% left"
        }
        if quota.fiveHourEnforced == false { return "5H paused" }
        return "5H unavailable"
    }

    private func codexCreditsLabel(_ balance: Double?) -> String? {
        guard let balance else { return nil }
        if balance >= 1_000 { return String(format: "%.1fK credits", balance / 1_000) }
        return "\(Int(balance.rounded())) credits"
    }

    private var purifierSummary: String {
        guard let purifier = model.selectedPurifier else { return "Status unavailable" }
        let power = purifier.isOn.map { $0 ? "On" : "Off" } ?? "Unknown"
        if let mode = purifier.mode, !mode.isEmpty { return "\(power) · \(mode.capitalized)" }
        return power
    }

    private func normalizedPurifierMode(_ mode: String?) -> String {
        guard let normalized = mode?.lowercased(),
              WatchPurifierCommand.supportedModes.contains(normalized) else { return "auto" }
        return normalized
    }

    private func purifierPendingSummary(_ command: PurifierPendingCommand?) -> String {
        guard let command else { return "Applying change…" }
        switch command.setting {
        case "mode": return "Switching to \(command.value?.capitalized ?? "mode")…"
        case "power": return "Turning \(command.value ?? "power")…"
        case "speed": return "Setting fan \(command.level.map(String.init) ?? "")…"
        default: return "Applying change…"
        }
    }

    private func airQualityLabel(_ value: Int?) -> String {
        guard let value else { return "Unavailable" }
        switch value {
        case ...12: return "Excellent"
        case ...35: return "Good"
        case ...55: return "Moderate"
        default: return "Poor"
        }
    }

    private func airQualityColor(_ value: Int?) -> Color {
        guard let value else { return .secondary }
        switch value {
        case ...12: return WatchJarvisStyle.accent
        case ...35: return .green
        case ...55: return WatchJarvisStyle.warning
        default: return .red
        }
    }

    private func airQualityProgress(_ value: Int?) -> CGFloat {
        CGFloat(AirQualityGauge.cleanlinessProgress(pm25: value))
    }
}

private struct WatchPlugTile: View {
    let name: String
    let isOn: Bool?
    let isBusy: Bool
    let isStale: Bool
    let minimumHeight: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                ZStack {
                    Circle()
                        .fill(iconColor.opacity(0.16))
                        .interactionTransition(value: isOn, allowed: !isStale && isOn != nil)
                    if isBusy {
                        ProgressView().controlSize(.mini)
                    } else {
                        Image(systemName: WatchJarvisStyle.plugSymbol(name))
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(iconColor)
                            .interactionTransition(value: isOn, allowed: !isStale && isOn != nil)
                    }
                }
                .frame(width: 29, height: 29)
                Spacer(minLength: 2)
                Circle()
                    .fill(statusColor)
                    .frame(width: 7, height: 7)
                    .shadow(color: isOn == true ? WatchJarvisStyle.accent.opacity(0.7) : .clear, radius: 4)
            }

            Text(WatchJarvisStyle.shortPlugName(name))
                .font(.system(size: 10, weight: .semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            Text(stateLabel)
                .font(.system(size: 8, weight: .bold))
                .tracking(0.6)
                .foregroundStyle(isStale ? WatchJarvisStyle.warning : iconColor)
        }
        .padding(8)
        .frame(maxWidth: .infinity, minHeight: minimumHeight, alignment: .leading)
        .background(tileFill, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 15, style: .continuous)
                .stroke(isOn == true ? WatchJarvisStyle.accent.opacity(0.34) : Color.white.opacity(0.08), lineWidth: 0.8)
        }
        .contentShape(RoundedRectangle(cornerRadius: 15, style: .continuous))
    }

    private var iconColor: Color {
        if isStale { return WatchJarvisStyle.warning }
        return isOn == true ? WatchJarvisStyle.accent : .secondary
    }

    private var statusColor: Color {
        if isBusy { return WatchJarvisStyle.warning }
        if isStale { return WatchJarvisStyle.warning }
        return isOn == true ? WatchJarvisStyle.accent : Color.secondary.opacity(0.55)
    }

    private var stateLabel: String {
        if isBusy { return "UPDATING" }
        if isStale { return "STALE" }
        return isOn.map { $0 ? "ON" : "OFF" } ?? "UNKNOWN"
    }

    private var tileFill: some ShapeStyle {
        if isOn == true {
            return AnyShapeStyle(
                LinearGradient(
                    colors: [WatchJarvisStyle.accent.opacity(0.20), WatchJarvisStyle.surface],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
        }
        return AnyShapeStyle(WatchJarvisStyle.surface)
    }
}

enum WatchJarvisStyle {
    static let accent = Color(
        red: JARVISBrandTheme.darkAccent.normalizedRed,
        green: JARVISBrandTheme.darkAccent.normalizedGreen,
        blue: JARVISBrandTheme.darkAccent.normalizedBlue
    )
    static let critical = Color(red: 1.0, green: 0.25, blue: 0.30)
    static let warning = Color(red: 1.0, green: 0.67, blue: 0.24)
    static let surface = Color.white.opacity(0.075)
    static let background = LinearGradient(
        colors: [Color.black, accent.opacity(0.14), Color.black],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static func plugSymbol(_ name: String) -> String {
        switch name {
        case "family-room-light": return "lightbulb.fill"
        case "lamp": return "lamp.table.fill"
        case "pedalboard": return "music.note"
        case "tv": return "tv.fill"
        default: return "powerplug.fill"
        }
    }

    static func shortPlugName(_ name: String) -> String {
        switch name {
        case "family-room-light": return "Room Light"
        case "pedalboard": return "Pedalboard"
        default: return WatchFormat.displayName(name)
        }
    }
}
