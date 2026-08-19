import SwiftUI
import JARVISKit

@main
struct JARVISWatchApp: App {
    init() {
        WatchBridge.shared.start()
    }

    var body: some Scene {
        WindowGroup {
            WatchConnectView()
        }
    }
}
