import Foundation
import SwiftUI
import JARVISKit

enum PiSessionIndicatorTone: Equatable {
    case offline
    case idle
    case running
    case new
    case compacting
    case unknown

    var color: Color {
        switch self {
        case .offline: return .gray
        case .idle: return .purple
        case .running: return .green
        case .new: return .cyan
        case .compacting: return .blue
        case .unknown: return JarvisPalette.warning
        }
    }
}

struct PiSessionIndicatorPresentation: Equatable {
    let label: String
    let tone: PiSessionIndicatorTone
    var symbol: String {
        switch tone {
        case .running: return "waveform"
        case .compacting: return "arrow.down.right.and.arrow.up.left"
        case .idle: return "pause.fill"
        case .new: return "plus"
        case .offline: return "bolt.slash.fill"
        case .unknown: return "questionmark"
        }
    }
    var animatesIcon: Bool { tone == .running || tone == .compacting }
    var allowsActivityEdge: Bool { animatesIcon || tone == .idle }

    init(lifecycle: PiSessionLifecycle) {
        switch lifecycle {
        case .offline:
            label = "Offline"
            tone = .offline
        case .idle:
            label = "Idle"
            tone = .idle
        case .running:
            label = "Running"
            tone = .running
        case .new:
            label = "New"
            tone = .new
        case .compacting:
            label = "Compacting"
            tone = .compacting
        case .unknown:
            label = "Unknown"
            tone = .unknown
        }
    }
}

/// One independent, full-target card; routing remains on the enclosing button.
struct PiSessionCardContent: View {
    let sessionID: Int
    let lifecycle: PiSessionLifecycle
    let motionActive: Bool

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .caption) private var numberSize = 12.0
    @ScaledMetric(relativeTo: .body) private var iconSize = 18.0
    @ScaledMetric(relativeTo: .subheadline) private var statusSize = 14.0

    var body: some View {
        let presentation = PiSessionIndicatorPresentation(lifecycle: lifecycle)
        let color = presentation.tone.color
        MinimalCard(padding: 8, glass: true) {
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("\(sessionID)")
                        .font(.system(size: numberSize, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 4)
                    Image(systemName: presentation.symbol)
                        .font(.system(size: iconSize, weight: .semibold))
                        // Normalize SF Symbol line boxes; glyph choice must not resize a card.
                        .frame(height: iconSize)
                        .foregroundStyle(color)
                        .activityIconPulse(active: motionActive && presentation.animatesIcon)
                        .accessibilityHidden(true)
                }
                Text(presentation.label)
                    .font(.system(size: statusSize, weight: .semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
                    .minimumScaleFactor(dynamicTypeSize.isAccessibilitySize ? 1 : 0.85)
            }
            .frame(maxWidth: .infinity, minHeight: 42, alignment: .leading)
        }
        .activityCardEdge(active: presentation.animatesIcon,
            allowed: motionActive && presentation.allowsActivityEdge, muted: true)
        .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Pi session \(sessionID), \(presentation.label.lowercased())")
    }
}

struct HomeView: View {
    @EnvironmentObject var app: AppState
    let onOpenPiTerminal: (JARVISTerminalSlot) -> Void

    init(onOpenPiTerminal: @escaping (JARVISTerminalSlot) -> Void = { _ in }) {
        self.onOpenPiTerminal = onOpenPiTerminal
    }
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.scenePhase) private var scenePhase
    @State private var fanLocal: Double = 2
    @State private var isDraggingFan = false
    @State private var showsPurifierControls = false
    @State private var selectedPurifierID: String?
    @State private var confirmsPurifierRecovery = false

    private var usesAccessibilityLayout: Bool { dynamicTypeSize.isAccessibilitySize }
    private var gridColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 8), count: usesAccessibilityLayout ? 1 : 2)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    HStack(spacing: 12) {
                        Text("JARVIS").font(.largeTitle.bold()).accessibilityAddTraits(.isHeader)
                        compactConnectionStrip
                    }

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
                            roomAudioCard
                            codexQuotaCard(state)
                            plugsSection(state)
                            purifierSection(state)
                            OMLXStatusCard(client: app.client,
                                endpoint: app.currentEndpoint.map { JarvisEndpoint(baseURL: $0, token: app.store.token ?? "") },
                                active: scenePhase == .active && app.activeSection == .home && !showsPurifierControls)
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
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $showsPurifierControls) {
                NavigationStack {
                    ScrollView {
                        VStack(spacing: 12) {
                            if let state = app.lastState { purifierDetailSection(state) }
                            if let item = selectedPurifier {
                                Text("PM2.5: \(item.pm25.map(String.init) ?? "—") µg/m³")
                                Text("Filter life: \(item.filterLife.map { "\($0)%" } ?? "—")")
                                if item.ok == true, let error = item.lastError {
                                    Text(error).font(.footnote).foregroundStyle(.secondary)
                                }
                            }
                            Button("Refresh readings") { Task { await app.refreshHome() } }
                            if (selectedPurifier?.lastError ?? selectedPurifier?.error ?? "").localizedCaseInsensitiveContains("backoff") {
                                Button("Try reading again") { confirmsPurifierRecovery = true }
                                    .confirmationDialog("Try one read despite the local cooldown?", isPresented: $confirmsPurifierRecovery, titleVisibility: .visible) {
                                        Button("Try one read") { Task { await app.retryPurifierReadings() } }
                                        Button("Cancel", role: .cancel) {}
                                    } message: {
                                        Text("This only checks readings. Another rate limit will restore backoff; purifier settings will not change.")
                                    }
                            }
                        }.padding()
                    }
                    .navigationTitle(selectedPurifier?.name ?? "Air purifier")
                    .toolbar { ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { showsPurifierControls = false }
                    } }
                }
                .presentationDetents([.medium, .large])
            }
            .refreshable { await app.refreshHome(); await app.refreshRoomAudio() }
            .task(id: scenePhase == .active && app.activeSection == .home) {
                guard scenePhase == .active, app.activeSection == .home else { return }
                while !Task.isCancelled {
                    await app.refreshRoomAudio()
                    do { try await Task.sleep(for: .seconds(2)) } catch { return }
                }
            }
        }
    }

    private var homeMotionActive: Bool {
        scenePhase == .active && app.activeSection == .home && !showsPurifierControls
    }

    private var roomAudioCard: some View {
        TimelineView(.animation(minimumInterval: 1, paused: !homeMotionActive)) { context in
            let sessions = app.lastState?.subsystems?.pi?.mobileSessions
            let lifecycle = app.lastState?.subsystems?.pi?.stale == true ? PiSessionLifecycle.unknown
                : sessions?.first(where: { $0.sessionID == 10 })?.resolvedLifecycle ?? .unknown
            let presentation = PiSessionIndicatorPresentation(lifecycle: lifecycle)
            let activeSpeakers = RoomAudioSpeaker.allCases.filter { speaker in
                app.roomAudio[speaker]?.allowsStop == true &&
                    (app.roomAudioUpdatedAt[speaker].map { context.date.timeIntervalSince($0) <= 6 } ?? false)
            }
            let speakerSummary = RoomAudioSpeaker.allCases.map { speaker in
                let fresh = app.roomAudioUpdatedAt[speaker].map { context.date.timeIntervalSince($0) <= 6 } ?? false
                return "\(speaker.title): \(fresh ? app.roomAudio[speaker]?.title ?? "Unavailable" : "Unavailable")"
            }.joined(separator: " · ")
            MinimalCard(padding: 8) {
                HStack(spacing: 8) {
                    Button { onOpenPiTerminal(.roomAudio) } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text("10").font(.system(.caption, design: .monospaced).weight(.semibold)).foregroundStyle(.secondary)
                                Text("Room Audio").font(.subheadline.weight(.semibold))
                                    .lineLimit(1).minimumScaleFactor(0.85)
                                Spacer(minLength: 4)
                                Image(systemName: presentation.symbol).foregroundStyle(presentation.tone.color)
                                    .activityIconPulse(active: homeMotionActive && presentation.animatesIcon)
                            }
                            Text(speakerSummary).font(.caption2).foregroundStyle(.secondary)
                                .lineLimit(1).minimumScaleFactor(0.85)
                        }
                        .frame(maxWidth: .infinity, minHeight: 42, alignment: .leading)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(JarvisPressStyle())
                    .accessibilityLabel("Room Audio, Pi session 10, \(presentation.label), \(speakerSummary)")
                    .accessibilityHint("Opens the shared Room Audio Pi session 10 terminal")
                    Button { Task { await app.stopAllRoomAudio() } } label: {
                        Image(systemName: "stop.fill").font(.caption)
                            .frame(width: 32, height: 32)
                            .background(JarvisPalette.warning.opacity(0.12), in: Circle())
                    }
                    .buttonStyle(JarvisPressStyle())
                    .disabled(activeSpeakers.isEmpty || !app.roomAudioStopping.isEmpty)
                    .accessibilityLabel("Stop current room audio on both speakers")
                }
            }
            .activityCardEdge(active: presentation.animatesIcon,
                allowed: homeMotionActive && presentation.allowsActivityEdge, muted: true)
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


        }
        .padding(.horizontal, 12)
        .frame(minHeight: 42)
        .jarvisGlassSurface(JarvisPalette.surface, in: RoundedRectangle(cornerRadius: 13, style: .continuous), glass: true)
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
            if app.isAwaitingFreshState { return "Online · loading status" }
            return app.lastState?.stale == true ? "Online · partial data" : "Online · \(networkLabel)"
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
        if app.isAwaitingFreshState { return "Loading status" }
        if app.lastState?.stale == true { return "Some data delayed" }
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
        let subsystemStale = subsystem?.stale == true
        let items = plugs.keys.sorted().map { name in
            let plug = plugs[name]
            return (
                name: name,
                isOn: plug?.isOn,
                stale: subsystemStale || plug?.ok != true || plug?.stale == true
            )
        }
        let unavailable = subsystem?.ok != true
        // Overall snapshot state can be partial because Pi, services, or network
        // telemetry is delayed. Only plug-scoped evidence gates plug controls.
        let stale = subsystemStale || items.contains(where: { $0.stale })
        let refreshing = subsystemStale && subsystem?.refreshing == true

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
                                isBusy: app.isOperationBusy("plug:\(item.name)"),
                                isStale: item.stale
                            )
                        }
                        .buttonStyle(JarvisPressStyle())
                        .disabled(
                            item.isOn == nil || item.stale || app.isOperationBusy("plug:\(item.name)")
                        )
                        .accessibilityLabel("\(JarvisFormat.displayName(item.name)) plug")
                        .accessibilityValue(item.isOn.map { $0 ? "on" : "off" } ?? "unavailable")
                        .accessibilityHint(
                            item.isOn == nil
                                ? "State unavailable"
                                : (item.stale
                                    ? (refreshing
                                        ? "State is refreshing; wait before changing it"
                                        : "State is stale; refresh before changing it")
                                    : "Double tap to set the opposite state")
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

    private var selectedPurifier: PurifierSubsystem? {
        app.lastState?.subsystems?.purifier?.selected(selectedPurifierID)
    }

    private var selectedPurifierBusy: Bool {
        app.isOperationBusy(selectedPurifierID.map { "purifier:\($0)" } ?? "purifier")
    }

    private func purifierSection(_ state: StateSnapshot) -> some View {
        CompactPurifierCard(purifier: state.subsystems?.purifier, isBusy: { id in
            app.isOperationBusy(id.map { "purifier:\($0)" } ?? "purifier")
        }) { id in
            selectedPurifierID = id
            isDraggingFan = false
            showsPurifierControls = true
        }
    }

    @ViewBuilder
    private func purifierDetailSection(_ state: StateSnapshot) -> some View {
        if let purifier = selectedPurifier, purifier.ok == true {
            let isOn = purifier.isOn
            let mode = ["auto", "manual", "sleep", "pet"].contains(purifier.mode ?? "")
                ? (purifier.mode ?? "auto")
                : "auto"
            let fan = purifier.fanSetLevel ?? purifier.fanLevel
            let pending = purifier.verificationPending == true
            let busy = selectedPurifierBusy || pending
            // Purifier controls depend only on purifier-scoped freshness.
            let stale = purifier.stale == true
            let refreshing = stale && purifier.refreshing == true

            MinimalCard {
                VStack(spacing: 9) {
                    HStack(spacing: 10) {
                        Label {
                            Text(purifier.name ?? "Air purifier")
                        } icon: {
                            Image(systemName: "wind")
                                .foregroundStyle(isOn == true ? JarvisPalette.accent : .secondary)
                                .interactionTransition(value: isOn, allowed: !stale && !busy && isOn != nil)
                        }
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
                        detail: selectedPurifier?.lastError ?? selectedPurifier?.error ?? "Refresh Home to retrieve this device."
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
            .font(.subheadline)
            .fixedSize(horizontal: true, vertical: false)
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
                let id = selectedPurifierID
                Task { await app.setPurifierFan(level, deviceID: id) }
            }
        }
        .tint(JarvisPalette.accent)
        .disabled(isOn != true || mode != "manual" || stale || busy)
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
        let content = VStack(spacing: 8) {
            piSessionStatusRow(
                sessionIDs: [1, 2, 3],
                sessions: pi.mobileSessions,
                isStale: isStale
            )
            piSessionStatusRow(
                sessionIDs: [4, 5, 6],
                sessions: pi.mobileSessions,
                isStale: isStale
            )
            piSessionStatusRow(
                sessionIDs: [7, 8, 9],
                sessions: pi.mobileSessions,
                isStale: isStale
            )
        }

        if isStale {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Pi session data is stale.") })
        }
        return AnyView(content)
    }

    private func piSessionStatusRow(
        sessionIDs: [Int],
        sessions: [PiMobileSession]?,
        isStale: Bool
    ) -> some View {
        HStack(alignment: .top, spacing: 8) {
            ForEach(sessionIDs, id: \.self) { sessionID in
                Button {
                    guard let slot = JARVISTerminalSlot(rawValue: sessionID) else { return }
                    onOpenPiTerminal(slot)
                } label: {
                    let lifecycle = isStale
                        ? PiSessionLifecycle.unknown
                        : sessions?.first(where: { $0.sessionID == sessionID })?.resolvedLifecycle ?? .unknown
                    piSessionStatusSection(sessionID: sessionID, lifecycle: lifecycle)
                }
                .buttonStyle(JarvisPressStyle())
                .accessibilityHint("Opens Pi \(sessionID)'s terminal on the JARVIS tab")
            }
        }
    }

    private func piSessionStatusSection(sessionID: Int, lifecycle: PiSessionLifecycle) -> some View {
        PiSessionCardContent(sessionID: sessionID, lifecycle: lifecycle,
            motionActive: scenePhase == .active && app.activeSection == .home
                && !showsPurifierControls && !app.isAwaitingFreshState)
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

    // MARK: - Detail helpers

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
            get: { selectedPurifier?.isOn ?? false },
            set: { value in let id = selectedPurifierID; Task { await app.setPurifierPower(value, deviceID: id) } }
        )
    }

    private var modeBinding: Binding<String> {
        Binding(
            get: {
                let value = selectedPurifier?.mode ?? "auto"
                return ["auto", "manual", "sleep", "pet"].contains(value) ? value : "auto"
            },
            set: { value in let id = selectedPurifierID; Task { await app.setPurifierMode(value, deviceID: id) } }
        )
    }
}

struct PlugCard: View {
    let name: String
    let isOn: Bool?
    let isBusy: Bool
    var isStale: Bool = false

    var body: some View {
        HStack(spacing: 8) {
            ZStack {
                Circle().fill(iconColor.opacity(0.12))
                    .interactionTransition(value: isOn, allowed: isOn != nil && !isStale)
                if isBusy {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: JarvisFormat.plugSymbol(name))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(iconColor)
                        .interactionTransition(value: isOn, allowed: isOn != nil && !isStale)
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
        .jarvisGlassSurface(tileFill, in: RoundedRectangle(cornerRadius: 14, style: .continuous),
                            glass: true, tint: isOn == true ? JarvisPalette.accent.opacity(0.12) : nil)
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


struct CompactPurifierCard: View {
    @Environment(\.colorScheme) private var colorScheme
    let purifier: PurifierSubsystem?
    var isBusy: (String?) -> Bool = { _ in false }
    let select: (String?) -> Void

    var body: some View {
        VStack(spacing: 0) {
            if let purifier, !purifier.compactDevices.isEmpty {
                ForEach(Array(purifier.compactDevices.prefix(2)), id: \.id) { item in
                    Button {
                        select(purifier.devices == nil ? nil : item.id)
                    } label: {
                        row(item.state, busy: isBusy(purifier.devices == nil ? nil : item.id))
                    }
                    .buttonStyle(JarvisPressStyle())
                }
            } else {
                Button { select(nil) } label: {
                    Label("Purifier readings unavailable", systemImage: "wind")
                        .font(.caption)
                        .frame(maxWidth: .infinity, minHeight: 44)
                }.buttonStyle(.plain)
            }
        }
        .frame(height: 44)
        .overlay {
            if (purifier?.compactDevices.count ?? 0) > 1 {
                Rectangle().fill(JarvisPalette.accent.opacity(0.12))
                    .frame(height: 0.5).padding(.leading, 28).padding(.trailing, 5)
                    .allowsHitTesting(false)
            }
        }
        .padding(5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(JarvisPalette.surface)
        }
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(JarvisPalette.accent.opacity(0.20), lineWidth: 0.75)
                .allowsHitTesting(false)
        }
    }

    private func row(_ item: PurifierSubsystem, busy: Bool) -> some View {
        let name = item.name ?? "Air purifier"
        let compactName = name.replacingOccurrences(of: " Air Purifier", with: "", options: .caseInsensitive)
        let status = busy ? "Working" : item.verificationPending == true ? "Pending" : item.refreshing == true ? "Loading" :
            item.ok != true ? "Offline" : item.stale == true ? "Stale" :
            item.isOn == false ? "Off" : item.mode?.capitalized ?? "—"
        let fresh = item.ok == true && item.stale != true && item.verificationPending != true && !busy
        let warningColor = colorScheme == .dark
            ? Color(red: 1, green: 0.73, blue: 0.40) : Color(red: 0.55, green: 0.25, blue: 0.04)
        let dangerColor = colorScheme == .dark
            ? Color(red: 1, green: 0.58, blue: 0.60) : Color(red: 0.65, green: 0.10, blue: 0.18)
        let qualityColor: Color = !fresh || item.pm25 == nil ? Color.primary.opacity(0.68) :
            (item.pm25 ?? 0) <= 12 ? JarvisPalette.accent : (item.pm25 ?? 0) <= 35 ? .primary : (item.pm25 ?? 0) <= 55 ? warningColor : dangerColor
        let activeColor: Color = fresh && item.isOn == true ? JarvisPalette.accent : Color.primary.opacity(0.68)
        let filterFraction = min(1, max(0, Double(item.filterLife ?? 0) / 100))
        return HStack(spacing: 5) {
            Image(systemName: "wind")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(activeColor)
                .frame(width: 18, height: 18)
                .background(activeColor.opacity(0.10), in: RoundedRectangle(cornerRadius: 6))
            Text(compactName).font(.system(size: 12, weight: .semibold))
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(status.uppercased())
                .font(.system(size: 8, weight: .semibold))
                .tracking(0.2)
                .foregroundStyle(activeColor)
                .padding(.horizontal, 5).frame(height: 15)
                .background(activeColor.opacity(0.07), in: Capsule())
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text("PM₂.₅").font(.system(size: 8, weight: .medium))
                Text(item.pm25.map(String.init) ?? "—")
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .monospacedDigit()
            }
            .foregroundStyle(qualityColor)
            .padding(.horizontal, 6).frame(height: 18)
            .background(qualityColor.opacity(0.08), in: Capsule())
            HStack(spacing: 3) {
                ZStack {
                    Circle().stroke(JarvisPalette.accent.opacity(0.15), lineWidth: 1.5)
                    Circle().trim(from: 0, to: filterFraction)
                        .stroke(item.filterLife.map { $0 <= 15 } == true ? warningColor : activeColor,
                                style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                }.frame(width: 12, height: 12)
                VStack(spacing: -1) {
                    Text("FILTER").font(.system(size: 7, weight: .medium)).foregroundStyle(Color.primary.opacity(0.65))
                    Text(item.filterLife.map { "\($0)%" } ?? "—")
                        .font(.system(size: 10, weight: .medium)).monospacedDigit()
                        .fixedSize(horizontal: true, vertical: false)
                }.frame(width: 36)
            }
            Image(systemName: "chevron.right")
                .font(.system(size: 7, weight: .semibold)).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 4)
        .lineLimit(1)
        .frame(maxWidth: .infinity, minHeight: 22, maxHeight: 22)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(name), \(status), PM2.5 \(item.pm25.map(String.init) ?? "unavailable") micrograms per cubic meter, filter \(item.filterLife.map { "\($0) percent" } ?? "unavailable")")
        .accessibilityHint("Opens this purifier's controls and full-size readings")
    }
}
