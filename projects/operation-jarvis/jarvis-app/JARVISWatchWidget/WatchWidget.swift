import SwiftUI
import WidgetKit
import JARVISKit

struct JARVISWatchEntry: TimelineEntry {
    let date: Date
    let cached: CachedState?
}

struct JARVISWatchProvider: TimelineProvider {
    private let store = SnapshotStore()

    func placeholder(in context: Context) -> JARVISWatchEntry {
        JARVISWatchEntry(date: Date(), cached: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (JARVISWatchEntry) -> Void) {
        completion(JARVISWatchEntry(date: Date(), cached: store.load()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<JARVISWatchEntry>) -> Void) {
        let date = Date()
        let cached = store.load()
        Task {
            let refreshed = await Self.fetchLatestState()
            if let refreshed { store.save(refreshed) }
            let entry = JARVISWatchEntry(date: date, cached: refreshed.map { CachedState(state: $0) } ?? cached)
            completion(Timeline(entries: [entry], policy: .after(date.addingTimeInterval(300))))
        }
    }

    private static func fetchLatestState() async -> StateSnapshot? {
        let store = EndpointStore(defaults: JARVISSharedStore.defaults)
        let client = JarvisClient()
        let endpointURL: URL?
        if let saved = store.endpointURL {
            endpointURL = saved
        } else {
            endpointURL = await client.discover(JarvisEndpoints.candidates(override: nil), timeout: 2)
        }
        guard let endpointURL else { return nil }
        do {
            return try await client.state(JarvisEndpoint(baseURL: endpointURL, token: store.token ?? ""))
        } catch {
            return nil
        }
    }
}

struct JARVISWatchWidgetView: View {
    let entry: JARVISWatchEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let cached = entry.cached,
           let subsystem = cached.state.subsystems?.plugs,
           subsystem.ok == true,
           let first = (subsystem.plugs ?? [:]).keys.sorted().first,
           let plug = subsystem.plugs?[first],
           let isOn = plug.isOn {
            let stale = cached.state.stale == true || subsystem.stale == true || plug.stale == true || Date().timeIntervalSince(cached.savedAt) > 900
            Button(intent: SetPlugIntent(plug: first, isOn: !isOn)) {
                VStack(spacing: 2) {
                    Image(systemName: "power")
                        .font(.title3)
                        .foregroundStyle(isOn ? .green : .secondary)
                    Text(JARVISWatchFormat.displayName(first))
                        .font(.caption2)
                        .lineLimit(1)
                    Text(isOn ? "ON" : "OFF")
                        .font(.caption2.weight(.semibold))
                    if stale {
                        Text("STALE")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundStyle(.orange)
                    }
                }
            }
            .buttonStyle(.plain)
            .disabled(stale)
            .containerBackground(.fill.tertiary, for: .widget)
        } else {
            VStack(spacing: 3) {
                Image(systemName: "powerplug").foregroundStyle(.secondary)
                Text("JARVIS").font(.caption2.weight(.semibold))
                Text("Unavailable").font(.caption2).foregroundStyle(.secondary)
            }
            .containerBackground(.fill.tertiary, for: .widget)
        }
    }
}

struct JARVISWatchWidget: Widget {
    let kind = "JARVISWatchWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchProvider()) { entry in
            JARVISWatchWidgetView(entry: entry)
        }
        .configurationDisplayName("JARVIS First Plug")
        .description("Control the first configured JARVIS plug.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct JARVISWatchWidgetBundle: WidgetBundle {
    var body: some Widget {
        JARVISWatchWidget()
    }
}

enum JARVISWatchFormat {
    static func displayName(_ raw: String) -> String {
        raw.replacingOccurrences(of: "-", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }
}
