import SwiftUI
import WidgetKit
import JARVISKit

private struct JARVISWatchNeuralCoreWidgetView: View {
    let entry: JARVISWatchStateEntry

    private var telemetry: JARVISNeuralCoreTelemetry {
        JARVISNeuralCoreTelemetry(cached: entry.cached, placeholder: entry.placeholder, now: entry.date)
    }

    var body: some View {
        JARVISNeuralCoreArtwork(telemetry: telemetry, layout: .watch)
            .padding(.horizontal, 2)
            .widgetURL(JARVISWatchNeuralCoreWidget.terminalURL)
            .containerBackground(for: .widget) {
                Color.clear
            }
    }
}

struct JARVISWatchNeuralCoreWidget: Widget {
    static let terminalURL = URL(string: "jarvis://terminal")!
    let kind = "JARVISWatchNeuralCoreWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchStateProvider()) { entry in
            JARVISWatchNeuralCoreWidgetView(entry: entry)
        }
        .configurationDisplayName("JARVIS Neural Core")
        .description("A transparent Modular complication driven by cached JARVIS state.")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}
