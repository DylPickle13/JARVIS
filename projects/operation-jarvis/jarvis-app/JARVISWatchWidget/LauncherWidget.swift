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
    var talk = false
    @Environment(\.widgetFamily) private var family
    @Environment(\.widgetRenderingMode) private var renderingMode

    var body: some View {
        Group {
            switch family {
            case .accessoryInline:
                // Inline complications have no reliable full-color image area.
                Label(talk ? "Talk to JARVIS" : "Open JARVIS", systemImage: talk ? "waveform" : "app.fill")
            case .accessoryCorner:
                renderedIcon
                    .scaledToFit()
                    .frame(width: 27, height: 27)
                    .clipShape(Circle())
                    .widgetLabel { Text("JARVIS") }
            case .accessoryRectangular:
                HStack(spacing: 8) {
                    renderedIcon
                        .scaledToFit()
                        .frame(width: 32, height: 32)
                        .clipShape(Circle())
                    VStack(alignment: .leading, spacing: 1) {
                        Text("JARVIS").font(.headline)
                        Text(talk ? "Talk to JARVIS" : "Open app").font(.caption2).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "arrow.up.forward.app").font(.caption2)
                }
            case .accessoryCircular:
                circularIcon
            default:
                Image(systemName: "app.fill")
            }
        }
        .widgetURL(talk ? URL(string: "jarvis://talk")! : jarvisWatchHomeURL)
        .jarvisWatchWidgetBackground()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(talk ? "Talk to JARVIS" : "Open JARVIS app")
    }

    @ViewBuilder
    private var circularIcon: some View {
        if talk {
            JARVISResonanceArtwork()
        } else {
            GeometryReader { geometry in
                let side = min(geometry.size.width, geometry.size.height)
                ZStack {
                    if renderingMode == .fullColor {
                        Circle().fill(Color.black)
                        fullColorIcon
                            .scaledToFill()
                    } else {
                        accentedIcon
                            .scaledToFit()
                    }
                }
                .frame(width: side, height: side)
                .clipShape(Circle())
                .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
            }
        }
    }

    @ViewBuilder
    private var renderedIcon: some View {
        if talk {
            JARVISResonanceArtwork()
        } else if renderingMode == .fullColor {
            fullColorIcon
        } else {
            accentedIcon
        }
    }

    private var fullColorIcon: some View {
        Image("JARVISWidgetIcon", bundle: .main)
            .resizable()
            .interpolation(.high)
    }

    private var accentedIcon: some View {
        Image("JARVISWidgetIconAccented", bundle: .main)
            .resizable()
            .interpolation(.high)
            .widgetAccentable()
    }
}

struct JARVISWatchLauncherWidget: Widget {
    let kind = "JARVISWatchLauncherWidget.v2"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchLauncherProvider()) { _ in
            JARVISWatchLauncherView()
        }
        .configurationDisplayName("Open JARVIS")
        .description("Launch the JARVIS Watch app from your watch face or Smart Stack.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}

/// Explicit user-entry point: opening this URL never submits a prompt.
struct JARVISWatchTalkWidget: Widget {
    let kind = "JARVISWatchTalkWidget.v1"

    init() {
        JARVISWidgetTimerAnimationFont.register()
    }

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchLauncherProvider()) { _ in
            JARVISWatchLauncherView(talk: true)
        }
        .configurationDisplayName("Talk to JARVIS")
        .description("Dictate or type; finishing native input sends to Pi session 10.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}
