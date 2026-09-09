import SwiftUI
import JARVISKit

struct WatchOMLXCard: View {
    @ObservedObject var model: OMLXStatusModel
    let active: Bool
    let onOpen: () -> Void

    var body: some View {
        TimelineView(.animation(minimumInterval: 1, paused: !active)) { context in
            Button(action: onOpen) {
                OMLXSummaryContent(rows: OMLXSnapshot.serverIDs.map { id in
                    OMLXServerSummary(id: id, server: model.snapshot?.servers.first { $0.id == id },
                        now: context.date, requestStartedAt: model.requestStartedAt,
                        available: active && model.isPolling && !model.unavailable,
                        checking: model.snapshot == nil && model.isPolling && !model.unavailable)
                }, compact: true)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(!active)
            .accessibilityHint("Show read-only model details for both servers")
        }
    }
}

struct WatchOMLXDetails: View {
    @ObservedObject var model: OMLXStatusModel
    let active: Bool
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            // This sheet owns its native scrolling/Crown. The underlying System
            // viewport relinquishes focus and its pager ignores sheet input.
            ScrollView {
                TimelineView(.animation(minimumInterval: 1, paused: !active)) { context in
                    VStack(alignment: .leading, spacing: 16) {
                        ForEach(OMLXSnapshot.serverIDs, id: \.self) { id in
                            if id != OMLXSnapshot.serverIDs.first { Divider() }
                            OMLXServerContent(id: id, server: model.snapshot?.servers.first { $0.id == id },
                                now: context.date, requestStartedAt: model.requestStartedAt,
                                available: active && model.isPolling && !model.unavailable,
                                checking: model.snapshot == nil && model.isPolling && !model.unavailable)
                        }
                    }
                    .padding(.horizontal, 8)
                }
            }
            .navigationTitle("oMLX")
            .toolbar { ToolbarItem(placement: .cancellationAction) {
                Button("Done") { dismiss() }
            } }
        }
    }
}
