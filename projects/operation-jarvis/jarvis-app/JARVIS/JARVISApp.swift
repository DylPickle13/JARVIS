import Foundation
import SwiftUI
import WidgetKit
import JARVISKit
import UIKit
import UserNotifications

@MainActor
final class JARVISAppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = PushNotificationCoordinator.shared
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in
            PushNotificationCoordinator.shared.didRegisterForRemoteNotifications(deviceToken: deviceToken)
        }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in
            PushNotificationCoordinator.shared.didFailToRegisterForRemoteNotifications(error)
        }
    }
}

private enum PhoneNeuralCoreWidgetReloadCoordinator {
    private static let lastRequestedAtKey = "jarvis.phone-neural-core-widget.last-reload-request-at"

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
        WidgetCenter.shared.reloadTimelines(ofKind: "JARVISNeuralCoreWidget.v1")
    }
}

@main
struct JARVISApp: App {
    @UIApplicationDelegateAdaptor(JARVISAppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var app = AppState()
    @StateObject private var notifications = PushNotificationCoordinator.shared
    @StateObject private var piTerminal: PiTerminalController

    init() {
        let settings = PiTerminalSettings()
        _piTerminal = StateObject(wrappedValue: PiTerminalController(settings: settings))
        JARVISAppShortcuts.updateAppShortcutParameters()
        // Request a targeted selector rebuild on launch. The same rate-limited
        // coordinator also runs on every foreground activation.
        PhoneNeuralCoreWidgetReloadCoordinator.reloadIfDue()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(app)
                .environmentObject(notifications)
                .environmentObject(piTerminal)
                .tint(Color.accentColor)
                .task {
                    app.startWatchBridge()
                    notifications.configure(app: app)
                    app.sceneDidBecomeActive()
                    piTerminal.sceneDidBecomeActive()
                }
                .onChange(of: scenePhase) { _, phase in
                    switch phase {
                    case .active:
                        PhoneNeuralCoreWidgetReloadCoordinator.reloadIfDue()
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
    @EnvironmentObject var notifications: PushNotificationCoordinator
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
            HomeView(
                onOpenJobs: { selection = .jobs },
                onOpenPiTerminal: { slot in
                    _ = piTerminal.selectSlot(slot)
                    selection = .pi
                }
            )
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
        .onReceive(NotificationCenter.default.publisher(for: .jarvisPushRoute)) { notification in
            guard let sequence = notification.userInfo?["resultSequence"] as? Int, sequence > 0 else { return }
            selection = .jobs
            requestedJobResultSequence = sequence
            notifications.consumePendingResultSequence()
        }
        .onChange(of: notifications.pendingResultSequence) { _, sequence in
            guard let sequence, sequence > 0 else { return }
            selection = .jobs
            requestedJobResultSequence = sequence
            notifications.consumePendingResultSequence()
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
