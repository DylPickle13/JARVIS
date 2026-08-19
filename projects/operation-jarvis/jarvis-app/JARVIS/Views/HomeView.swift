import SwiftUI
import JARVISKit

// M1 Home screen — the main control surface.
//
// Layout (per the approved plan, HIG-aligned):
//   • status header (connection capsule + active IP)
//   • weather card (inset-grouped)
//   • Pi sessions card
//   • air purifier section (power switch + mode segmented control + fan slider)
//   • plugs (2-column grid of tappable cards; tap = toggle)
//
// Polls the snapshot every 10 s while connected; a toolbar button refreshes
// on demand. Commands go through AppState → jarvisd allowlist.

struct HomeView: View {
    @EnvironmentObject var app: AppState

    // Local fan-slider state (commit only on release, not on every tick).
    @State private var fanLocal: Double = 2
    @State private var isDraggingFan = false

    private let gridColumns = [GridItem(.flexible(), spacing: 12),
                               GridItem(.flexible(), spacing: 12)]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    statusHeader

                    switch app.connectionState {
                    case .connected where app.lastState != nil:
                        if let state = app.lastState {
                            weatherCard(state)
                            piCard(state)
                            purifierSection(state)
                            plugsSection(state)
                        }
                    case .connecting:
                        Card {
                            HStack(spacing: 12) {
                                ProgressView()
                                Text("Connecting to jarvisd…")
                                    .foregroundStyle(.secondary)
                            }
                        }
                    default:
                        notConnectedCard
                    }
                }
                .padding(.horizontal)
                .padding(.bottom, 8)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("JARVIS")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await app.fetchState() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh")
                }
            }
            .task { await pollLoop() }
        }
    }

    // MARK: - Status header

    private var statusHeader: some View {
        HStack {
            ConnectionBadge(state: app.connectionState, detail: statusDetail)
            Spacer()
            if let ip = activeIP {
                Text(ip)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.top, 4)
    }

    private var statusDetail: String {
        switch app.connectionState {
        case .connected: return "Connected · \(networkLabel)"
        case .connecting: return "Connecting…"
        case .failed: return "Offline"
        case .idle: return "Not connected"
        }
    }

    private var networkLabel: String {
        guard let host = app.currentEndpoint?.host else { return "—" }
        if host.hasPrefix("100.") { return "Tailscale" }
        if host.hasPrefix("192.168") || host.hasPrefix("10.") || host.hasPrefix("172.") {
            return "LAN"
        }
        return host
    }

    private var activeIP: String? {
        app.currentEndpoint?.host
    }

    // MARK: - Weather

    @ViewBuilder
    private func weatherCard(_ state: StateSnapshot) -> some View {
        if let w = state.subsystems?.weather {
            let code = w.weatherCode
            Card {
                HStack(spacing: 14) {
                    Image(systemName: JarvisFormat.weatherSymbol(code))
                        .font(.system(size: 34))
                        .foregroundStyle(JarvisFormat.weatherTint(code))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(w.location ?? "Pickering, ON")")
                            .font(.headline)
                        Text(weatherSubline(w))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let temp = w.temperatureC {
                        Text("\(temp, format: .number.precision(.fractionLength(0)))°")
                            .font(.system(size: 42, weight: .light))
                            .monospacedDigit()
                    }
                }
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Weather: \(w.location ?? "local"), \(weatherSubline(w))")
        }
    }

    private func weatherSubline(_ w: WeatherSubsystem) -> String {
        var parts: [String] = []
        if let f = w.feelsLikeC { parts.append("Feels \(Int(f))°") }
        if let h = w.humidityPercent { parts.append("\(h)% humidity") }
        if let wind = w.windKph { parts.append("\(Int(wind)) km/h") }
        return parts.joined(separator: " · ")
    }

    // MARK: - Pi sessions

    private func piCard(_ state: StateSnapshot) -> some View {
        let active = state.subsystems?.pi?.active ?? state.summary?.piActive ?? 0
        return Card {
            HStack(spacing: 14) {
                Image(systemName: "terminal")
                    .font(.title2)
                    .foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Pi sessions")
                        .font(.headline)
                    Text("\(active) active")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Pi sessions: \(active) active")
    }

    // MARK: - Air purifier

    @ViewBuilder
    private func purifierSection(_ state: StateSnapshot) -> some View {
        if let p = state.subsystems?.purifier {
            let isOn = p.isOn ?? false
            let mode = ["auto", "manual", "sleep", "pet"].contains(p.mode ?? "") ? (p.mode ?? "auto") : "auto"
            let fan = p.fanSetLevel ?? p.fanLevel ?? 2
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("Air purifier", systemImage: "wind")
                        .font(.headline)
                    Spacer()
                    Toggle("Power", isOn: powerBinding)
                        .labelsHidden()
                        .accessibilityLabel("Air purifier power")
                }
                .padding(.horizontal, 4)

                Card {
                    VStack(spacing: 14) {
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading, spacing: 0) {
                                Text("\(p.pm25 ?? 0) µg/m³")
                                    .font(.title2.weight(.medium))
                                    .monospacedDigit()
                                Text("PM2.5")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text("\(mode.capitalized) · fan \(fan)")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }

                        Picker("Mode", selection: modeBinding) {
                            Text("Auto").tag("auto")
                            Text("Manual").tag("manual")
                            Text("Sleep").tag("sleep")
                            Text("Pet").tag("pet")
                        }
                        .pickerStyle(.segmented)
                        .disabled(!isOn)
                        .accessibilityLabel("Air purifier mode")

                        HStack(spacing: 10) {
                            Text("Fan")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Slider(
                                value: Binding(
                                    get: { isDraggingFan ? fanLocal : Double(fan) },
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
                            .disabled(!isOn || mode != "manual")
                            Text("\(isDraggingFan ? Int(fanLocal) : fan)")
                                .font(.body.monospacedDigit())
                                .frame(width: 18)
                        }
                    }
                }
            }
            .accessibilityElement(children: .contain)
        }
    }

    // MARK: - Plugs

    private func plugsSection(_ state: StateSnapshot) -> some View {
        let plugs = state.subsystems?.plugs?.plugs ?? [:]
        let items = plugs.keys.sorted().map { (name: $0, isOn: plugs[$0]?.isOn ?? false) }
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Plugs", systemImage: "powerplug")
                    .font(.headline)
                Spacer()
                if let on = state.subsystems?.plugs?.onCount, let total = state.subsystems?.plugs?.count {
                    Text("\(on) / \(total) on")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }
            .padding(.horizontal, 4)

            if items.isEmpty {
                Card {
                    Text("No plugs configured.")
                        .foregroundStyle(.secondary)
                }
            } else {
                LazyVGrid(columns: gridColumns, spacing: 12) {
                    ForEach(items, id: \.name) { item in
                        PlugCard(name: item.name, isOn: item.isOn)
                            .onTapGesture {
                                Task { await app.togglePlug(item.name) }
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("\(JarvisFormat.displayName(item.name)) plug")
                            .accessibilityValue(item.isOn ? "on" : "off")
                            .accessibilityHint("Double tap to toggle")
                    }
                }
            }
        }
    }

    // MARK: - Not connected

    private var notConnectedCard: some View {
        Card {
            VStack(spacing: 12) {
                Image(systemName: "antenna.radiowaves.left.and.right.slash")
                    .font(.system(size: 34))
                    .foregroundStyle(.secondary)
                Text(app.connectionState == .failed ? "Offline" : "Not connected")
                    .font(.headline)
                if let err = app.errorMessage {
                    Text(err)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                Button {
                    Task { await app.connect() }
                } label: {
                    Label("Connect", systemImage: "link")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - Bindings

    private var powerBinding: Binding<Bool> {
        Binding(
            get: { app.lastState?.subsystems?.purifier?.isOn ?? false },
            set: { newValue in
                Task { await app.setPurifierPower(newValue) }
            }
        )
    }

    private var modeBinding: Binding<String> {
        Binding(
            get: {
                let m = app.lastState?.subsystems?.purifier?.mode ?? "auto"
                return ["auto", "manual", "sleep", "pet"].contains(m) ? m : "auto"
            },
            set: { newValue in
                Task { await app.setPurifierMode(newValue) }
            }
        )
    }

    // MARK: - Polling

    private func pollLoop() async {
        while !Task.isCancelled {
            if app.connectionState == .connected {
                await app.fetchState()
            }
            try? await Task.sleep(for: .seconds(10))
        }
    }
}

// MARK: - Plug card

struct PlugCard: View {
    let name: String
    let isOn: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "power")
                    .font(.body)
                    .foregroundStyle(isOn ? Color.accentColor : .secondary)
                Spacer()
                Circle()
                    .fill(isOn ? Color.green : Color.secondary.opacity(0.4))
                    .frame(width: 8, height: 8)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(JarvisFormat.displayName(name))
                    .font(.subheadline.weight(.medium))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Text(isOn ? "ON" : "OFF")
                    .font(.caption)
                    .foregroundStyle(isOn ? Color.accentColor : .secondary)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
        .background(
            Color(.secondarySystemGroupedBackground),
            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
        )
        .contentShape(Rectangle())
    }
}

#Preview {
    HomeView().environmentObject(AppState())
}
