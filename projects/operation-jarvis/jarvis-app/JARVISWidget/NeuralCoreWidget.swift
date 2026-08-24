import SwiftUI
import WidgetKit
import JARVISKit

private struct JARVISNeuralCoreWidgetView: View {
    let entry: JARVISStateEntry

    private var telemetry: JARVISNeuralCoreTelemetry {
        JARVISNeuralCoreTelemetry(cached: entry.cached, placeholder: entry.placeholder, now: entry.date)
    }

    var body: some View {
        JARVISNeuralCoreArtwork(
            telemetry: telemetry,
            layout: .phone,
            motionPhase: JARVISNeuralCoreMotion.phase(for: entry.date),
            allowsMotion: !entry.placeholder
        )
            .padding(.horizontal, 13)
            .padding(.vertical, 8)
            .widgetURL(JARVISNeuralCoreWidget.homeURL)
            .containerBackground(for: .widget) {
                Color(red: 0.003, green: 0.005, blue: 0.007)
            }
    }
}

struct JARVISNeuralCoreWidget: Widget {
    static let homeURL = URL(string: "jarvis://home")!
    let kind = "JARVISNeuralCoreWidget.v1"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISStateProvider()) { entry in
            JARVISNeuralCoreWidgetView(entry: entry)
        }
        .configurationDisplayName("JARVIS Neural Core")
        .description("A native-vector, state-reactive JARVIS projection. Tap to open JARVIS Home.")
        .supportedFamilies([.systemMedium])
        .contentMarginsDisabled()
    }
}
