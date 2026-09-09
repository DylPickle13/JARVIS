import SwiftUI
import JARVISKit

struct OMLXStatusCard: View {
    let endpoint: JarvisEndpoint?
    let active: Bool
    @StateObject private var model: OMLXStatusModel

    init(client: any JarvisAPI, endpoint: JarvisEndpoint?, active: Bool) {
        self.endpoint = endpoint
        self.active = active
        _model = StateObject(wrappedValue: OMLXStatusModel(fetch: { try await client.omlxStatus($0) }))
    }

    private var poll: OMLXPollConfiguration {
        .init(endpoint: endpoint, surface: .iPhoneHome, visible: active, interactive: active)
    }
    private var available: Bool { active && model.isPolling && !model.unavailable }
    private var checking: Bool { model.snapshot == nil && model.isPolling && !model.unavailable }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1, paused: !active)) { context in
            MinimalCard(padding: 11) {
                OMLXSummaryContent(rows: OMLXSnapshot.serverIDs.map { id in
                    OMLXServerSummary(id: id, server: model.snapshot?.servers.first { $0.id == id },
                        now: context.date, requestStartedAt: model.requestStartedAt,
                        available: available, checking: checking)
                })
            }
        }
        .task(id: poll) { await model.run(endpoint: poll.endpoint, interval: poll.interval) }
    }
}
