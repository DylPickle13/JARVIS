import SwiftUI
import JARVISKit

struct SystemView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.scenePhase) private var scenePhase
    @State private var showsDetails = false
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
                    HomeDeviceControls { covered in
                        showsDetails = covered
                        app.setSystemDetailsCovered(covered || showsServices)
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
                app.setSystemDetailsCovered(scope != nil || showsDetails)
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
