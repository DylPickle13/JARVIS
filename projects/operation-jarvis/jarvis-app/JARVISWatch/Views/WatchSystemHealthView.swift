import SwiftUI
import JARVISKit

struct WatchSystemHealthView: View {
    @ObservedObject var model: WatchConnectModel
    let active: Bool
    let onDetailVisibilityChanged: (Bool) -> Void
    @State private var showsServices = false
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
                onServices: { showsServices = true })

        }
        .frame(maxWidth: .infinity, alignment: .top)
        .onChange(of: showsServices) { _, covered in onDetailVisibilityChanged(covered) }
        .onDisappear { onDetailVisibilityChanged(false) }
        .sheet(isPresented: $showsServices) {
            NavigationStack {
                WatchSystemCrownViewport(active: scenePhase == .active && !dimmed && showsServices) {
                    TimelineView(.animation(minimumInterval: 5,
                        paused: scenePhase != .active || dimmed || !showsServices)) { _ in
                        SystemServicesContent(presentation: .init(snapshot: model.lastState,
                            requestStartedAt: SystemDashboardPresentation.snapshotGeneratedAt(model.lastState),
                            isConnected: model.connectionState == .connected), compact: true,
                            accent: WatchJarvisStyle.accent, warning: WatchJarvisStyle.warning,
                            surface: WatchJarvisStyle.surface)
                    }
                }
                .padding(.horizontal, 8)
                .navigationTitle("Services")
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { showsServices = false }
                    }
                }
            }
            .onAppear { onDetailVisibilityChanged(true) }
            .onDisappear { onDetailVisibilityChanged(false) }
        }
    }
}
