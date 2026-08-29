import Foundation
import SwiftUI
import JARVISKit

private enum WatchDashboardPage: Hashable, CaseIterable {
    case terminal
    case plugs
    case system
}

struct WatchDashboardContent: View {
    @ObservedObject var model: WatchConnectModel
    let siriTerminalRequestSequence: Int
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var selectedPage: WatchDashboardPage = .terminal
    @State private var showsPurifierModeChoices = false
    @State private var showsPurifierFanChoices = false

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
                .transition(.opacity)

            pageIndicator
        }
        .tint(WatchJarvisStyle.accent)
        .animation(.easeInOut(duration: 0.16), value: selectedPage)
        .onAppear {
            #if DEBUG && targetEnvironment(simulator)
            if CommandLine.arguments.contains("-jarvisOpenWatchSystem") {
                selectedPage = .system
            }
            #endif
        }
        .onChange(of: selectedPage) { _, page in
            if page == .system {
                Task { await model.refreshCodexQuotaWhenVisible() }
            } else {
                model.cancelCodexQuotaViewRefresh()
            }
        }
        .onChange(of: siriTerminalRequestSequence) { oldValue, newValue in
            guard newValue != oldValue else { return }
            selectedPage = .terminal
        }
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
                .gesture(pageDragGesture(previous: .terminal, next: .system))
        case .system:
            resolvedSystemPage
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
                .gesture(pageDragGesture(previous: .plugs, next: nil))
        }
    }

    private var pageIndicator: some View {
        VStack(spacing: 5) {
            ForEach(WatchDashboardPage.allCases, id: \.self) { page in
                Circle()
                    .fill(page == selectedPage ? Color.white : Color.secondary.opacity(0.55))
                    .frame(width: page == selectedPage ? 6 : 5, height: page == selectedPage ? 6 : 5)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .trailing)
        .padding(.trailing, 1)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func pageDragGesture(
        previous: WatchDashboardPage?,
        next: WatchDashboardPage?
    ) -> some Gesture {
        DragGesture(minimumDistance: 24)
            .onEnded { value in
                guard abs(value.translation.height) > abs(value.translation.width),
                      abs(value.translation.height) >= 52 else { return }
                if value.translation.height < 0, let next {
                    selectedPage = next
                } else if value.translation.height > 0, let previous {
                    selectedPage = previous
                }
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
        if dynamicTypeSize.isAccessibilitySize {
            accessibilitySystemPage
        } else {
            systemPage
        }
    }

    // MARK: - Plug controls

    private var plugsPage: some View {
        VStack(alignment: .leading, spacing: 7) {
            pageHeader("Plugs", symbol: "powerplug.fill", trailing: plugSummary)

            if availablePlugNames.isEmpty {
                unavailablePanel("Plug status unavailable", symbol: "powerplug")
            } else {
                LazyVGrid(columns: gridColumns, spacing: 7) {
                    ForEach(availablePlugNames, id: \.self) { name in
                        plugButton(name)
                    }
                }
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
    }

    private func plugButton(_ name: String) -> some View {
        let state = model.lastState?.subsystems?.plugs?.plugs?[name]?.isOn
        let stale = model.isPlugStateStale(name)
        let busy = model.busyPlug == name
        return Button {
            guard let state else { return }
            Task { await model.setPlug(name, isOn: !state) }
        } label: {
            WatchPlugTile(name: name, isOn: state, isBusy: busy, isStale: stale)
        }
        .buttonStyle(.plain)
        .disabled(state == nil || stale || model.busyPlug != nil)
        .accessibilityLabel("\(WatchFormat.displayName(name)) plug")
        .accessibilityValue(busy ? "updating" : (stale ? "stale" : (state.map { $0 ? "on" : "off" } ?? "unavailable")))
        .accessibilityHint(stale ? "Wait for automatic refresh before changing this plug" : "Double tap to set the opposite state")
    }

    // MARK: - System

    private var systemPage: some View {
        VStack(spacing: 7) {
            pageHeader("System", symbol: "waveform.path.ecg", trailing: codexQuotaHeader)
            purifierPanel
            codexQuotaPanel

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
        let purifier = model.lastState?.subsystems?.purifier
        let pm25 = purifier?.pm25
        let isOn = purifier?.isOn
        let mode = normalizedPurifierMode(purifier?.mode)
        let fan = purifier?.fanSetLevel ?? purifier?.fanLevel
        let stale = model.isPurifierStateStale
        let pending = model.isPurifierVerificationPending

        return HStack(spacing: 8) {
            ZStack {
                Circle()
                    .stroke(airQualityColor(pm25).opacity(0.22), lineWidth: 5)
                Circle()
                    .trim(from: 0, to: airQualityProgress(pm25))
                    .stroke(
                        airQualityColor(pm25),
                        style: StrokeStyle(lineWidth: 5, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))
                Text(pm25.map(String.init) ?? "—")
                    .font(.caption.weight(.bold))
                    .monospacedDigit()
            }
            .frame(width: 46, height: 46)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Air quality \(airQualityLabel(pm25)), PM2.5 \(pm25.map(String.init) ?? "unavailable")")

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 4) {
                    Text("AIR PURIFIER")
                        .font(.system(size: 8, weight: .bold))
                        .tracking(0.7)
                        .foregroundStyle(stale || pending ? WatchJarvisStyle.warning : .secondary)
                    Spacer(minLength: 2)
                    purifierPowerButton(isOn: isOn, stale: stale)
                }

                Text(pending ? purifierPendingSummary(purifier?.pendingCommand) : "\(airQualityLabel(pm25)) · \(purifierSummary)")
                    .font(.system(size: 9.5, weight: .semibold))
                    .foregroundStyle(pending ? WatchJarvisStyle.warning : Color.primary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)

                HStack(spacing: 5) {
                    purifierModeControl(isOn: isOn, mode: mode, stale: stale)
                    purifierFanControl(isOn: isOn, mode: mode, fan: fan, stale: stale)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 9)
        .frame(maxWidth: .infinity, minHeight: 68)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityElement(children: .contain)
    }

    private func purifierPowerButton(isOn: Bool?, stale: Bool) -> some View {
        Button {
            guard let isOn else { return }
            Task { await model.setPurifierPower(!isOn) }
        } label: {
            ZStack {
                Circle()
                    .fill((isOn == true ? WatchJarvisStyle.accent : Color.secondary).opacity(0.16))
                if model.purifierBusy || model.isPurifierVerificationPending {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: "power")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(isOn == true ? WatchJarvisStyle.accent : .secondary)
                }
            }
            .frame(width: 27, height: 27)
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(isOn == nil || stale || model.purifierBusy)
        .accessibilityLabel("Air purifier power")
        .accessibilityValue(
            model.isPurifierVerificationPending
                ? "waiting for confirmation"
                : (model.purifierBusy ? "updating" : (isOn.map { $0 ? "on" : "off" } ?? "unavailable"))
        )
        .accessibilityHint(
            model.isPurifierVerificationPending
                ? "Wait for the previous change to be confirmed"
                : (stale ? "Wait for automatic refresh before changing the air purifier" : "Double tap to set the opposite state")
        )
    }

    private func purifierModeControl(isOn: Bool?, mode: String, stale: Bool) -> some View {
        Button {
            showsPurifierModeChoices = true
        } label: {
            HStack(spacing: 2) {
                Image(systemName: "dial.medium")
                Text(mode.uppercased())
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.system(size: 6, weight: .bold))
            }
            .font(.system(size: 7.5, weight: .bold))
            .foregroundStyle(isOn == true ? WatchJarvisStyle.accent : .secondary)
            .padding(.horizontal, 5)
            .frame(height: 21)
            .background(Color.white.opacity(0.07), in: Capsule())
        }
        .buttonStyle(.plain)
        .disabled(isOn != true || stale || model.purifierBusy)
        .confirmationDialog(
            "Air purifier mode",
            isPresented: $showsPurifierModeChoices,
            titleVisibility: .visible
        ) {
            ForEach(WatchPurifierCommand.supportedModes, id: \.self) { option in
                Button(option == mode ? "✓ \(option.capitalized)" : option.capitalized) {
                    Task { await model.setPurifierMode(option) }
                }
            }
            Button("Cancel", role: .cancel) {}
        }
        .accessibilityLabel("Air purifier mode")
        .accessibilityValue(mode.capitalized)
        .accessibilityHint(
            model.isPurifierVerificationPending
                ? "Wait for the previous change to be confirmed"
                : "Double tap to choose Auto, Manual, Sleep, or Pet mode"
        )
    }

    private func purifierFanControl(isOn: Bool?, mode: String, fan: Int?, stale: Bool) -> some View {
        Button {
            showsPurifierFanChoices = true
        } label: {
            HStack(spacing: 2) {
                Image(systemName: "fan.fill")
                Text(fan.map(String.init) ?? "—")
                    .monospacedDigit()
                Image(systemName: "chevron.down")
                    .font(.system(size: 6, weight: .bold))
            }
            .font(.system(size: 7.5, weight: .bold))
            .foregroundStyle(mode == "manual" && isOn == true ? WatchJarvisStyle.accent : .secondary)
            .padding(.horizontal, 5)
            .frame(height: 21)
            .background(Color.white.opacity(0.07), in: Capsule())
        }
        .buttonStyle(.plain)
        .disabled(isOn != true || mode != "manual" || stale || model.purifierBusy)
        .confirmationDialog(
            "Air purifier fan",
            isPresented: $showsPurifierFanChoices,
            titleVisibility: .visible
        ) {
            ForEach(1...4, id: \.self) { level in
                Button(level == fan ? "✓ Fan \(level)" : "Fan \(level)") {
                    Task { await model.setPurifierFan(level) }
                }
            }
            Button("Cancel", role: .cancel) {}
        }
        .accessibilityLabel("Air purifier fan level")
        .accessibilityValue(fan.map(String.init) ?? "unavailable")
        .accessibilityHint(
            model.isPurifierVerificationPending
                ? "Wait for the previous change to be confirmed"
                : (mode == "manual" ? "Double tap to choose a fan level" : "Set the air purifier to manual mode to change fan level")
        )
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
                pageHeader("Plugs", symbol: "powerplug.fill", trailing: plugSummary)
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

    private var accessibilitySystemPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                pageHeader("System", symbol: "waveform.path.ecg", trailing: codexQuotaHeader)
                purifierPanel
                codexQuotaPanel
                if model.shouldShowRetry {
                    retryButton
                }
                if let message = model.errorMessage, !message.isEmpty {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(WatchJarvisStyle.warning)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
        }
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
        .buttonStyle(.plain)
        .disabled(state == nil || stale || model.busyPlug != nil)
    }

    // MARK: - Helpers

    private func pageHeader(_ title: String, symbol: String, trailing: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol)
                .foregroundStyle(WatchJarvisStyle.accent)
            Text(title)
                .font(.headline.weight(.bold))
            Spacer()
            Text(trailing)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.secondary)
                .lineLimit(1)
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

    private var plugSummary: String {
        guard let summary = model.lastState?.summary,
              let on = summary.plugsOn, let total = summary.plugsTotal else { return "—" }
        return "\(on)/\(total) on"
    }

    private var codexQuotaHeader: String {
        guard let quota = model.lastState?.subsystems?.codexQuota,
              quota.available == true,
              let remaining = quota.weekly?.remainingPercent else { return "Codex —" }
        return "\(Int(remaining.rounded()))% left"
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
           let date = ISO8601DateFormatter().date(from: resetAt) {
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
        guard let purifier = model.lastState?.subsystems?.purifier else { return "Status unavailable" }
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

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                ZStack {
                    Circle()
                        .fill(iconColor.opacity(0.16))
                    if isBusy {
                        ProgressView().controlSize(.mini)
                    } else {
                        Image(systemName: WatchJarvisStyle.plugSymbol(name))
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(iconColor)
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
        .frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
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
