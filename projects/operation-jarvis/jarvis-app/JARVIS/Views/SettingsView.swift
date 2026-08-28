import SwiftUI

/// A focused settings index. Configuration, recovery, and signing controls stay
/// available in dedicated pages without duplicating diagnostics on the root.
struct SettingsView: View {
    @EnvironmentObject var app: AppState
    @EnvironmentObject var piTerminal: PiTerminalController
    @State private var localSigningStatus = LocalSigningStatus.current()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 15) {
                    SettingsGroup(title: "Configuration") {
                        NavigationLink {
                            ConnectionSettingsView()
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
                        } label: {
                            SettingsNavigationRow(
                                title: "Pi Terminal",
                                systemImage: "terminal.fill",
                                value: piTerminal.settings.hasPassword ? "Configured" : "Setup required",
                                color: piTerminal.settings.hasPassword ? JarvisPalette.cyan : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            WatchTerminalSettingsView()
                        } label: {
                            SettingsNavigationRow(
                                title: "Watch Terminal",
                                systemImage: "applewatch",
                                value: app.watchTerminalProvisioning.isProvisioned ? "Provisioned" : "Setup required",
                                color: app.watchTerminalProvisioning.isProvisioned ? JarvisPalette.cyan : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)
                    }

                    SettingsGroup(title: "Maintenance") {
                        NavigationLink {
                            DeveloperSigningSettingsView()
                        } label: {
                            TimelineView(.periodic(from: .now, by: 60)) { context in
                                SettingsNavigationRow(
                                    title: "Developer Signing",
                                    systemImage: "checkmark.seal",
                                    value: signingSummary(at: context.date),
                                    color: SettingsPresentation.signingColor(
                                        expiration: localSigningStatus.earliestExpiration,
                                        at: context.date
                                    )
                                )
                            }
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
            .navigationTitle("Settings")
            .onAppear { localSigningStatus = .current() }
        }
    }

    private var settingsDivider: some View {
        Divider().padding(.leading, 35)
    }

    private func signingSummary(at date: Date) -> String {
        guard let expiration = localSigningStatus.earliestExpiration else { return "Unavailable" }
        return SettingsPresentation.signingCountdown(to: expiration, at: date)
    }
}

#Preview {
    let settings = PiTerminalSettings(defaults: UserDefaults(suiteName: "pi-settings-preview")!)
    return SettingsView()
        .environmentObject(AppState())
        .environmentObject(PiTerminalController(settings: settings))
}
