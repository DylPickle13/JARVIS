import SwiftUI
import WidgetKit

private struct JARVISWatchLauncherEntry: TimelineEntry {
    let date: Date
}

private struct JARVISWatchLauncherProvider: TimelineProvider {
    func placeholder(in context: Context) -> JARVISWatchLauncherEntry { .init(date: Date()) }
    func getSnapshot(in context: Context, completion: @escaping (JARVISWatchLauncherEntry) -> Void) {
        completion(.init(date: Date()))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<JARVISWatchLauncherEntry>) -> Void) {
        completion(Timeline(entries: [.init(date: Date())], policy: .never))
    }
}

private struct JARVISWatchLauncherView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        Group {
            switch family {
            case .accessoryInline:
                Label("Open JARVIS", systemImage: "sparkles")
            case .accessoryCorner:
                Image(systemName: "sparkles")
                    .font(.title3.weight(.semibold))
                    .widgetAccentable()
                    .widgetLabel { Text("JARVIS") }
            case .accessoryRectangular:
                HStack(spacing: 8) {
                    Image(systemName: "sparkles")
                        .font(.title2.weight(.semibold))
                        .widgetAccentable()
                    VStack(alignment: .leading, spacing: 1) {
                        Text("JARVIS").font(.headline)
                        Text("Open app").font(.caption2).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "arrow.up.forward.app").font(.caption2)
                }
            default:
                ZStack {
                    AccessoryWidgetBackground()
                    VStack(spacing: 1) {
                        Image(systemName: "sparkles")
                            .font(.title3.weight(.semibold))
                            .widgetAccentable()
                        Text("JARVIS").font(.caption2.bold())
                    }
                }
            }
        }
        .widgetURL(jarvisWatchHomeURL)
        .jarvisWatchWidgetBackground()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Open JARVIS app")
    }
}

struct JARVISWatchLauncherWidget: Widget {
    let kind = "JARVISWatchLauncherWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchLauncherProvider()) { _ in
            JARVISWatchLauncherView()
        }
        .configurationDisplayName("Open JARVIS")
        .description("Launch the JARVIS Watch app from your watch face or Smart Stack.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}
