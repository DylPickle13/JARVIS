import AppIntents
import SwiftUI
import WidgetKit
import JARVISKit

private struct WatchPlugGridItem: Identifiable {
    let id: String
    let name: String
    let isOn: Bool?
    let stale: Bool
}

private struct JARVISWatchPlugGridView: View {
    let entry: JARVISWatchStateEntry

    private var items: [WatchPlugGridItem] {
        if entry.placeholder {
            return [
                .init(id: "lamp", name: "Lamp", isOn: true, stale: false),
                .init(id: "tv", name: "TV", isOn: false, stale: false),
            ]
        }
        guard let cached = entry.cached,
              let subsystem = cached.state.subsystems?.plugs,
              subsystem.ok == true else { return [] }
        let subsystemStale = JARVISWidgetStateLoader.isStale(cached, subsystemStale: subsystem.stale == true)
        return (subsystem.plugs ?? [:]).keys.sorted().prefix(2).map { id in
            let state = subsystem.plugs?[id]
            return WatchPlugGridItem(
                id: id,
                name: JARVISWatchWidgetFormat.displayName(id),
                isOn: state?.isOn,
                stale: subsystemStale || state?.stale == true
            )
        }
    }

    var body: some View {
        Group {
            if items.isEmpty {
                Label {
                    VStack(alignment: .leading) {
                        Text("JARVIS Plugs").font(.headline)
                        Text("Status unavailable").font(.caption2).foregroundStyle(.secondary)
                    }
                } icon: {
                    Image(systemName: "powerplug")
                }
            } else {
                HStack(spacing: 6) {
                    ForEach(items) { item in
                        plugButton(item)
                    }
                }
            }
        }
        .widgetURL(jarvisWatchHomeURL)
        .jarvisWatchWidgetBackground()
        .accessibilityElement(children: .contain)
    }

    private func plugButton(_ item: WatchPlugGridItem) -> some View {
        let isOn = item.isOn == true
        let disabled = item.isOn == nil || item.stale
        return Button(intent: SetPlugIntent(plug: item.id, isOn: !isOn)) {
            VStack(spacing: 1) {
                Image(systemName: isOn ? "power.circle.fill" : "power.circle")
                    .font(.body)
                    .widgetAccentable()
                Text(item.name)
                    .font(.caption2.weight(.semibold))
                    .lineLimit(1)
                Text(item.stale ? "STALE" : (isOn ? "ON" : "OFF"))
                    .font(.caption2.bold())
                    .foregroundStyle(item.stale ? Color.orange : Color.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel("\(item.name), \(item.stale ? "stale" : (isOn ? "on" : "off"))")
        .accessibilityHint(disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
    }
}

struct JARVISWatchPlugGridWidget: Widget {
    let kind = "JARVISWatchPlugGridWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchStateProvider()) { entry in
            JARVISWatchPlugGridView(entry: entry)
        }
        .configurationDisplayName("JARVIS Plug Grid")
        .description("Control two plugs from a rectangular watch complication or Smart Stack widget.")
        .supportedFamilies([.accessoryRectangular])
    }
}
