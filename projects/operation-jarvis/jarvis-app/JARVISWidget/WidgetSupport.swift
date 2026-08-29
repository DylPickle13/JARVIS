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

    func getSnapshot(in context: Context, completion: @escaping (JARVISStateEntry) -> Void) {
        completion(
            JARVISStateEntry(
                date: Date(),
                cached: JARVISWidgetStateLoader.cachedState(),
                placeholder: context.isPreview
            )
        )
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<JARVISStateEntry>) -> Void) {
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

enum JARVISWidgetFormat {
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

    static func purifierStatus(_ purifier: PurifierSubsystem) -> String {
        guard let isOn = purifier.isOn else { return "Status unavailable" }
        guard isOn else { return "Off" }
        let mode = (purifier.mode ?? "On").capitalized
        if let fan = purifier.fanSetLevel ?? purifier.fanLevel { return "\(mode) · Fan \(fan)" }
        return mode
    }
}

extension View {
    func jarvisWidgetBackground() -> some View {
        containerBackground(.fill.tertiary, for: .widget)
    }
}
