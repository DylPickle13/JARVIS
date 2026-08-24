import SwiftUI
import WidgetKit
import JARVISKit

private struct JARVISNeuralCoreWidgetView: View {
    let entry: JARVISStateEntry

    private var telemetry: JARVISNeuralCoreTelemetry {
        JARVISNeuralCoreTelemetry(cached: entry.cached, placeholder: entry.placeholder, now: entry.date)
    }

    var body: some View {
        JARVISNeuralCoreArtwork(telemetry: telemetry, layout: .phone)
            .padding(.horizontal, 13)
            .padding(.vertical, 8)
            .widgetURL(JARVISNeuralCoreWidget.terminalURL)
            .containerBackground(for: .widget) {
                Color(red: 0.008, green: 0.018, blue: 0.024)
            }
    }
}

struct JARVISNeuralCoreWidget: Widget {
    static let terminalURL = URL(string: "jarvis://terminal")!
    let kind = "JARVISNeuralCoreWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISStateProvider()) { entry in
            JARVISNeuralCoreWidgetView(entry: entry)
        }
        .configurationDisplayName("JARVIS Neural Core")
        .description("A live, state-reactive JARVIS system link. Tap to open the Pi terminal.")
        .supportedFamilies([.systemMedium])
        .contentMarginsDisabled()
    }
}
