import SwiftUI
import WidgetKit
import JARVISKit

@main
struct JARVISWatchApp: App {
    init() {
        WatchBridge.shared.start()
        JARVISAppShortcuts.updateAppShortcutParameters()
        // The launcher has a static timeline. Reload it on host launch so an
        // upgraded asset cannot remain stuck behind an older cached rendering.
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISWatchLauncherWidget.v2")
    }

    var body: some Scene {
        WindowGroup {
            WatchConnectView()
        }
    }
}
