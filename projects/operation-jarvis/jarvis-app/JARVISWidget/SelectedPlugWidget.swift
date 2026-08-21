import AppIntents
import SwiftUI
import WidgetKit
import JARVISKit

private struct PlugPresentation {
    let id: String
    let name: String
    let isOn: Bool?
    let stale: Bool
}

private struct JARVISSelectedPlugView: View {
    let entry: JARVISSelectedPlugEntry
    @Environment(\.widgetFamily) private var family

    private var plug: PlugPresentation? {
        if entry.placeholder {
            return PlugPresentation(id: "lamp", name: "Lamp", isOn: true, stale: false)
        }
        let names = JARVISWidgetStateLoader.plugNames(from: entry.cached)
        guard let subsystem = entry.cached?.state.subsystems?.plugs,
              subsystem.ok == true else { return nil }
        let configured = entry.plugID.flatMap { subsystem.plugs?[$0] == nil ? nil : $0 }
        guard let id = configured ?? names.first,
              let state = subsystem.plugs?[id] else { return nil }
        return PlugPresentation(
            id: id,
            name: JARVISWidgetFormat.displayName(id),
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
        .widgetURL(jarvisHomeURL)
        .jarvisWidgetBackground()
    }

    @ViewBuilder
    private func plugContent(_ plug: PlugPresentation) -> some View {
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
        case .accessoryCircular:
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
        case .accessoryRectangular:
            Button(intent: intent) {
                HStack(spacing: 8) {
                    Image(systemName: isOn ? "power.circle.fill" : "power.circle")
                        .font(.title2)
                        .widgetAccentable()
                    VStack(alignment: .leading, spacing: 1) {
                        Text(plug.name).font(.headline).lineLimit(1)
                        Text(plug.stale ? "Status stale" : (isOn ? "On" : "Off"))
                            .font(.caption)
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
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("JARVIS", systemImage: "powerplug.fill")
                        .font(.caption.weight(.semibold))
                    Spacer()
                    Circle()
                        .fill(plug.stale ? Color.orange : (isOn ? Color.green : Color.secondary))
                        .frame(width: 9, height: 9)
                }
                Spacer(minLength: 0)
                Image(systemName: isOn ? "power.circle.fill" : "power.circle")
                    .font(.system(size: 34, weight: .medium))
                    .foregroundStyle(plug.stale ? Color.orange : (isOn ? Color.green : Color.secondary))
                Text(plug.name)
                    .font(.headline)
                    .lineLimit(2)
                Button(intent: intent) {
                    Text(plug.stale ? "Status stale" : (isOn ? "Turn Off" : "Turn On"))
                        .font(.caption.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.bordered)
                .disabled(disabled)
                .accessibilityHint(disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")
            }
            .accessibilityElement(children: .contain)
        }
    }

    @ViewBuilder
    private var unavailableContent: some View {
        switch family {
        case .accessoryInline:
            Label("JARVIS plug unavailable", systemImage: "powerplug")
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                Image(systemName: "powerplug").font(.title3)
            }
        case .accessoryRectangular:
            Label {
                VStack(alignment: .leading) {
                    Text("JARVIS Plug").font(.headline)
                    Text("Choose or refresh a plug").font(.caption).foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "powerplug")
            }
        default:
            VStack(alignment: .leading, spacing: 8) {
                Label("JARVIS", systemImage: "powerplug.fill").font(.caption.weight(.semibold))
                Spacer()
                Image(systemName: "wifi.slash").font(.title2).foregroundStyle(.secondary)
                Text("Choose or refresh a plug").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct JARVISSelectedPlugWidget: Widget {
    let kind = "JARVISSelectedPlugWidget.v1"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: kind, intent: SelectJARVISPlugIntent.self, provider: JARVISSelectedPlugProvider()) { entry in
            JARVISSelectedPlugView(entry: entry)
        }
        .configurationDisplayName("JARVIS Plug")
        .description("Choose one plug for fast, explicit on and off control.")
        .supportedFamilies([.systemSmall, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}
