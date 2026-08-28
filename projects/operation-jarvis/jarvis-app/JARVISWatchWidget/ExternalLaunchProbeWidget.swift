import AppIntents
import SwiftUI
import WidgetKit

private struct JARVISWatchExternalLaunchProbeEntry: TimelineEntry {
    let date: Date
}

private struct JARVISWatchExternalLaunchProbeProvider: TimelineProvider {
    func placeholder(in context: Context) -> JARVISWatchExternalLaunchProbeEntry {
        .init(date: Date())
    }

    func getSnapshot(
        in context: Context,
        completion: @escaping (JARVISWatchExternalLaunchProbeEntry) -> Void
    ) {
        completion(.init(date: Date()))
    }

    func getTimeline(
        in context: Context,
        completion: @escaping (Timeline<JARVISWatchExternalLaunchProbeEntry>) -> Void
    ) {
        completion(Timeline(entries: [.init(date: Date())], policy: .never))
    }
}

private struct JARVISWatchExternalLaunchProbeView: View {
    private static let shortcutsCustomURL = URL(string: "shortcuts://")!
    private static let shortcutsUniversalURL = URL(string: "https://www.icloud.com/shortcuts/")!
    private static let shortcutsTrampolineURL = URL(string: "jarvis://launch-shortcuts")!
    private static let spotifyCustomURL = URL(string: "spotify://")!
    private static let spotifyUniversalURL = URL(string: "https://open.spotify.com/")!
    private static let spotifyTrampolineURL = URL(string: "jarvis://launch-spotify")!

    var body: some View {
        VStack(spacing: 2) {
            probeRow(
                prefix: "S",
                customURL: Self.shortcutsCustomURL,
                universalURL: Self.shortcutsUniversalURL,
                trampolineURL: Self.shortcutsTrampolineURL,
                appName: "Shortcuts"
            )
            probeRow(
                prefix: "P",
                customURL: Self.spotifyCustomURL,
                universalURL: Self.spotifyUniversalURL,
                trampolineURL: Self.spotifyTrampolineURL,
                appName: "Spotify"
            )
        }
        .padding(2)
        .containerBackground(.black, for: .widget)
    }

    private func probeRow(
        prefix: String,
        customURL: URL,
        universalURL: URL,
        trampolineURL: URL,
        appName: String
    ) -> some View {
        HStack(spacing: 2) {
            Link(destination: customURL) {
                probeCell("\(prefix) URL")
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Open \(appName) using its custom URL")

            Link(destination: universalURL) {
                probeCell("\(prefix) WEB")
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Open \(appName) using its universal link")

            if #available(watchOS 11.0, *) {
                Button(intent: OpenURLIntent(universalURL)) {
                    probeCell("\(prefix) INT")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Open \(appName) using Open URL intent")
            } else {
                probeCell("\(prefix) INT")
                    .opacity(0.3)
                    .accessibilityHidden(true)
            }

            Link(destination: trampolineURL) {
                probeCell("\(prefix) JAR")
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Open \(appName) through JARVIS")
        }
        .frame(maxHeight: .infinity)
    }

    private func probeCell(_ label: String) -> some View {
        Text(label)
            .font(.system(size: 7, weight: .bold, design: .rounded))
            .minimumScaleFactor(0.7)
            .lineLimit(1)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background {
                RoundedRectangle(cornerRadius: 5, style: .continuous)
                    .fill(.white.opacity(0.13))
            }
            .contentShape(Rectangle())
    }
}

/// Temporary physical-only matrix. The final composite widget replaces this
/// after one Shortcuts route and one Spotify route are proven on the Watch.
struct JARVISWatchExternalLaunchProbeWidget: Widget {
    static let kind = "JARVISWatchExternalLaunchProbeWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: Self.kind, provider: JARVISWatchExternalLaunchProbeProvider()) { _ in
            JARVISWatchExternalLaunchProbeView()
        }
        .configurationDisplayName("JARVIS Link Probe")
        .description("Temporarily tests supported Watch launch routes for Shortcuts and Spotify.")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}
