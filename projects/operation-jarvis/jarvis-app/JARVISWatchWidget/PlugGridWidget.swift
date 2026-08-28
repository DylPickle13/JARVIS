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

    private let columns = [
        GridItem(.flexible(), spacing: 4),
        GridItem(.flexible(), spacing: 4),
    ]

    private var items: [WatchPlugGridItem] {
        if entry.placeholder {
            return [
                .init(id: "family-room-light", name: "Family Light", isOn: false, stale: false),
                .init(id: "lamp", name: "Lamp", isOn: true, stale: false),
                .init(id: "pedalboard", name: "Pedalboard", isOn: false, stale: false),
                .init(id: "tv", name: "TV", isOn: false, stale: false),
            ]
        }
        guard let cached = entry.cached,
              let subsystem = cached.state.subsystems?.plugs,
              subsystem.ok == true else { return [] }
        let subsystemStale = JARVISWidgetStateLoader.isStale(cached, subsystemStale: subsystem.stale == true)
        return JARVISPlugChoice.allCases.compactMap { choice in
            let id = choice.rawValue
            guard let state = subsystem.plugs?[id] else { return nil }
            return WatchPlugGridItem(
                id: id,
                name: gridName(id),
                isOn: state.isOn,
                stale: subsystemStale || state.stale == true
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
                LazyVGrid(columns: columns, spacing: 4) {
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
        let pending = JARVISWidgetControlStore.shared.pendingCommand(for: item.id)
        let disabled = item.isOn == nil || item.stale || pending != nil
        let status = pending != nil ? "UPDATING" : (item.stale ? "STALE" : (isOn ? "ON" : "OFF"))
        let color = pending != nil ? JARVISWidgetTheme.accent : (item.stale ? Color.orange : (isOn ? Color.green : Color.secondary))
        return Button(intent: SetPlugIntent(plug: item.id, isOn: !isOn)) {
            HStack(spacing: 4) {
                Image(systemName: pending != nil ? "hourglass" : (isOn ? "power.circle.fill" : "power.circle"))
                    .font(.caption)
                    .foregroundStyle(color)
                    .widgetAccentable()
                VStack(alignment: .leading, spacing: 0) {
                    Text(item.name)
                        .font(.system(size: 9, weight: .semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                    Text(status)
                        .font(.system(size: 8, weight: .bold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                        .foregroundStyle(pending != nil || item.stale ? color : Color.secondary)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 4)
            .frame(maxWidth: .infinity, minHeight: 31, alignment: .leading)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel("\(item.name), \(pending != nil ? "updating" : (item.stale ? "stale" : (isOn ? "on" : "off")))")
        .accessibilityHint(
            pending != nil
                ? "A plug command is in progress"
                : (disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
        )
    }

    private func gridName(_ id: String) -> String {
        id == "family-room-light" ? "Family Light" : JARVISWatchWidgetFormat.displayName(id)
    }
}

struct JARVISWatchPlugGridWidget: Widget {
    let kind = "JARVISWatchPlugGridWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchStateProvider()) { entry in
            JARVISWatchPlugGridView(entry: entry)
        }
        .configurationDisplayName("JARVIS Plug Grid")
        .description("Control all four approved plugs from a rectangular Watch widget.")
        .supportedFamilies([.accessoryRectangular])
    }
}
