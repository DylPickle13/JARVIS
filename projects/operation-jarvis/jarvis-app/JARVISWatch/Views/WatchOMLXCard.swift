import SwiftUI
import JARVISKit

struct WatchOMLXCard: View {
    @ObservedObject var model: OMLXStatusModel
    let active: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1, paused: !active)) { context in
            OMLXSummaryContent(rows: OMLXSnapshot.serverIDs.map { id in
                    OMLXServerSummary(id: id, server: model.snapshot?.servers.first { $0.id == id },
                        now: context.date, requestStartedAt: model.requestStartedAt,
                        available: active && model.isPolling && !model.unavailable,
                        checking: model.snapshot == nil && model.isPolling && !model.unavailable)
                }, compact: true, motionActive: active)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 13, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.08), lineWidth: 0.5)
                }
        }
    }
}
