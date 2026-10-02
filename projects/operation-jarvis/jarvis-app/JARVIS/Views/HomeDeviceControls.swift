import SwiftUI
import JARVISKit

/// Device controls belong to Home, independently of the JARVIS/AI dashboard.
struct HomeDeviceControls: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let onDetailVisibilityChanged: (Bool) -> Void
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
        VStack(spacing: 10) {
            if let message = app.operationErrorMessage {
                OperationErrorCard(message: message)
            }
            if let state = app.lastState {
                plugsSection(state)
                    .disabled(app.connectionState != .connected)
                purifierSection(state)
            } else {
                MinimalCard {
                    Text(app.connectionState == .connecting ? "Loading home devices…" : "Home device readings unavailable")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            }
            if app.connectionState == .failed || app.connectionState == .idle {
                Button("Connect") { Task { await app.connect() } }
                    .buttonStyle(.borderedProminent)
            }
        }
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
                        Button("Refresh readings") { Task { await app.refreshHomeDevices() } }
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
        .onChange(of: showsPurifierControls) { _, covered in onDetailVisibilityChanged(covered) }
        .onDisappear { onDetailVisibilityChanged(false) }
        .accessibilityIdentifier("home-device-controls")
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
            let stale = purifier.stale == true || app.connectionState != .connected
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
        .tabSwipeExcluded()
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
        .jarvisGlassSurface(JarvisPalette.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
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
        .jarvisGlassSurface(
            JarvisPalette.surface,
            in: RoundedRectangle(cornerRadius: 14, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(JarvisPalette.accent.opacity(0.20), lineWidth: 0.75)
                .allowsHitTesting(false)
        }
    }

    private func row(_ item: PurifierSubsystem, busy: Bool) -> some View {
        let name = item.name ?? "Air Purifier"
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
            Text(name).font(.system(size: 12, weight: .semibold))
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
