import SwiftUI
import JARVISKit

struct WatchSystemHealthView: View {
    @ObservedObject var model: WatchConnectModel
    let active: Bool
    let onDetailVisibilityChanged: (Bool) -> Void
    @State private var serviceScope: SystemServicesScope?
    private var showsServices: Bool { serviceScope != nil }
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.isLuminanceReduced) private var dimmed

    var body: some View {
        // Health-only Home overview; the parent provides Crown overflow for large text.
        TimelineView(.animation(minimumInterval: 5, paused: !active)) { _ in
            SystemDashboardContent(presentation: .init(snapshot: model.lastState,
                requestStartedAt: SystemDashboardPresentation.snapshotGeneratedAt(model.lastState),
                isConnected: model.connectionState == .connected),
                connectionLabel: model.statusText, compact: true,
                accent: WatchJarvisStyle.accent, warning: WatchJarvisStyle.warning,
                surface: WatchJarvisStyle.surface, connectionError: model.errorMessage,
                historyModel: model.systemHistory,
                onServices: { serviceScope = .services },
                onMinecraft: { serviceScope = .minecraft })

        }
        .frame(maxWidth: .infinity, alignment: .top)
        .onChange(of: serviceScope) { _, scope in onDetailVisibilityChanged(scope != nil) }
        .onDisappear { onDetailVisibilityChanged(false) }
        .sheet(item: $serviceScope) { scope in
            NavigationStack {
                WatchSystemCrownViewport(active: scenePhase == .active && !dimmed && showsServices) {
                    TimelineView(.animation(minimumInterval: 5,
                        paused: scenePhase != .active || dimmed || !showsServices)) { _ in
                        SystemServicesContent(presentation: .init(snapshot: model.lastState,
                            requestStartedAt: SystemDashboardPresentation.snapshotGeneratedAt(model.lastState),
                            isConnected: model.connectionState == .connected), scope: scope, compact: true,
                            accent: WatchJarvisStyle.accent, warning: WatchJarvisStyle.warning,
                            surface: WatchJarvisStyle.surface)
                    }
                }
                .padding(.horizontal, 8)
                .navigationTitle(scope.title)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { serviceScope = nil }
                    }
                }
            }
            .onAppear { onDetailVisibilityChanged(true) }
            .onDisappear { onDetailVisibilityChanged(false) }
        }
    }
}
