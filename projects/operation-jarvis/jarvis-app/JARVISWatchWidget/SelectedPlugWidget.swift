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
        let pending = JARVISWidgetControlStore.shared.pendingCommand(for: plug.id)
        let disabled = plug.isOn == nil || plug.stale || pending != nil
        let intent = SetPlugIntent(plug: plug.id, isOn: !isOn)
        let shortStatus = pending != nil ? "UPDATING" : (plug.stale ? "STALE" : (isOn ? "ON" : "OFF"))
        let status = pending != nil ? "Updating…" : (plug.stale ? "Status stale" : (isOn ? "On" : "Off"))
        let actionHint = pending != nil
            ? "A plug command is in progress"
            : (disabled ? "Control unavailable until status refreshes" : "Sets the plug \(isOn ? "off" : "on")")

        switch family {
        case .accessoryInline:
            Button(intent: intent) {
                Label("\(plug.name) · \(shortStatus)", systemImage: pending != nil ? "hourglass" : "power")
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("\(plug.name), \(pending != nil ? "updating" : (plug.stale ? "stale" : (isOn ? "on" : "off")))")
            .accessibilityHint(actionHint)
        case .accessoryCorner:
            Button(intent: intent) {
                Image(systemName: pending != nil ? "hourglass" : (isOn ? "power.circle.fill" : "power.circle"))
                    .font(.title3)
                    .widgetAccentable()
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .widgetLabel { Text(shortStatus) }
            .accessibilityLabel("\(plug.name), \(pending != nil ? "updating" : (plug.stale ? "stale" : (isOn ? "on" : "off")))")
            .accessibilityHint(actionHint)
        case .accessoryRectangular:
            Button(intent: intent) {
                HStack(spacing: 8) {
                    Image(systemName: pending != nil ? "hourglass" : (isOn ? "power.circle.fill" : "power.circle"))
                        .font(.title2)
                        .widgetAccentable()
                    VStack(alignment: .leading, spacing: 1) {
                        Text(plug.name).font(.headline).lineLimit(1)
                        Text(status)
                            .font(.caption2)
                            .foregroundStyle(pending != nil ? Color.blue : (plug.stale ? Color.orange : Color.secondary))
                    }
                    Spacer(minLength: 0)
                }
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("\(plug.name), \(pending != nil ? "updating" : (plug.stale ? "stale" : (isOn ? "on" : "off")))")
            .accessibilityHint(actionHint)
        default:
            Button(intent: intent) {
                ZStack {
                    AccessoryWidgetBackground()
                    VStack(spacing: 1) {
                        Image(systemName: pending != nil ? "hourglass" : (isOn ? "power.circle.fill" : "power.circle"))
                            .font(.title3)
                            .widgetAccentable()
                        Text(shortStatus)
                            .font(.caption2.bold())
                            .minimumScaleFactor(0.6)
                    }
                }
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("\(plug.name), \(pending != nil ? "updating" : (plug.stale ? "stale" : (isOn ? "on" : "off")))")
            .accessibilityHint(actionHint)
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
