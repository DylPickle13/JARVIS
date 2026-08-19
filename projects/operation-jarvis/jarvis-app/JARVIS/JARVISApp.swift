import SwiftUI
import JARVISKit

@main
struct JARVISApp: App {
    @StateObject private var app = AppState()

    init() {
        // Start the WatchConnectivity session (no-op on the simulator if no
        // paired watch; the full relay lands in M3).
        WatchBridge.shared.start()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(app)
                .tint(Color.accentColor)
        }
    }
}

// Four-tab shell (M1): Home / Events / System / Settings.
private struct RootTabView: View {
    @EnvironmentObject var app: AppState
    @State private var selection: Tab = .home

    init() {
        // Dev convenience: -jarvisSeedTab home|events|system|settings
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "-jarvisSeedTab"), i + 1 < args.count,
           let tab = Tab(rawValue: args[i + 1].lowercased()) {
            _selection = State(initialValue: tab)
        }
    }

    var body: some View {
        TabView(selection: $selection) {
            HomeView()
                .tabItem { Label("Home", systemImage: "house.fill") }
                .tag(Tab.home)

            EventsView()
                .tabItem { Label("Events", systemImage: "list.bullet") }
                .tag(Tab.events)

            SystemView()
                .tabItem { Label("System", systemImage: "gearshape.2") }
                .tag(Tab.system)

            SettingsView()
                .tabItem { Label("Settings", systemImage: "slider.horizontal.3") }
                .tag(Tab.settings)
        }
    }
}

private enum Tab: String {
    case home, events, system, settings
}
