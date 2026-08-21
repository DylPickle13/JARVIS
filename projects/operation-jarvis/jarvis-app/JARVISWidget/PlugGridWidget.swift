import AppIntents
import SwiftUI
import WidgetKit
import JARVISKit

private struct PlugGridItem: Identifiable {
    let id: String
    let name: String
    let isOn: Bool?
    let stale: Bool
}

private struct JARVISPlugGridView: View {
    let entry: JARVISStateEntry
    @Environment(\.widgetFamily) private var family

    private var maximumItems: Int { family == .systemLarge ? 8 : 4 }

    private var items: [PlugGridItem] {
        if entry.placeholder {
            return [
                .init(id: "family-room-light", name: "Family Room Light", isOn: false, stale: false),
                .init(id: "lamp", name: "Lamp", isOn: true, stale: false),
                .init(id: "pedalboard", name: "Pedalboard", isOn: false, stale: false),
                .init(id: "tv", name: "TV", isOn: false, stale: false),
            ]
        }
        guard let cached = entry.cached,
              let subsystem = cached.state.subsystems?.plugs,
              subsystem.ok == true else { return [] }
        let subsystemStale = JARVISWidgetStateLoader.isStale(cached, subsystemStale: subsystem.stale == true)
        return (subsystem.plugs ?? [:]).keys.sorted().prefix(maximumItems).map { id in
            let state = subsystem.plugs?[id]
            return PlugGridItem(
                id: id,
                name: JARVISWidgetFormat.displayName(id),
                isOn: state?.isOn,
                stale: subsystemStale || state?.stale == true
            )
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("JARVIS Plugs", systemImage: "powerplug.fill")
                    .font(.headline)
                Spacer()
                if !items.isEmpty {
                    Text("\(items.filter { $0.isOn == true }.count) on")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }

            if items.isEmpty {
                Spacer()
                Label("Plug status unavailable", systemImage: "wifi.slash")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer()
            } else {
                LazyVGrid(
                    columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 2),
                    spacing: 8
                ) {
                    ForEach(items) { item in
                        plugButton(item)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .widgetURL(jarvisHomeURL)
        .jarvisWidgetBackground()
        .accessibilityElement(children: .contain)
    }

    private func plugButton(_ item: PlugGridItem) -> some View {
        let isOn = item.isOn == true
        let disabled = item.isOn == nil || item.stale
        return Button(intent: SetPlugIntent(plug: item.id, isOn: !isOn)) {
            HStack(spacing: 7) {
                Image(systemName: isOn ? "power.circle.fill" : "power.circle")
                    .font(.title3)
                    .foregroundStyle(item.stale ? Color.orange : (isOn ? Color.green : Color.secondary))
                VStack(alignment: .leading, spacing: 1) {
                    Text(item.name)
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                    Text(item.stale ? "STALE" : (isOn ? "ON" : "OFF"))
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(item.stale ? Color.orange : Color.secondary)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 9)
            .frame(maxWidth: .infinity, minHeight: family == .systemLarge ? 48 : 42, alignment: .leading)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel("\(item.name), \(item.stale ? "stale" : (isOn ? "on" : "off"))")
        .accessibilityHint(disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
    }
}

struct JARVISPlugGridWidget: Widget {
    let kind = "JARVISPlugGridWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISStateProvider()) { entry in
            JARVISPlugGridView(entry: entry)
        }
        .configurationDisplayName("JARVIS Plug Grid")
        .description("Control up to four plugs in medium or eight plugs in large.")
        .supportedFamilies([.systemMedium, .systemLarge])
    }
}
