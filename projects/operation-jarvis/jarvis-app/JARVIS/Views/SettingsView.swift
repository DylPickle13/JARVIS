import SwiftUI
import JARVISKit

/// A focused settings index for active runtime configuration.
struct SettingsView: View {
    @EnvironmentObject var app: AppState
    @EnvironmentObject var notifications: PushNotificationCoordinator
    @EnvironmentObject var piTerminal: PiTerminalController
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    static func columnCount(for size: DynamicTypeSize) -> Int {
        size.isAccessibilitySize ? 1 : 2
    }

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 10),
              count: Self.columnCount(for: dynamicTypeSize))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 15) {
                    TabPageHeader(title: "Settings")
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 10) {
                        NavigationLink {
                            ConnectionSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                        } label: {
                            SettingsNavigationCard(
                                title: "Connection",
                                systemImage: "server.rack",
                                value: SettingsPresentation.daemonSummary(app),
                                color: SettingsPresentation.daemonColor(app)
                            )
                        }
                        .buttonStyle(JarvisPressStyle())

                        NavigationLink {
                            PiTerminalSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                        } label: {
                            SettingsNavigationCard(
                                title: "iPhone Terminal",
                                systemImage: "terminal.fill",
                                value: piTerminal.settings.hasPassword ? "Configured" : "Setup required",
                                color: piTerminal.settings.hasPassword ? JarvisPalette.accent : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(JarvisPressStyle())

                        NavigationLink {
                            WatchTerminalSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                        } label: {
                            SettingsNavigationCard(
                                title: "Watch Terminal",
                                systemImage: "applewatch",
                                value: app.watchTerminalProvisioning.isProvisioned ? "Configured" : "Setup required",
                                color: app.watchTerminalProvisioning.isProvisioned ? JarvisPalette.accent : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(JarvisPressStyle())

                        NavigationLink {
                            NotificationSettingsView()
                                .toolbar(.visible, for: .navigationBar)
                                .navigationBarTitleDisplayMode(.inline)
                        } label: {
                            SettingsNavigationCard(
                                title: "Notifications",
                                systemImage: "bell.badge.fill",
                                value: notifications.overallTitle,
                                color: notifications.overallTitle == "Active" ? JarvisPalette.accent : .secondary
                            )
                        }
                        .buttonStyle(JarvisPressStyle())
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

}

struct SettingsNavigationCard: View {
    let title: String
    let systemImage: String
    let value: String
    let color: Color
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .body) private var iconSize = 22.0

    var body: some View {
        MinimalCard(padding: 12) {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: systemImage)
                        .font(.system(size: iconSize, weight: .semibold))
                        .foregroundStyle(color)
                        .frame(width: iconSize + 8, height: iconSize + 8)
                    Spacer(minLength: 4)
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
                .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
                        .frame(minHeight: dynamicTypeSize.isAccessibilitySize ? 0 : 36, alignment: .topLeading)
                    Text(value)
                        .font(.caption)
                        .foregroundStyle(color)
                        .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
                        .frame(minHeight: dynamicTypeSize.isAccessibilitySize ? 0 : 30, alignment: .topLeading)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens \(title) settings")
    }
}

#Preview {
    let settings = PiTerminalSettings(defaults: UserDefaults(suiteName: "pi-settings-preview")!)
    return SettingsView()
        .environmentObject(AppState())
        .environmentObject(PushNotificationCoordinator.shared)
        .environmentObject(PiTerminalController(settings: settings))
}
