import SwiftUI
import JARVISKit

struct WatchSystemHealthView: View {
    @ObservedObject var model: WatchConnectModel
    let active: Bool
    let onDetailVisibilityChanged: (Bool) -> Void

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
                onDetailVisibilityChanged: onDetailVisibilityChanged)

        }
        .frame(maxWidth: .infinity, alignment: .top)
    }
}
