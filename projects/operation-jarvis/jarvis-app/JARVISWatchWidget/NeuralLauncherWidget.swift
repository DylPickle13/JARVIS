import SwiftUI
import WidgetKit
import JARVISKit

private struct JARVISWatchNeuralLauncherView: View {
    let entry: JARVISWatchStateEntry

    private var telemetry: JARVISNeuralCoreTelemetry {
        JARVISNeuralCoreTelemetry(cached: entry.cached, placeholder: entry.placeholder, now: entry.date)
    }

    var body: some View {
        ZStack {
            JARVISNeuralCoreContinuousArtwork(
                telemetry: telemetry,
                layout: .watch,
                basePhase: JARVISNeuralCoreMotion.phase(for: entry.date),
                allowsMotion: !entry.placeholder
            )
            .id(entry.date.timeIntervalSinceReferenceDate)

            HStack(spacing: 0) {
                Link(destination: JARVISWatchWidgetRoute.quickActionsURL) {
                    JARVISWatchLauncherButtonChrome {
                        JARVISWatchShortcutsGlyph()
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("JARVIS Shortcuts")
                .accessibilityHint("Opens JARVIS quick actions")

                Spacer(minLength: 44)

                Link(destination: JARVISWatchWidgetRoute.nowPlayingURL) {
                    JARVISWatchLauncherButtonChrome {
                        JARVISWatchSpotifyGlyph()
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Spotify Now Playing")
                .accessibilityHint("Opens system controls for the current Spotify session")
            }
        }
        // Taps outside the two explicit Link regions preserve the accepted
        // Neural Core behavior and open the JARVIS Pi terminal.
        .widgetURL(JARVISWatchNeuralCoreWidget.terminalURL)
        .containerBackground(for: .widget) {
            Color.clear
        }
    }
}

private struct JARVISWatchLauncherButtonChrome<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .frame(width: 20, height: 20)
            .padding(4)
            .background {
                Circle()
                    .fill(.black.opacity(0.76))
                    .overlay {
                        Circle().stroke(.white.opacity(0.36), lineWidth: 0.7)
                    }
            }
            .frame(width: 40)
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .widgetAccentable()
    }
}

private struct JARVISWatchShortcutsGlyph: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 2.2, style: .continuous)
                .stroke(.white, lineWidth: 1.8)
                .frame(width: 10, height: 10)
                .rotationEffect(.degrees(45))
                .offset(x: -3.3, y: 3.3)
            RoundedRectangle(cornerRadius: 2.2, style: .continuous)
                .stroke(.white, lineWidth: 1.8)
                .frame(width: 10, height: 10)
                .rotationEffect(.degrees(45))
                .offset(x: 3.3, y: -3.3)
        }
        .accessibilityHidden(true)
    }
}

private struct JARVISWatchSpotifyGlyph: View {
    var body: some View {
        Canvas { context, size in
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            let radius = min(size.width, size.height) * 0.45

            context.stroke(
                Path(ellipseIn: CGRect(
                    x: center.x - radius,
                    y: center.y - radius,
                    width: radius * 2,
                    height: radius * 2
                )),
                with: .color(.white),
                lineWidth: 1.5
            )

            for index in 0..<3 {
                let inset = CGFloat(index) * 2.5
                var wave = Path()
                wave.move(to: CGPoint(x: 4 + inset * 0.45, y: 7 + inset))
                wave.addCurve(
                    to: CGPoint(x: 16 - inset * 0.45, y: 8.5 + inset),
                    control1: CGPoint(x: 8, y: 4.8 + inset),
                    control2: CGPoint(x: 13, y: 5.5 + inset)
                )
                context.stroke(
                    wave,
                    with: .color(.white.opacity(1 - Double(index) * 0.14)),
                    style: StrokeStyle(lineWidth: 1.45, lineCap: .round)
                )
            }
        }
        .accessibilityHidden(true)
    }
}

struct JARVISWatchNeuralLauncherWidget: Widget {
    static let kind = "JARVISWatchNeuralLauncherWidget.v1"

    init() {
        JARVISWidgetTimerAnimationFont.register()
    }

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: Self.kind, provider: JARVISWatchStateProvider()) { entry in
            JARVISWatchNeuralLauncherView(entry: entry)
        }
        .configurationDisplayName("JARVIS Neural Launcher")
        .description("Neural Core with JARVIS Shortcuts and Spotify Now Playing controls.")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}
