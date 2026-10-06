import SwiftUI
import JARVISKit

struct SystemView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.scenePhase) private var scenePhase
    @State private var showsDetails = false
    @State private var showsHomeConfirmation = false
    @State private var serviceScope: SystemServicesScope?
    private var showsServices: Bool { serviceScope != nil }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    TabPageHeader(title: "Home")
                    TimelineView(.animation(minimumInterval: 5,
                        paused: scenePhase != .active || app.activeSection != .system || showsDetails || showsServices)) { _ in
                        // Timeline ticks schedule redraws, not the evaluation clock.
                        SystemDashboardContent(presentation: .init(snapshot: app.lastState,
                            requestStartedAt: app.lastStateRequestStartedAt,
                            isConnected: app.connectionState == .connected),
                            connectionLabel: connectionLabel, showsHeader: false, accent: JarvisPalette.accent,
                            warning: JarvisPalette.warning, surface: JarvisPalette.surface,
                            connectionError: app.stateErrorMessage ?? app.errorMessage,
                            refreshing: app.isStateLoading || app.isRefreshing,
                            historyModel: app.systemHistory,
                            onServices: { serviceScope = .services },
                            onMinecraft: { serviceScope = .minecraft })
                    }
                    HomeAutomationCards { covered in
                        showsHomeConfirmation = covered
                        app.setSystemDetailsCovered(covered || showsDetails || showsServices)
                    }
                    HomeDeviceControls { covered in
                        showsDetails = covered
                        app.setSystemDetailsCovered(covered || showsServices || showsHomeConfirmation)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
            .scrollIndicators(.hidden)
            .scrollBounceBehavior(.always)
            .background(JarvisBackdrop())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await refreshSystem() }
            .onAppear { app.setSystemViewVisible(true) }
            .onDisappear { app.setSystemViewVisible(false) }
            .onChange(of: serviceScope) { _, scope in
                app.setSystemDetailsCovered(scope != nil || showsDetails || showsHomeConfirmation)
            }
            .sheet(item: $serviceScope) { scope in servicesSheet(scope: scope) }
        }
    }

    private func servicesSheet(scope: SystemServicesScope) -> some View {
        NavigationStack {
            ScrollView {
                TimelineView(.animation(minimumInterval: 5, paused: scenePhase != .active || !showsServices)) { _ in
                    SystemServicesContent(presentation: .init(snapshot: app.lastState,
                        requestStartedAt: app.lastStateRequestStartedAt,
                        isConnected: app.connectionState == .connected), scope: scope,
                        accent: JarvisPalette.accent, warning: JarvisPalette.warning,
                        surface: JarvisPalette.surface)
                }
                .padding(16)
            }
            .navigationTitle(scope.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { serviceScope = nil }
                }
            }
            .background(JarvisBackdrop())
        }
    }

    private func refreshSystem() async {
        guard scenePhase == .active, app.activeSection == .system else { return }
        app.systemHistory.refresh()
        if app.connectionState == .connected { await app.refreshHomeDevices() }
        else { await app.connect() }
    }

    private var connectionLabel: String {
        switch app.connectionState {
        case .connected: return "Connected · cached observations"
        case .connecting: return "Connecting"
        case .failed: return "Offline · pull to refresh to reconnect"
        case .idle: return "Not connected · pull to refresh to connect"
        }
    }
}

struct HomeAutomationCards: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.scenePhase) private var scenePhase
    let onConfirmationChanged: (Bool) -> Void
    @State private var barnConfirmation: HomeAutomationCommand?

    var body: some View {
        TimelineView(.animation(minimumInterval: 5,
            paused: scenePhase != .active || app.activeSection != .system)) { context in
            VStack(alignment: .leading, spacing: 6) {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8),
                    count: dynamicTypeSize.isAccessibilitySize ? 1 : 2), spacing: 8) {
                    ForEach(HomeAutomationControl.allCases, id: \.self) { control in
                        card(control, at: context.date)
                    }
                }
                ForEach(HomeAutomationControl.allCases, id: \.self) { control in
                    if let warning = app.lastState?.homeAutomations?[control]?.outcomeWarning {
                        Text("\(control.title): \(warning)")
                            .font(.caption2).foregroundStyle(JarvisPalette.warning)
                    }
                }
            }
        }
        .confirmationDialog("Enable Barn Door Protocol?", isPresented: Binding(
            get: { barnConfirmation != nil }, set: { if !$0 { barnConfirmation = nil } }), titleVisibility: .visible) {
            Button("Enable protocol", role: .destructive) {
                guard let command = barnConfirmation else { return }
                barnConfirmation = nil
                Task { await app.setHomeAutomation(command) }
            }
            Button("Cancel", role: .cancel) { barnConfirmation = nil }
        } message: {
            Text("Enabling may trigger physical actions immediately or later. Disabling does not stop an alarm already sounding.")
        }
        .onChange(of: barnConfirmation) { _, command in onConfirmationChanged(command != nil) }
        .onDisappear { barnConfirmation = nil; onConfirmationChanged(false) }
    }

    private func card(_ control: HomeAutomationControl, at now: Date) -> some View {
        let state = app.lastState?.homeAutomations?[control]
        let connected = app.connectionState == .connected
        let busy = app.isHomeAutomationBusy(control)
        let label = busy ? (connected ? "Changing…" : "Unconfirmed") : state?.label(connected: connected, now: now) ?? "Unavailable"
        return Button {
            guard let revision = state?.revision, let enabled = state?.enabled else { return }
            let command = HomeAutomationCommand(control: control, enabled: !enabled, revision: revision,
                confirmed: control == .barnDoor && !enabled)
            if control == .barnDoor && !enabled { barnConfirmation = command }
            else { Task { await app.setHomeAutomation(command) } }
        } label: {
            HomeAutomationCardContent(control: control, status: label,
                enabled: connected && state?.isFresh(now: now) == true ? state?.enabled : nil,
                busy: busy, hasWarning: state?.outcomeWarning != nil || label == "Unconfirmed",
                size: .phone, accent: JarvisPalette.accent, warning: JarvisPalette.warning,
                surface: JarvisPalette.surface)
        }
        .buttonStyle(JarvisPressStyle())
        .disabled(busy || state?.canChange(control, connected: connected, now: now) != true)
        .accessibilityElement(children: .ignore)
        .accessibilityIdentifier("home-automation-\(control.rawValue)")
        .accessibilityLabel(control.title)
        .accessibilityValue(label + (state?.outcomeWarning.map { ". \($0)" } ?? ""))
        .accessibilityHint(control == .automaticVoice
            ? "Changes unsolicited announcements only. Audio already started may finish."
            : "Changes Barn Door Protocol. Enabling requires confirmation; disabling does not silence an active alarm.")
    }
}
