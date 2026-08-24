import SwiftUI
import WidgetKit
import JARVISKit

private struct JARVISNeuralCoreWidgetView: View {
    let entry: JARVISStateEntry

    private var telemetry: JARVISNeuralCoreTelemetry {
        JARVISNeuralCoreTelemetry(cached: entry.cached, placeholder: entry.placeholder, now: entry.date)
    }

    var body: some View {
        JARVISNeuralCoreContinuousArtwork(
            telemetry: telemetry,
            layout: .phone,
            basePhase: JARVISNeuralCoreMotion.phase(for: entry.date),
            allowsMotion: !entry.placeholder
        )
            .widgetURL(JARVISNeuralCoreWidget.homeURL)
            .containerBackground(for: .widget) {
                Color(red: 0.003, green: 0.005, blue: 0.007)
            }
    }
}

struct JARVISNeuralCoreWidget: Widget {
    static let homeURL = URL(string: "jarvis://home")!
    let kind = "JARVISNeuralCoreWidget.v1"

    init() {
        JARVISWidgetTimerAnimationFont.register()
    }

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISStateProvider()) { entry in
            JARVISNeuralCoreWidgetView(entry: entry)
        }
        .configurationDisplayName("JARVIS Neural Core")
        .description("An animated, state-reactive JARVIS projection. Tap to open JARVIS Home.")
        .supportedFamilies([.systemMedium])
        .contentMarginsDisabled()
    }
}
