import SwiftUI
import WidgetKit
import JARVISKit

private struct PurifierPresentation {
    let pm25: Int?
    let isOn: Bool?
    let mode: String?
    let fan: Int?
    let filterLife: Int?
    let stale: Bool

    var status: String {
        guard let isOn else { return "Status unavailable" }
        guard isOn else { return "Off" }
        let modeName = (mode ?? "On").capitalized
        if let fan { return "\(modeName) · Fan \(fan)" }
        return modeName
    }
}

private struct JARVISPurifierView: View {
    let entry: JARVISStateEntry
    @Environment(\.widgetFamily) private var family

    private var purifier: PurifierPresentation? {
        if entry.placeholder {
            return PurifierPresentation(pm25: 3, isOn: false, mode: "auto", fan: 2, filterLife: 88, stale: false)
        }
        guard let cached = entry.cached,
              let subsystem = cached.state.subsystems?.purifier,
              subsystem.ok == true else { return nil }
        return PurifierPresentation(
            pm25: subsystem.pm25,
            isOn: subsystem.isOn,
            mode: subsystem.mode,
            fan: subsystem.fanSetLevel ?? subsystem.fanLevel,
            filterLife: subsystem.filterLife,
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
        .widgetURL(jarvisHomeURL)
        .jarvisWidgetBackground()
    }

    @ViewBuilder
    private func purifierContent(_ purifier: PurifierPresentation) -> some View {
        let quality = JARVISWidgetFormat.purifierQuality(pm25: purifier.pm25)
        let reading = purifier.pm25.map(String.init) ?? "—"
        switch family {
        case .accessoryInline:
            Label("Air \(reading) µg/m³ · \(purifier.stale ? "STALE" : quality.label)", systemImage: "wind")
        case .accessoryCircular:
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
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Air purifier, PM2.5 \(reading), \(purifier.stale ? "status stale" : quality.label)")
        case .accessoryRectangular:
            HStack(spacing: 9) {
                Image(systemName: "wind")
                    .font(.title2)
                    .widgetAccentable()
                VStack(alignment: .leading, spacing: 1) {
                    Text("\(reading) µg/m³")
                        .font(.headline.monospacedDigit())
                    Text(purifier.stale ? "Status stale" : "\(quality.label) · \(purifier.status)")
                        .font(.caption)
                        .foregroundStyle(purifier.stale ? Color.orange : Color.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Air purifier, PM2.5 \(reading), \(purifier.stale ? "status stale" : quality.label), \(purifier.status)")
        case .systemMedium:
            HStack(spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Label("Air Purifier", systemImage: "wind")
                        .font(.headline)
                    Spacer(minLength: 0)
                    Text(reading)
                        .font(.system(size: 42, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                    Text("PM2.5 µg/m³")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    Label(quality.label, systemImage: "aqi.medium")
                        .foregroundStyle(purifier.stale ? Color.orange : quality.color)
                    LabeledContent("Power", value: purifier.isOn == true ? "On" : (purifier.isOn == false ? "Off" : "—"))
                    LabeledContent("Mode", value: purifier.mode?.capitalized ?? "—")
                    if let filter = purifier.filterLife {
                        LabeledContent("Filter", value: "\(filter)%")
                    }
                    if purifier.stale {
                        Label("Status stale", systemImage: "clock.badge.exclamationmark")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
                .font(.caption)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Air purifier, PM2.5 \(reading), \(purifier.stale ? "status stale" : quality.label), \(purifier.status)")
        default:
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Label("Air Purifier", systemImage: "wind")
                        .font(.caption.weight(.semibold))
                    Spacer()
                    Circle()
                        .fill(purifier.stale ? Color.orange : quality.color)
                        .frame(width: 9, height: 9)
                }
                Spacer(minLength: 0)
                Text(reading)
                    .font(.system(size: 38, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                Text("PM2.5 µg/m³")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(purifier.stale ? "Status stale" : "\(quality.label) · \(purifier.status)")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(purifier.stale ? Color.orange : Color.secondary)
                    .lineLimit(1)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Air purifier, PM2.5 \(reading), \(purifier.stale ? "status stale" : quality.label), \(purifier.status)")
        }
    }

    @ViewBuilder
    private var unavailableContent: some View {
        switch family {
        case .accessoryInline:
            Label("Air purifier unavailable", systemImage: "wind")
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                Image(systemName: "wind").font(.title3)
            }
        case .accessoryRectangular:
            Label {
                VStack(alignment: .leading) {
                    Text("Air Purifier").font(.headline)
                    Text("Status unavailable").font(.caption).foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "wind")
            }
        default:
            VStack(alignment: .leading, spacing: 8) {
                Label("Air Purifier", systemImage: "wind").font(.headline)
                Spacer()
                Image(systemName: "wifi.slash").font(.title2).foregroundStyle(.secondary)
                Text("Status unavailable").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct JARVISPurifierWidget: Widget {
    let kind = "JARVISPurifierWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISStateProvider()) { entry in
            JARVISPurifierView(entry: entry)
        }
        .configurationDisplayName("Air Purifier")
        .description("View PM2.5, air quality, power, mode, and filter status.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}
