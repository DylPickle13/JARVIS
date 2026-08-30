import Foundation
import SwiftUI
import WidgetKit

@main
struct JARVISApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var app = AppState()
    @StateObject private var piTerminal: PiTerminalController

    init() {
        let settings = PiTerminalSettings()
        _piTerminal = StateObject(wrappedValue: PiTerminalController(settings: settings))
        JARVISAppShortcuts.updateAppShortcutParameters()
        // Rebuild the phone Neural Core's system-owned timer selectors after a
        // host launch. WidgetKit still decides when to honor the reload.
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISNeuralCoreWidget.v1")
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
                    case .inactive:
                        app.sceneWillResignActive()
                        // Siri and system overlays make a foreground iPhone
                        // inactive. Keep the SSH terminal attached so a prompt
                        // submitted out-of-band can stream into its open pane.
                    case .background:
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
    @State private var requestedJobResultSequence: Int?

    init() {
        let args = CommandLine.arguments
        if let index = args.firstIndex(of: "-jarvisSeedTab"), index + 1 < args.count,
           let tab = AppSection(rawValue: args[index + 1].lowercased()) {
            _selection = State(initialValue: tab)
        }
    }

    var body: some View {
        TabView(selection: $selection) {
            HomeView(onOpenJobs: { selection = .jobs })
                .tabItem { Label("Home", systemImage: "house.fill") }
                .tag(AppSection.home)

            PiTerminalView()
                .tabItem { Label("JARVIS", systemImage: "terminal.fill") }
                .tag(AppSection.pi)

            JobsView(requestedResultSequence: $requestedJobResultSequence)
                .tabItem { Label("Jobs", systemImage: "calendar.badge.clock") }
                .badge(app.unreadScheduledJobResultCount)
                .tag(AppSection.jobs)

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
            case "jobs":
                selection = .jobs
                let components = url.pathComponents.filter { $0 != "/" }
                if components.count == 2, components[0].lowercased() == "result",
                   let sequence = Int(components[1]), sequence > 0 {
                    requestedJobResultSequence = sequence
                }
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
