import AppIntents
import SwiftUI
import WidgetKit
import JARVISKit

private struct WatchPlugPresentation {
    let id: String
    let name: String
    let isOn: Bool?
    let stale: Bool
}

private struct JARVISWatchSelectedPlugView: View {
    let entry: JARVISWatchSelectedPlugEntry
    @Environment(\.widgetFamily) private var family

    private var plug: WatchPlugPresentation? {
        if entry.placeholder {
            return WatchPlugPresentation(id: "lamp", name: "Lamp", isOn: true, stale: false)
        }
        let names = JARVISWidgetStateLoader.plugNames(from: entry.cached)
        guard let subsystem = entry.cached?.state.subsystems?.plugs,
              subsystem.ok == true else { return nil }
        let configured = entry.plugID.flatMap { subsystem.plugs?[$0] == nil ? nil : $0 }
        guard let id = configured ?? names.first,
              let state = subsystem.plugs?[id] else { return nil }
        return WatchPlugPresentation(
            id: id,
            name: JARVISWatchWidgetFormat.displayName(id),
            isOn: state.isOn,
            stale: JARVISWidgetStateLoader.isStale(
                entry.cached,
                subsystemStale: subsystem.stale == true,
                itemStale: state.stale == true
            )
        )
    }

    var body: some View {
        Group {
            if let plug {
                plugContent(plug)
            } else {
                unavailableContent
            }
        }
        .widgetURL(jarvisWatchHomeURL)
        .jarvisWatchWidgetBackground()
    }

    @ViewBuilder
    private func plugContent(_ plug: WatchPlugPresentation) -> some View {
        let isOn = plug.isOn == true
        let disabled = plug.isOn == nil || plug.stale
        let intent = SetPlugIntent(plug: plug.id, isOn: !isOn)

        switch family {
        case .accessoryInline:
            Button(intent: intent) {
                Label("\(plug.name) · \(plug.stale ? "STALE" : (isOn ? "ON" : "OFF"))", systemImage: "power")
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("\(plug.name), \(plug.stale ? "stale" : (isOn ? "on" : "off"))")
            .accessibilityHint(disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
        case .accessoryCorner:
            Button(intent: intent) {
                Image(systemName: isOn ? "power.circle.fill" : "power.circle")
                    .font(.title3)
                    .widgetAccentable()
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .widgetLabel {
                Text(plug.stale ? "STALE" : (isOn ? "ON" : "OFF"))
            }
            .accessibilityLabel("\(plug.name), \(plug.stale ? "stale" : (isOn ? "on" : "off"))")
            .accessibilityHint(disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
        case .accessoryRectangular:
            Button(intent: intent) {
                HStack(spacing: 8) {
                    Image(systemName: isOn ? "power.circle.fill" : "power.circle")
                        .font(.title2)
                        .widgetAccentable()
                    VStack(alignment: .leading, spacing: 1) {
                        Text(plug.name).font(.headline).lineLimit(1)
                        Text(plug.stale ? "Status stale" : (isOn ? "On" : "Off"))
                            .font(.caption2)
                            .foregroundStyle(plug.stale ? Color.orange : Color.secondary)
                    }
                    Spacer(minLength: 0)
                }
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("\(plug.name), \(plug.stale ? "stale" : (isOn ? "on" : "off"))")
            .accessibilityHint(disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
        default:
            Button(intent: intent) {
                ZStack {
                    AccessoryWidgetBackground()
                    VStack(spacing: 1) {
                        Image(systemName: isOn ? "power.circle.fill" : "power.circle")
                            .font(.title3)
                            .widgetAccentable()
                        Text(plug.stale ? "STALE" : (isOn ? "ON" : "OFF"))
                            .font(.caption2.bold())
                    }
                }
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("\(plug.name), \(plug.stale ? "stale" : (isOn ? "on" : "off"))")
            .accessibilityHint(disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
        }
    }

    @ViewBuilder
    private var unavailableContent: some View {
        switch family {
        case .accessoryInline:
            Label("JARVIS plug unavailable", systemImage: "powerplug")
        case .accessoryCorner:
            Image(systemName: "powerplug")
                .widgetLabel { Text("Unavailable") }
        case .accessoryRectangular:
            Label {
                VStack(alignment: .leading) {
                    Text("JARVIS Plug").font(.headline)
                    Text("Choose or refresh a plug").font(.caption2).foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "powerplug")
            }
        default:
            ZStack {
                AccessoryWidgetBackground()
                Image(systemName: "powerplug").font(.title3)
            }
        }
    }
}

struct JARVISWatchSelectedPlugWidget: Widget {
    let kind = "JARVISWatchSelectedPlugWidget.v1"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: kind,
            intent: SelectJARVISPlugIntent.self,
            provider: JARVISWatchSelectedPlugProvider()
        ) { entry in
            JARVISWatchSelectedPlugView(entry: entry)
        }
        .configurationDisplayName("JARVIS Plug")
        .description("Choose one plug for explicit on and off control from Apple Watch.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}
