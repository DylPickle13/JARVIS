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
                // Inline complications have no reliable full-color image area.
                Label("Open JARVIS", systemImage: "app.fill")
            case .accessoryCorner:
                brandedIcon
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 27, height: 27)
                    .clipShape(Circle())
                    .widgetLabel { Text("JARVIS") }
            case .accessoryRectangular:
                HStack(spacing: 8) {
                    brandedIcon
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 32, height: 32)
                        .clipShape(Circle())
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
                    Circle()
                        .fill(Color.cyan.opacity(0.10))
                    brandedIcon
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .padding(3)
                        .clipShape(Circle())
                }
            }
        }
        .widgetURL(jarvisWatchHomeURL)
        .jarvisWatchWidgetBackground()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Open JARVIS app")
    }

    @ViewBuilder
    private var brandedIcon: some View {
        if #available(watchOS 11.0, *) {
            Image("JARVISWidgetIcon", bundle: .main)
                .resizable()
                .interpolation(.high)
                .widgetAccentedRenderingMode(.fullColor)
        } else {
            Image("JARVISWidgetIcon", bundle: .main)
                .resizable()
                .interpolation(.high)
        }
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
