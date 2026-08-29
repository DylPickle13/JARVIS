import SwiftUI
import WidgetKit
import JARVISKit

let jarvisHomeURL = URL(string: "jarvis://home")!

struct JARVISStateEntry: TimelineEntry {
    let date: Date
    let cached: CachedState?
    let placeholder: Bool
}

struct JARVISStateProvider: TimelineProvider {
    func placeholder(in context: Context) -> JARVISStateEntry {
        JARVISStateEntry(date: Date(), cached: nil, placeholder: true)
    }

    func getSnapshot(in context: Context, completion: @escaping @Sendable (JARVISStateEntry) -> Void) {
        completion(
            JARVISStateEntry(
                date: Date(),
                cached: JARVISWidgetStateLoader.cachedState(),
                placeholder: context.isPreview
            )
        )
    }

    func getTimeline(in context: Context, completion: @escaping @Sendable (Timeline<JARVISStateEntry>) -> Void) {
        Task {
            let now = Date()
            let cached = await JARVISWidgetStateLoader.refreshedState()
            completion(
                Timeline(
                    entries: [JARVISStateEntry(date: now, cached: cached, placeholder: false)],
                    policy: .after(now.addingTimeInterval(JARVISWidgetStateLoader.timelineRefreshInterval))
                )
            )
        }
    }
}

extension View {
    func jarvisWidgetBackground() -> some View {
        containerBackground(.fill.tertiary, for: .widget)
    }
}
