import SwiftUI
import WidgetKit

@main
struct JARVISWatchWidgetBundle: WidgetBundle {
    var body: some Widget {
        JARVISWatchLauncherWidget()
        JARVISWatchSelectedPlugWidget()
        JARVISWatchPlugGridWidget()
        JARVISWatchPurifierWidget()
    }
}
