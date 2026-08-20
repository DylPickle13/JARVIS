import SwiftUI
import WidgetKit
import JARVISKit

struct JARVISPlugEntry: TimelineEntry {
    let date: Date
    let cached: CachedState?
}

struct JARVISPlugProvider: TimelineProvider {
    private let store = SnapshotStore()

    func placeholder(in context: Context) -> JARVISPlugEntry {
        JARVISPlugEntry(date: Date(), cached: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (JARVISPlugEntry) -> Void) {
        completion(JARVISPlugEntry(date: Date(), cached: store.load()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<JARVISPlugEntry>) -> Void) {
        let now = Date()
        let cached = store.load()
        Task {
            let refreshed = await Self.fetchLatestState()
            if let refreshed { store.save(refreshed) }
            let entry = JARVISPlugEntry(date: now, cached: refreshed.map { CachedState(state: $0) } ?? cached)
            completion(Timeline(entries: [entry], policy: .after(now.addingTimeInterval(300))))
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

struct JARVISPlugWidgetView: View {
    let entry: JARVISPlugEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let cached = entry.cached,
           let subsystem = cached.state.subsystems?.plugs,
           subsystem.ok == true {
            let cacheStale = Date().timeIntervalSince(cached.savedAt) > 900
            plugsView(subsystem, stale: subsystem.stale == true || cached.state.stale == true || cacheStale)
        } else {
            unavailableView
        }
    }

    private func plugsView(_ subsystem: PlugsSubsystem, stale: Bool) -> some View {
        let plugs = (subsystem.plugs ?? [:]).keys.sorted()
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Label("JARVIS", systemImage: "powerplug.fill")
                    .font(.caption.weight(.semibold))
                Spacer()
                if stale { Image(systemName: "clock.badge.exclamationmark").font(.caption) }
            }
            if plugs.isEmpty {
                Text("No plugs configured").font(.caption).foregroundStyle(.secondary)
            } else {
                let columns = family == .systemSmall ? 2 : 2
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: columns), spacing: 6) {
                    ForEach(plugs.prefix(family == .systemSmall ? 2 : 4), id: \.self) { name in
                        plugButton(name: name, state: subsystem.plugs?[name], stale: stale)
                    }
                }
            }
            if stale { Text("Stale").font(.caption2).foregroundStyle(.orange) }
        }
        .containerBackground(.fill.tertiary, for: .widget)
    }

    private func plugButton(name: String, state: PlugState?, stale: Bool) -> some View {
        let isOn = state?.isOn
        return Button(intent: SetPlugIntent(plug: name, isOn: !(isOn ?? false))) {
            HStack(spacing: 4) {
                Image(systemName: "power")
                    .font(.caption2)
                    .foregroundStyle(isOn == true ? .green : .secondary)
                Text(JARVISWidgetFormat.displayName(name))
                    .font(.caption2)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, minHeight: 28)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(isOn == nil || stale)
    }

    private var unavailableView: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("JARVIS", systemImage: "powerplug.fill").font(.caption.weight(.semibold))
            Image(systemName: "wifi.slash").font(.title2).foregroundStyle(.secondary)
            Text("Plug status unavailable").font(.caption).foregroundStyle(.secondary)
        }
        .containerBackground(.fill.tertiary, for: .widget)
    }
}

struct JARVISPlugWidget: Widget {
    let kind = "JARVISPlugWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISPlugProvider()) { entry in
            JARVISPlugWidgetView(entry: entry)
        }
        .configurationDisplayName("JARVIS Plugs")
        .description("Control the approved JARVIS plug grid.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular])
    }
}

@main
struct JARVISWidgetBundle: WidgetBundle {
    var body: some Widget {
        JARVISPlugWidget()
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
}
