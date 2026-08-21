import SwiftUI
import WidgetKit

@main
struct JARVISWidgetBundle: WidgetBundle {
    var body: some Widget {
        JARVISLauncherWidget()
        JARVISSelectedPlugWidget()
        JARVISPlugGridWidget()
        JARVISPurifierWidget()
    }
}
