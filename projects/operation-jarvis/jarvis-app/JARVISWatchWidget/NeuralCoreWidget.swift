import SwiftUI
import WidgetKit
import JARVISKit

private struct JARVISWatchNeuralCoreWidgetView: View {
    let entry: JARVISWatchStateEntry

    private var telemetry: JARVISNeuralCoreTelemetry {
        JARVISNeuralCoreTelemetry(cached: entry.cached, placeholder: entry.placeholder, now: entry.date)
    }

    var body: some View {
        JARVISNeuralCoreContinuousArtwork(
            telemetry: telemetry,
            layout: .watch,
            basePhase: JARVISNeuralCoreMotion.phase(for: entry.date),
            allowsMotion: !entry.placeholder,
            selectorGeneration: entry.date.timeIntervalSinceReferenceDate
        )
            // A genuine WidgetKit timeline replacement receives a new identity,
            // rebuilding timer selectors that the system previously suspended.
            .id(entry.date.timeIntervalSinceReferenceDate)
            .widgetURL(JARVISWatchNeuralCoreWidget.terminalURL)
            .containerBackground(for: .widget) {
                Color.clear
            }
    }
}

struct JARVISWatchNeuralCoreWidget: Widget {
    static let terminalURL = URL(string: "jarvis://terminal")!
    let kind = "JARVISWatchNeuralCoreWidget.v1"

    init() {
        JARVISWidgetTimerAnimationFont.register()
    }

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: JARVISWatchStateProvider()) { entry in
            JARVISWatchNeuralCoreWidgetView(entry: entry)
        }
        .configurationDisplayName("JARVIS Neural Core")
        .description("A transparent animated Cathedral driven by cached JARVIS state.")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}
