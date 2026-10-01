import SwiftUI

/// A focused settings index for active runtime configuration.
struct SettingsView: View {
    @EnvironmentObject var app: AppState
    @EnvironmentObject var notifications: PushNotificationCoordinator
    @EnvironmentObject var piTerminal: PiTerminalController

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 15) {
                    TabPageHeader(title: "Settings")
                    SettingsGroup(title: "Configuration") {
                        NavigationLink {
                            ConnectionSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                        } label: {
                            SettingsNavigationRow(
                                title: "Connection",
                                systemImage: "server.rack",
                                value: SettingsPresentation.daemonSummary(app),
                                color: SettingsPresentation.daemonColor(app)
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            PiTerminalSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                        } label: {
                            SettingsNavigationRow(
                                title: "Pi Terminal",
                                systemImage: "terminal.fill",
                                value: piTerminal.settings.hasPassword ? "Configured" : "Setup required",
                                color: piTerminal.settings.hasPassword ? JarvisPalette.accent : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            WatchTerminalSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                        } label: {
                            SettingsNavigationRow(
                                title: "Watch Terminal",
                                systemImage: "applewatch",
                                value: app.watchTerminalProvisioning.isProvisioned ? "Provisioned" : "Setup required",
                                color: app.watchTerminalProvisioning.isProvisioned ? JarvisPalette.accent : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            NotificationSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                                .navigationBarTitleDisplayMode(.inline)
                        } label: {
                            SettingsNavigationRow(
                                title: "Notifications",
                                systemImage: "bell.badge.fill",
                                value: notifications.overallTitle,
                                color: notifications.overallTitle == "Active" ? JarvisPalette.accent : .secondary
                            )
                        }
                        .buttonStyle(.plain)
                    }

                    Text("JARVIS \(SettingsPresentation.appVersion)")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.tertiary)
                        .frame(maxWidth: .infinity)
                        .padding(.top, 2)
                        .accessibilityLabel("JARVIS version \(SettingsPresentation.appVersion)")
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
            .scrollIndicators(.hidden)
            .background(JarvisBackdrop())
            .toolbar(.hidden, for: .navigationBar)
        }
    }

    private var settingsDivider: some View {
        Divider().padding(.leading, 35)
    }
}

#Preview {
    let settings = PiTerminalSettings(defaults: UserDefaults(suiteName: "pi-settings-preview")!)
    return SettingsView()
        .environmentObject(AppState())
        .environmentObject(PushNotificationCoordinator.shared)
        .environmentObject(PiTerminalController(settings: settings))
}
