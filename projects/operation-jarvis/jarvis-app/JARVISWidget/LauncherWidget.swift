import SwiftUI
import WidgetKit

private struct JARVISLauncherEntry: TimelineEntry {
    let date: Date
}

private struct JARVISLauncherProvider: TimelineProvider {
    func placeholder(in context: Context) -> JARVISLauncherEntry { .init(date: Date()) }
    func getSnapshot(in context: Context, completion: @escaping (JARVISLauncherEntry) -> Void) {
        completion(.init(date: Date()))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<JARVISLauncherEntry>) -> Void) {
        completion(Timeline(entries: [.init(date: Date())], policy: .never))
    }
}

private struct JARVISLauncherView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        Group {
            switch family {
            case .accessoryInline:
                Label("Open JARVIS", systemImage: "sparkles")
            case .accessoryCircular:
                ZStack {
                    AccessoryWidgetBackground()
                    Image(systemName: "sparkles")
                        .font(.title2.weight(.semibold))
                        .widgetAccentable()
                }
                .accessibilityLabel("Open JARVIS")
            case .accessoryRectangular:
                HStack(spacing: 8) {
                    Image(systemName: "sparkles")
                        .font(.title2.weight(.semibold))
                        .widgetAccentable()
                    VStack(alignment: .leading, spacing: 1) {
                        Text("JARVIS").font(.headline)
                        Text("Open app").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "arrow.up.forward.app").font(.caption)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Open JARVIS app")
            default:
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Image(systemName: "sparkles")
                            .font(.title2.weight(.semibold))
                            .foregroundStyle(JARVISWidgetTheme.accent)
                        Spacer()
                        Image(systemName: "arrow.up.forward.app")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    Text("JARVIS")
                        .font(.title2.bold())
                    Text("Open app")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Open JARVIS app")
            }
        }
        .widgetURL(jarvisHomeURL)
        .jarvisWidgetBackground()
    }
}

struct JARVISLauncherWidget: Widget {
    let kind = "JARVISLauncherWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISLauncherProvider()) { _ in
            JARVISLauncherView()
        }
        .configurationDisplayName("Open JARVIS")
        .description("Launch JARVIS directly from your Home Screen or Lock Screen.")
        .supportedFamilies([.systemSmall, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}
