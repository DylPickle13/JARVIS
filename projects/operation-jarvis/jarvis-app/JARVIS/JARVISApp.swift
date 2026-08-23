import Foundation
import SwiftUI

@main
struct JARVISApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var app = AppState()
    @StateObject private var piTerminal: PiTerminalController

    init() {
        let settings = PiTerminalSettings()
        _piTerminal = StateObject(wrappedValue: PiTerminalController(settings: settings))
        JARVISAppShortcuts.updateAppShortcutParameters()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(app)
                .environmentObject(piTerminal)
                .tint(Color.accentColor)
                .task {
                    app.startWatchBridge()
                    app.sceneDidBecomeActive()
                    piTerminal.sceneDidBecomeActive()
                }
                .onChange(of: scenePhase) { _, phase in
                    switch phase {
                    case .active:
                        app.sceneDidBecomeActive()
                        piTerminal.sceneDidBecomeActive()
                    case .inactive, .background:
                        app.sceneWillResignActive()
                        piTerminal.sceneWillResignActive()
                    @unknown default:
                        break
                    }
                }
        }
    }
}

private struct RootTabView: View {
    @Environment(\.scenePhase) private var scenePhase
    @EnvironmentObject var app: AppState
    @EnvironmentObject var piTerminal: PiTerminalController
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

            PiTerminalView()
                .tabItem { Label("JARVIS", systemImage: "terminal.fill") }
                .tag(AppSection.pi)

            SettingsView()
                .tabItem { Label("Settings", systemImage: "slider.horizontal.3") }
                .tag(AppSection.settings)
        }
        .onAppear {
            openSiriTerminalIfRequested()
            app.setActiveSection(selection)
            setPiVisibility(selection)
        }
        .onChange(of: selection) { _, value in
            app.setActiveSection(value)
            setPiVisibility(value)
        }
        .onOpenURL { url in
            if JARVISSiriNavigation.isTerminalURL(url) {
                selection = .pi
                return
            }
            guard url.scheme?.lowercased() == "jarvis" else { return }
            switch url.host?.lowercased() {
            case "settings": selection = .settings
            case "pi": selection = .pi
            default: selection = .home
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: JARVISSiriNavigation.terminalRequestNotification)) { _ in
            openSiriTerminalIfRequested()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { openSiriTerminalIfRequested() }
        }
    }

    private func openSiriTerminalIfRequested() {
        guard JARVISSiriNavigation.consumeTerminalPresentationRequest() else { return }
        selection = .pi
    }

    private func setPiVisibility(_ section: AppSection) {
        piTerminal.setVisible(section == .pi, fallbackHost: app.currentEndpoint?.host)
    }
}
