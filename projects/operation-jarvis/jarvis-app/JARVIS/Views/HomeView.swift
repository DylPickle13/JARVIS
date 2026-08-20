import SwiftUI
import JARVISKit

struct HomeView: View {
    @EnvironmentObject var app: AppState
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var fanLocal: Double = 2
    @State private var isDraggingFan = false

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
                        weatherCard(state)
                        piCard(state)
                        purifierSection(state)
                        plugsSection(state)
                    } else {
                        notConnectedCard
                    }
                }
                .padding(.horizontal)
                .padding(.bottom, 8)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("JARVIS")
            .refreshable { await app.fetchState() }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await app.fetchState() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh home status")
                    .disabled(app.isStateLoading || app.connectionState != .connected)
                }
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

    // MARK: - Weather

    @ViewBuilder
    private func weatherCard(_ state: StateSnapshot) -> some View {
        if let weather = state.subsystems?.weather, weather.ok == true {
            let code = weather.weatherCode
            Card {
                if usesAccessibilityLayout {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: JarvisFormat.weatherSymbol(code))
                                .font(.system(size: 34))
                                .foregroundStyle(JarvisFormat.weatherTint(code))
                            VStack(alignment: .leading, spacing: 4) {
                                Text(weather.location ?? "Pickering, ON").font(.headline)
                                Text(weatherSubline(weather))
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        if let temp = weather.temperatureC {
                            Text("\(temp, format: .number.precision(.fractionLength(0)))°")
                                .font(.title.weight(.light))
                                .monospacedDigit()
                        }
                    }
                } else {
                    HStack(spacing: 14) {
                        Image(systemName: JarvisFormat.weatherSymbol(code))
                            .font(.system(size: 34))
                            .foregroundStyle(JarvisFormat.weatherTint(code))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(weather.location ?? "Pickering, ON").font(.headline)
                            Text(weatherSubline(weather))
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if let temp = weather.temperatureC {
                            Text("\(temp, format: .number.precision(.fractionLength(0)))°")
                                .font(.system(size: 42, weight: .light))
                                .monospacedDigit()
                        }
                    }
                }
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Weather: \(weather.location ?? "local"), \(weatherSubline(weather))")
            if weather.stale == true {
                staleCaption("Weather data is stale.")
            }
        } else {
            unavailableCard(title: "Weather unavailable", detail: state.subsystems?.weather?.lastError ?? state.subsystems?.weather?.error)
        }
    }

    private func weatherSubline(_ weather: WeatherSubsystem) -> String {
        var parts: [String] = []
        if let feels = weather.feelsLikeC { parts.append("Feels \(Int(feels))°") }
        if let humidity = weather.humidityPercent { parts.append("\(humidity)% humidity") }
        if let wind = weather.windKph { parts.append("\(Int(wind)) km/h") }
        return parts.isEmpty ? "Current conditions" : parts.joined(separator: " · ")
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
