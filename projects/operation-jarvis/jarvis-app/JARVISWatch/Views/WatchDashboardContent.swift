import SwiftUI
import JARVISKit

struct WatchDashboardContent: View {
    @ObservedObject var model: WatchConnectModel
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private let plugOrder = ["family-room-light", "lamp", "pedalboard", "tv"]
    private let gridColumns = [
        GridItem(.flexible(), spacing: 7),
        GridItem(.flexible(), spacing: 7),
    ]

    var body: some View {
        ZStack {
            WatchJarvisStyle.background
                .ignoresSafeArea()

            if dynamicTypeSize.isAccessibilitySize {
                accessibilityLayout
            } else {
                TabView {
                    overviewPage
                    plugsPage
                    systemPage
                    jarvisPage
                }
                .tabViewStyle(.verticalPage)
            }
        }
        .tint(WatchJarvisStyle.cyan)
    }

    // MARK: - Overview

    private var overviewPage: some View {
        VStack(spacing: 8) {
            brandHeader
            overviewHero
            HStack(spacing: 7) {
                metricTile(
                    value: model.lastState?.summary?.pm25.map(String.init) ?? "—",
                    label: "PM2.5",
                    symbol: "aqi.medium"
                )
                metricTile(
                    value: model.lastState?.summary?.piActive.map(String.init) ?? "—",
                    label: "Pi active",
                    symbol: "cpu"
                )
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
    }

    private var brandHeader: some View {
        HStack(spacing: 8) {
            JARVISWatchMark(size: 38)
            VStack(alignment: .leading, spacing: 0) {
                Text("JARVIS")
                    .font(.headline.weight(.bold))
                    .tracking(1.2)
                Text("CONTROL")
                    .font(.system(size: 8, weight: .semibold))
                    .tracking(0.8)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 2)
            connectionPill
        }
    }

    private var overviewHero: some View {
        VStack(spacing: 3) {
            if model.connectionState == .connecting, model.lastState == nil {
                ProgressView()
                    .controlSize(.small)
                Text("Establishing link")
                    .font(.caption.weight(.semibold))
            } else {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text(model.lastState?.summary?.plugsOn.map(String.init) ?? "—")
                        .font(.system(size: 32, weight: .bold, design: .rounded))
                        .monospacedDigit()
                    Text("of \(model.lastState?.summary?.plugsTotal.map(String.init) ?? "—")")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                Text("PLUGS ACTIVE")
                    .font(.system(size: 9, weight: .bold))
                    .tracking(1.1)
                    .foregroundStyle(WatchJarvisStyle.cyan)
            }
            Text(freshnessText)
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(model.isStale ? WatchJarvisStyle.warning : .secondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, minHeight: 72)
        .background(WatchJarvisStyle.heroFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(WatchJarvisStyle.cyan.opacity(0.24), lineWidth: 1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(overviewAccessibilityLabel)
    }

    private func metricTile(value: String, label: String, symbol: String) -> some View {
        HStack(spacing: 7) {
            Image(systemName: symbol)
                .font(.caption.weight(.semibold))
                .foregroundStyle(WatchJarvisStyle.cyan)
                .frame(width: 22, height: 22)
                .background(WatchJarvisStyle.cyan.opacity(0.13), in: Circle())
            VStack(alignment: .leading, spacing: 0) {
                Text(value)
                    .font(.caption.weight(.bold))
                    .monospacedDigit()
                Text(label)
                    .font(.system(size: 8))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 8)
        .frame(maxWidth: .infinity, minHeight: 42)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label), \(value)")
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
            pageHeader("System", symbol: "waveform.path.ecg", trailing: sourceLabel)
            purifierPanel
            sourcePanel

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
        return HStack(spacing: 10) {
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
            .frame(width: 48, height: 48)

            VStack(alignment: .leading, spacing: 2) {
                Text("AIR QUALITY")
                    .font(.system(size: 8, weight: .bold))
                    .tracking(0.8)
                    .foregroundStyle(.secondary)
                Text(airQualityLabel(pm25))
                    .font(.headline.weight(.semibold))
                Text(purifierSummary)
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .frame(maxWidth: .infinity, minHeight: 66)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Air quality \(airQualityLabel(pm25)), PM2.5 \(pm25.map(String.init) ?? "unavailable"), \(purifierSummary)")
    }

    private var sourcePanel: some View {
        HStack(spacing: 9) {
            Image(systemName: model.isViaPhone ? "iphone.radiowaves.left.and.right" : "antenna.radiowaves.left.and.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(model.dotColor)
                .frame(width: 28, height: 28)
                .background(model.dotColor.opacity(0.14), in: Circle())
            VStack(alignment: .leading, spacing: 1) {
                Text(sourceLabel)
                    .font(.caption.weight(.semibold))
                Text(freshnessText)
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            if model.pendingRelay || model.isRefreshing {
                ProgressView().controlSize(.small)
            }
        }
        .padding(.horizontal, 10)
        .frame(maxWidth: .infinity, minHeight: 48)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
        .accessibilityElement(children: .combine)
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

    // MARK: - JARVIS terminal

    private var jarvisPage: some View {
        VStack(spacing: 9) {
            pageHeader("JARVIS", symbol: "terminal.fill", trailing: model.terminal.status.label)
            NavigationLink {
                WatchTerminalView(controller: model.terminal)
            } label: {
                VStack(spacing: 8) {
                    ZStack {
                        Circle()
                            .fill(WatchJarvisStyle.cyan.opacity(0.15))
                            .frame(width: 58, height: 58)
                        Image(systemName: "terminal.fill")
                            .font(.title2.weight(.semibold))
                            .foregroundStyle(WatchJarvisStyle.cyan)
                    }
                    Text("Open JARVIS")
                        .font(.headline.weight(.bold))
                    Text("Same persistent Pi session")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 142)
                .background(WatchJarvisStyle.heroFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(WatchJarvisStyle.cyan.opacity(0.26), lineWidth: 1)
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Open the JARVIS terminal")
            .accessibilityValue(model.terminal.status.label)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
    }

    // MARK: - Accessibility layout

    private var accessibilityLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                brandHeader
                overviewHero
                pageHeader("Plugs", symbol: "powerplug.fill", trailing: plugSummary)
                ForEach(availablePlugNames, id: \.self) { name in
                    accessiblePlugButton(name)
                }
                pageHeader("System", symbol: "waveform.path.ecg", trailing: sourceLabel)
                purifierPanel
                sourcePanel
                NavigationLink {
                    WatchTerminalView(controller: model.terminal)
                } label: {
                    Label("Open JARVIS terminal", systemImage: "terminal.fill")
                        .frame(maxWidth: .infinity, minHeight: 38)
                }
                if model.shouldShowRetry {
                    retryButton
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
                    .foregroundStyle(state == true ? WatchJarvisStyle.cyan : .secondary)
                    .frame(width: 30, height: 30)
                    .background((state == true ? WatchJarvisStyle.cyan : Color.secondary).opacity(0.14), in: Circle())
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

    private var connectionPill: some View {
        HStack(spacing: 4) {
            Circle().fill(model.dotColor).frame(width: 6, height: 6)
            Text(shortConnectionLabel)
                .font(.system(size: 8, weight: .bold))
                .lineLimit(1)
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 5)
        .background(model.dotColor.opacity(0.13), in: Capsule())
        .overlay { Capsule().stroke(model.dotColor.opacity(0.28), lineWidth: 0.5) }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Connection \(model.statusText)")
    }

    private func pageHeader(_ title: String, symbol: String, trailing: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol)
                .foregroundStyle(WatchJarvisStyle.cyan)
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

    private var shortConnectionLabel: String {
        switch model.connectionState {
        case .connected: return model.isStale ? "STALE" : (model.isViaPhone ? "PHONE" : "DIRECT")
        case .connecting: return "LINKING"
        case .failed: return "OFFLINE"
        case .idle: return "IDLE"
        }
    }

    private var sourceLabel: String {
        switch model.connectionState {
        case .connected:
            if model.pendingRelay { return "Waiting for iPhone" }
            return model.isViaPhone ? "Via iPhone" : "Direct to Mac"
        case .connecting: return "Connecting"
        case .failed: return "Offline"
        case .idle: return "Not connected"
        }
    }

    private var freshnessText: String {
        if model.isStale { return "Status is stale" }
        guard let date = model.cachedAt else { return model.lastState == nil ? "Waiting for status" : "Current status" }
        let seconds = max(0, Int(Date().timeIntervalSince(date)))
        if seconds < 5 { return "Updated now" }
        if seconds < 60 { return "Updated \(seconds)s ago" }
        if seconds < 3_600 { return "Updated \(seconds / 60)m ago" }
        return "Updated \(seconds / 3_600)h ago"
    }

    private var overviewAccessibilityLabel: String {
        let on = model.lastState?.summary?.plugsOn.map(String.init) ?? "unknown"
        let total = model.lastState?.summary?.plugsTotal.map(String.init) ?? "unknown"
        return "\(on) of \(total) plugs active. \(freshnessText)."
    }

    private var purifierSummary: String {
        guard let purifier = model.lastState?.subsystems?.purifier else { return "Status unavailable" }
        let power = purifier.isOn.map { $0 ? "On" : "Off" } ?? "Unknown"
        if let mode = purifier.mode, !mode.isEmpty { return "\(power) · \(mode.capitalized)" }
        return power
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
        case ...12: return WatchJarvisStyle.cyan
        case ...35: return .green
        case ...55: return WatchJarvisStyle.warning
        default: return .red
        }
    }

    private func airQualityProgress(_ value: Int?) -> CGFloat {
        guard let value else { return 0 }
        return min(max(CGFloat(value) / 75, 0.04), 1)
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
                    .shadow(color: isOn == true ? WatchJarvisStyle.cyan.opacity(0.7) : .clear, radius: 4)
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
                .stroke(isOn == true ? WatchJarvisStyle.cyan.opacity(0.34) : Color.white.opacity(0.08), lineWidth: 0.8)
        }
        .contentShape(RoundedRectangle(cornerRadius: 15, style: .continuous))
    }

    private var iconColor: Color {
        if isStale { return WatchJarvisStyle.warning }
        return isOn == true ? WatchJarvisStyle.cyan : .secondary
    }

    private var statusColor: Color {
        if isBusy { return WatchJarvisStyle.warning }
        if isStale { return WatchJarvisStyle.warning }
        return isOn == true ? WatchJarvisStyle.cyan : Color.secondary.opacity(0.55)
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
                    colors: [WatchJarvisStyle.cyan.opacity(0.20), WatchJarvisStyle.surface],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
        }
        return AnyShapeStyle(WatchJarvisStyle.surface)
    }
}

private struct JARVISWatchMark: View {
    let size: CGFloat

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    RadialGradient(
                        colors: [WatchJarvisStyle.cyan.opacity(0.34), WatchJarvisStyle.cyan.opacity(0.04)],
                        center: .center,
                        startRadius: 1,
                        endRadius: size / 2
                    )
                )
                .blur(radius: 2)
            Image("JARVISMark")
                .resizable()
                .scaledToFit()
                .padding(3)
                .clipShape(Circle())
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

enum WatchJarvisStyle {
    static let cyan = Color(red: 0.29, green: 0.82, blue: 1.0)
    static let warning = Color(red: 1.0, green: 0.67, blue: 0.24)
    static let surface = Color.white.opacity(0.075)
    static let heroFill = LinearGradient(
        colors: [cyan.opacity(0.18), Color.white.opacity(0.055)],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    static let background = LinearGradient(
        colors: [Color.black, Color(red: 0.01, green: 0.08, blue: 0.12), Color.black],
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
