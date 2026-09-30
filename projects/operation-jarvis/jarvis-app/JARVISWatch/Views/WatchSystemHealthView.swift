import SwiftUI
import JARVISKit

struct WatchSystemHealthView: View {
    @ObservedObject var model: WatchConnectModel
    let active: Bool
    let onDetailVisibilityChanged: (Bool) -> Void

    var body: some View {
        // Fixed overview: no pan/Crown scrolling competes with page navigation.
        TimelineView(.animation(minimumInterval: 5, paused: !active)) { _ in
            SystemDashboardContent(presentation: .init(snapshot: model.lastState,
                requestStartedAt: SystemDashboardPresentation.snapshotGeneratedAt(model.lastState),
                isConnected: model.connectionState == .connected),
                connectionLabel: model.statusText, compact: true,
                accent: WatchJarvisStyle.accent, warning: WatchJarvisStyle.warning,
                surface: WatchJarvisStyle.surface, connectionError: model.errorMessage,
                historyModel: model.systemHistory,
                onDetailVisibilityChanged: onDetailVisibilityChanged)
                .padding(.horizontal, 8)
                .padding(.vertical, 7)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }
}
