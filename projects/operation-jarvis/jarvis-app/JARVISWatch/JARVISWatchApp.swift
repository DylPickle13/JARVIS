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

private enum WatchNeuralCoreWidgetReloadCoordinator {
    private static let lastRequestedAtKey = "jarvis.watch-neural-core-widget.last-reload-request-at"

    static func reloadIfDue(
        now: Date = Date(),
        defaults: UserDefaults = .standard
    ) {
        let lastRequestedAt = defaults.object(forKey: lastRequestedAtKey) as? Date
        guard JARVISNeuralCoreWidgetReloadPolicy.shouldRequestReload(
            lastRequestedAt: lastRequestedAt,
            now: now
        ) else { return }

        defaults.set(now, forKey: lastRequestedAtKey)
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISWatchNeuralCoreWidget.v1")
    }
}

@main
struct JARVISWatchApp: App {
    @Environment(\.scenePhase) private var scenePhase

    init() {
        WatchBridge.shared.start()
        JARVISAppShortcuts.updateAppShortcutParameters()
        // The launcher has a static timeline. Request one reload for each newly
        // installed build without repeating identical WidgetKit work on every
        // same-build process launch.
        WatchLauncherWidgetReloadPolicy.reloadAfterUpgradeIfNeeded()
        // Request a targeted selector rebuild on launch. The same rate-limited
        // coordinator also runs on every foreground activation.
        WatchNeuralCoreWidgetReloadCoordinator.reloadIfDue()
    }

    var body: some Scene {
        WindowGroup {
            WatchConnectView()
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active {
                        WatchNeuralCoreWidgetReloadCoordinator.reloadIfDue()
                    }
                }
        }
    }
}
