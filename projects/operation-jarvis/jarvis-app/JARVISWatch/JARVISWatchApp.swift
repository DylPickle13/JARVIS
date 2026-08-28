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
        // Rebuild the Watch Neural Core's system-owned timer selectors after a
        // host launch. WidgetKit still decides when to honor the reload.
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISWatchNeuralCoreWidget.v1")
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISWatchExternalLaunchProbeWidget.v1")
    }

    var body: some Scene {
        WindowGroup {
            WatchConnectView()
        }
    }
}
