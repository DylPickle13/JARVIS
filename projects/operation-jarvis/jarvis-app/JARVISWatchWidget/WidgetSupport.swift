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

    func getSnapshot(in context: Context, completion: @escaping (JARVISWatchStateEntry) -> Void) {
        completion(
            JARVISWatchStateEntry(
                date: Date(),
                cached: JARVISWidgetStateLoader.cachedState(),
                placeholder: context.isPreview
            )
        )
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<JARVISWatchStateEntry>) -> Void) {
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

enum JARVISWatchWidgetFormat {
    static func displayName(_ raw: String) -> String {
        raw.replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }

    static func purifierQuality(pm25: Int?) -> (label: String, color: Color) {
        guard let pm25 else { return ("Unavailable", .secondary) }
        switch pm25 {
        case ...12: return ("Good", .green)
        case 13...35: return ("Moderate", .yellow)
        case 36...55: return ("Sensitive", .orange)
        default: return ("Unhealthy", .red)
        }
    }
}

extension View {
    func jarvisWatchWidgetBackground() -> some View {
        containerBackground(.fill.tertiary, for: .widget)
    }
}
