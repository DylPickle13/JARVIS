import SwiftUI
import WidgetKit
import JARVISKit

private struct SpotifyLauncherEntry: TimelineEntry { let date: Date }
private struct SpotifyLauncherProvider: TimelineProvider {
    func placeholder(in context: Context) -> SpotifyLauncherEntry { .init(date: .now) }
    func getSnapshot(in context: Context, completion: @escaping (SpotifyLauncherEntry) -> Void) {
        completion(.init(date: .now))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<SpotifyLauncherEntry>) -> Void) {
        completion(.init(entries: [.init(date: .now)], policy: .never))
    }
}

/// A music-specific sibling of Resonance. Motion never represents playback state.
private struct SpotifyLauncherArtwork: View {
    @Environment(\.isLuminanceReduced) private var dimmed
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var animate: Bool {
        !dimmed && !reduceMotion && JARVISWidgetTimerAnimationFont.isAvailable
    }

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            ZStack {
                // Static ring and symbol never depend on the animation masks.
                Circle().trim(from: 0.04, to: 0.45).stroke(.white.opacity(0.8), lineWidth: 1)
                    .rotationEffect(.degrees(-90))
                Circle().trim(from: 0.54, to: 0.95).stroke(.white.opacity(0.8), lineWidth: 1)
                    .rotationEffect(.degrees(-90))
                Circle().stroke(.white.opacity(0.2), lineWidth: 0.5).padding(side * 0.065)
                Image(systemName: "music.note").font(.system(size: side * 0.39, weight: .medium))
                    .foregroundStyle(.white)
                if animate {
                    // Eight small decorative scenes, not another 24-frame core.
                    ForEach(0..<8, id: \.self) { index in
                        Circle().trim(from: 0, to: 0.065)
                            .stroke(.white.opacity(0.8), style: StrokeStyle(lineWidth: 1.3, lineCap: .round))
                            .rotationEffect(.degrees(24 + 13 * sin(Double(index) * .pi / 4)))
                            .padding(side * 0.065)
                            .frame(width: side, height: side)
                            .mask {
                                JARVISWidgetTimerFrameWindow(frameIndex: index, frameCount: 8, extent: max(1, side))
                                    .frame(width: side, height: side)
                            }
                    }
                }
            }
            .frame(width: side, height: side)
            .scaleEffect(0.82)
            .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
        }
        .id(animate)
        .widgetAccentable()
        .accessibilityHidden(true)
    }
}

private struct SpotifyLauncherView: View {
    @Environment(\.widgetFamily) private var family
    var body: some View {
        Group {
            switch family {
            case .accessoryInline:
                Label("Spotify", systemImage: "music.note")
            case .accessoryRectangular:
                HStack(spacing: 8) {
                    SpotifyLauncherArtwork().frame(width: 40, height: 40)
                    VStack(alignment: .leading) {
                        Text("Spotify").font(.headline)
                        Text("Open on Watch").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            case .accessoryCorner:
                SpotifyLauncherArtwork().frame(width: 29, height: 29)
                    .widgetLabel { Text("Spotify") }
            default:
                SpotifyLauncherArtwork()
            }
        }
        .widgetURL(JARVISWatchSpotifyRoute.widgetURL)
        .jarvisWatchWidgetBackground()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Open Spotify on Apple Watch")
    }
}

struct JARVISWatchSpotifyWidget: Widget {
    let kind = "JARVISWatchSpotifyWidget.v1"
    init() { JARVISWidgetTimerAnimationFont.register() }
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SpotifyLauncherProvider()) { _ in SpotifyLauncherView() }
            .configurationDisplayName("Spotify · JARVIS")
            .description("A decorative JARVIS music icon that requests Spotify on this Watch. Requires the Spotify Watch app.")
            .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}
