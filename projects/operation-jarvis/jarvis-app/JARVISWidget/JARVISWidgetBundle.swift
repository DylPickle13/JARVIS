import SwiftUI
import WidgetKit

@main
struct JARVISWidgetBundle: WidgetBundle {
    var body: some Widget {
        JARVISNeuralCoreWidget()
        JARVISLauncherWidget()
        JARVISSelectedPlugWidget()
        JARVISPlugGridWidget()
        JARVISPurifierWidget()
    }
}
