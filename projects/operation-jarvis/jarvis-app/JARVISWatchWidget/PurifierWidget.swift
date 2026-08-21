import SwiftUI
import WidgetKit
import JARVISKit

private struct WatchPurifierPresentation {
    let pm25: Int?
    let isOn: Bool?
    let mode: String?
    let fan: Int?
    let stale: Bool

    var status: String {
        guard let isOn else { return "Unknown" }
        guard isOn else { return "Off" }
        let modeName = (mode ?? "On").capitalized
        if let fan { return "\(modeName) · Fan \(fan)" }
        return modeName
    }
}

private struct JARVISWatchPurifierView: View {
    let entry: JARVISWatchStateEntry
    @Environment(\.widgetFamily) private var family

    private var purifier: WatchPurifierPresentation? {
        if entry.placeholder {
            return WatchPurifierPresentation(pm25: 3, isOn: false, mode: "auto", fan: 2, stale: false)
        }
        guard let cached = entry.cached,
              let subsystem = cached.state.subsystems?.purifier,
              subsystem.ok == true else { return nil }
        return WatchPurifierPresentation(
            pm25: subsystem.pm25,
            isOn: subsystem.isOn,
            mode: subsystem.mode,
            fan: subsystem.fanSetLevel ?? subsystem.fanLevel,
            stale: JARVISWidgetStateLoader.isStale(cached, subsystemStale: subsystem.stale == true)
        )
    }

    var body: some View {
        Group {
            if let purifier {
                purifierContent(purifier)
            } else {
                unavailableContent
            }
        }
        .widgetURL(jarvisWatchHomeURL)
        .jarvisWatchWidgetBackground()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(purifierAccessibilityLabel)
    }

    private var purifierAccessibilityLabel: String {
        guard let purifier else { return "Air purifier status unavailable" }
        let reading = purifier.pm25.map(String.init) ?? "unknown"
        let quality = JARVISWatchWidgetFormat.purifierQuality(pm25: purifier.pm25).label
        return "Air purifier, PM2.5 \(reading), \(purifier.stale ? "status stale" : quality), \(purifier.status)"
    }

    @ViewBuilder
    private func purifierContent(_ purifier: WatchPurifierPresentation) -> some View {
        let quality = JARVISWatchWidgetFormat.purifierQuality(pm25: purifier.pm25)
        let reading = purifier.pm25.map(String.init) ?? "—"
        switch family {
        case .accessoryInline:
            Label("Air \(reading) µg/m³ · \(purifier.stale ? "STALE" : quality.label)", systemImage: "wind")
        case .accessoryCorner:
            Text(reading)
                .font(.title3.bold().monospacedDigit())
                .widgetAccentable()
                .widgetLabel {
                    Text(purifier.stale ? "STALE" : "PM2.5")
                }
        case .accessoryRectangular:
            HStack(spacing: 8) {
                Image(systemName: "wind")
                    .font(.title2)
                    .widgetAccentable()
                VStack(alignment: .leading, spacing: 1) {
                    Text("\(reading) µg/m³")
                        .font(.headline.monospacedDigit())
                    Text(purifier.stale ? "Status stale" : "\(quality.label) · \(purifier.status)")
                        .font(.caption2)
                        .foregroundStyle(purifier.stale ? Color.orange : Color.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
        default:
            ZStack {
                AccessoryWidgetBackground()
                VStack(spacing: 0) {
                    Image(systemName: "wind")
                        .font(.caption2)
                        .widgetAccentable()
                    Text(reading)
                        .font(.headline.monospacedDigit())
                        .minimumScaleFactor(0.7)
                    Text(purifier.stale ? "STALE" : "PM2.5")
                        .font(.caption2.weight(.semibold))
                }
            }
        }
    }

    @ViewBuilder
    private var unavailableContent: some View {
        switch family {
        case .accessoryInline:
            Label("Air purifier unavailable", systemImage: "wind")
        case .accessoryCorner:
            Image(systemName: "wind")
                .widgetLabel { Text("Unavailable") }
        case .accessoryRectangular:
            Label {
                VStack(alignment: .leading) {
                    Text("Air Purifier").font(.headline)
                    Text("Status unavailable").font(.caption2).foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "wind")
            }
        default:
            ZStack {
                AccessoryWidgetBackground()
                Image(systemName: "wind").font(.title3)
            }
        }
    }
}

struct JARVISWatchPurifierWidget: Widget {
    let kind = "JARVISWatchPurifierWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchStateProvider()) { entry in
            JARVISWatchPurifierView(entry: entry)
        }
        .configurationDisplayName("Air Purifier")
        .description("View PM2.5, air quality, power, mode, and stale status from Apple Watch.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}
