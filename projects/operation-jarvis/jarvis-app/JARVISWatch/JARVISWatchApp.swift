import Foundation
import SwiftUI
import WidgetKit
import JARVISKit

private enum WatchLauncherWidgetReloadPolicy {
    private static let lastRequestedBuildKey = "jarvis.watch-launcher-widget.last-reload-build"

    static func reloadAfterUpgradeIfNeeded() {
        guard let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String,
              !build.isEmpty else {
            WidgetCenter.shared.reloadTimelines(ofKind: "JARVISWatchLauncherWidget.v2")
            return
        }
        let defaults = UserDefaults.standard
        guard defaults.string(forKey: lastRequestedBuildKey) != build else { return }
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISWatchLauncherWidget.v2")
        defaults.set(build, forKey: lastRequestedBuildKey)
    }
}

@main
struct JARVISWatchApp: App {
    init() {
        WatchBridge.shared.start()
        JARVISAppShortcuts.updateAppShortcutParameters()
        // The launcher has a static timeline. Request one reload for each newly
        // installed build without repeating identical WidgetKit work on every
        // same-build process launch.
        WatchLauncherWidgetReloadPolicy.reloadAfterUpgradeIfNeeded()
        // Rebuild the Watch Neural Core's system-owned timer selectors after a
        // host launch. WidgetKit still decides when to honor the reload.
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISWatchNeuralCoreWidget.v1")
    }

    var body: some Scene {
        WindowGroup {
            WatchConnectView()
        }
    }
}
