import SwiftUI
import JARVISKit

struct SystemView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            TimelineView(.animation(minimumInterval: 5,
                paused: scenePhase != .active || app.activeSection != .system)) { _ in
                // Timeline ticks schedule redraws, not the evaluation clock.
                SystemDashboardContent(presentation: .init(snapshot: app.lastState,
                    requestStartedAt: app.lastStateRequestStartedAt,
                    isConnected: app.connectionState == .connected),
                    connectionLabel: connectionLabel, accent: JarvisPalette.accent,
                    warning: JarvisPalette.warning, surface: JarvisPalette.surface,
                    connectionError: app.stateErrorMessage ?? app.errorMessage,
                    refreshing: app.isStateLoading || app.isRefreshing,
                    onRefresh: {
                        Task {
                            guard scenePhase == .active, app.activeSection == .system else { return }
                            if app.connectionState == .connected { await app.fetchState() }
                            else { await app.connect() }
                        }
                    })
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(JarvisBackdrop())
            .toolbar(.hidden, for: .navigationBar)
        }
    }

    private var connectionLabel: String {
        switch app.connectionState {
        case .connected: return "Connected · cached observations"
        case .connecting: return "Connecting"
        case .failed: return "Offline · tap refresh to reconnect"
        case .idle: return "Not connected · tap refresh to connect"
        }
    }
}
