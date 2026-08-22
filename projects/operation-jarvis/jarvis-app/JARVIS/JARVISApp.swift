import SwiftUI
@main
struct JARVISApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var app = AppState()

    init() {
        JARVISAppShortcuts.updateAppShortcutParameters()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(app)
                .tint(Color.accentColor)
                .task {
                    app.startWatchBridge()
                    app.sceneDidBecomeActive()
                }
                .onChange(of: scenePhase) { _, phase in
                    switch phase {
                    case .active:
                        app.sceneDidBecomeActive()
                    case .inactive, .background:
                        app.sceneWillResignActive()
                    @unknown default:
                        break
                    }
                }
        }
    }
}

private struct RootTabView: View {
    @EnvironmentObject var app: AppState
    @State private var selection: AppSection = .home

    init() {
        let args = CommandLine.arguments
        if let index = args.firstIndex(of: "-jarvisSeedTab"), index + 1 < args.count,
           let tab = AppSection(rawValue: args[index + 1].lowercased()) {
            _selection = State(initialValue: tab)
        }
    }

    var body: some View {
        TabView(selection: $selection) {
            HomeView()
                .tabItem { Label("Home", systemImage: "house.fill") }
                .tag(AppSection.home)

            SettingsView()
                .tabItem { Label("Settings", systemImage: "slider.horizontal.3") }
                .tag(AppSection.settings)
        }
        .onAppear { app.setActiveSection(selection) }
        .onChange(of: selection) { _, value in
            app.setActiveSection(value)
        }
        .onOpenURL { url in
            guard url.scheme?.lowercased() == "jarvis" else { return }
            switch url.host?.lowercased() {
            case "settings": selection = .settings
            default: selection = .home
            }
        }
    }
}
