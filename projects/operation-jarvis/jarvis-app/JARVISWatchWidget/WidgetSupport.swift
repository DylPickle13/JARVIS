import SwiftUI
import WidgetKit
import JARVISKit

let jarvisWatchHomeURL = URL(string: "jarvis://home")!

struct JARVISWatchStateEntry: TimelineEntry {
    let date: Date
    let cached: CachedState?
    let placeholder: Bool
}

struct JARVISWatchStateProvider: TimelineProvider {
    func placeholder(in context: Context) -> JARVISWatchStateEntry {
        JARVISWatchStateEntry(date: Date(), cached: nil, placeholder: true)
    }

    func getSnapshot(in context: Context, completion: @escaping @Sendable (JARVISWatchStateEntry) -> Void) {
        completion(
            JARVISWatchStateEntry(
                date: Date(),
                cached: JARVISWidgetStateLoader.cachedState(),
                placeholder: context.isPreview
            )
        )
    }

    func getTimeline(in context: Context, completion: @escaping @Sendable (Timeline<JARVISWatchStateEntry>) -> Void) {
        Task {
            let now = Date()
            let cached = await JARVISWidgetStateLoader.refreshedState()
            completion(
                Timeline(
                    entries: [JARVISWatchStateEntry(date: now, cached: cached, placeholder: false)],
                    policy: .after(now.addingTimeInterval(JARVISWidgetStateLoader.timelineRefreshInterval))
                )
            )
        }
    }
}

extension View {
    func jarvisWatchWidgetBackground() -> some View {
        containerBackground(.fill.tertiary, for: .widget)
    }
}
