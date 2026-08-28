import SwiftUI
import WidgetKit

@main
struct JARVISWatchWidgetBundle: WidgetBundle {
    var body: some Widget {
        JARVISWatchNeuralCoreWidget()
        JARVISWatchLauncherWidget()
        JARVISWatchSelectedPlugWidget()
        JARVISWatchPlugGridWidget()
        JARVISWatchPurifierWidget()
        JARVISWatchNeuralLauncherWidget()
    }
}
