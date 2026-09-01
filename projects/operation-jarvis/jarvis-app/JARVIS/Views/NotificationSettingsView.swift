import JARVISKit
import SwiftUI
import UIKit

struct NotificationSettingsView: View {
    @EnvironmentObject var notifications: PushNotificationCoordinator

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 15) {
                SettingsGroup(title: "Native alerts") {
                    Toggle(isOn: enabledBinding) {
                        SettingsNavigationRow(
                            title: "Job result alerts",
                            systemImage: "bell.badge.fill",
                            value: notifications.overallTitle,
                            color: statusColor
                        )
                    }
                    .tint(JarvisPalette.accent)
                }

                SettingsGroup(title: "Registration") {
                    statusRow(
                        title: "iPhone",
                        symbol: "iphone",
                        state: notifications.iphoneState
                    )
                    settingsDivider
                    statusRow(
                        title: "Apple Watch",
                        symbol: "applewatch",
                        state: notifications.watchState
                    )
                }

                if let host = notifications.hostStatus {
                    SettingsGroup(title: "Private APNs provider") {
                        valueRow(
                            title: "Credentials",
                            value: host.providerConfigured ? "Configured" : "Not configured",
                            color: host.providerConfigured ? JarvisPalette.accent : .secondary
                        )
                        settingsDivider
                        valueRow(
                            title: "Host dispatch",
                            value: host.dispatchEnabled ? "Enabled" : "Disabled",
                            color: host.dispatchEnabled ? JarvisPalette.accent : .secondary
                        )
                        settingsDivider
                        valueRow(
                            title: "Delivery queue",
                            value: "\(host.pendingCount) pending · \(host.failedCount) failed · \(host.ambiguousCount) uncertain",
                            color: host.failedCount == 0 && host.ambiguousCount == 0 ? .secondary : JarvisPalette.warning
                        )
                        if let hostError = host.error, !hostError.isEmpty {
                            settingsDivider
                            Text(hostError)
                                .font(.caption)
                                .foregroundStyle(JarvisPalette.warning)
                                .accessibilityIdentifier("notification-provider-error")
                        }
                    }
                }

                if let error = notifications.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(JarvisPalette.warning)
                        .accessibilityIdentifier("notification-error")
                }

                HStack(spacing: 10) {
                    Button("Retry secure update") {
                        Task { await notifications.retryPendingRegistrations() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!notifications.canRetrySecureUpdate)

                    Button("Refresh status") {
                        Task { await notifications.refreshHostStatus() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(notifications.isWorking)
                }

                if notifications.authorizationStatus == .denied {
                    Button("Open iPhone Notification Settings") {
                        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
                        UIApplication.shared.open(url)
                    }
                    .buttonStyle(.bordered)
                }

                Text("Alerts contain only a generic Jobs route. Result details remain in the private, durable Jobs history on your Mac. iPhone and Apple Watch register independently; APNs delivery is best-effort.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(16)
        }
        .scrollIndicators(.hidden)
        .background(JarvisBackdrop())
        .navigationTitle("Notifications")
        .task { await notifications.refreshHostStatus() }
    }

    private var enabledBinding: Binding<Bool> {
        Binding(
            get: { notifications.desiredEnabled },
            set: { enabled in
                Task { await notifications.setEnabled(enabled) }
            }
        )
    }

    private var statusColor: Color {
        switch notifications.overallTitle {
        case JARVISNotificationLocalState.active.title: return JarvisPalette.accent
        case JARVISNotificationLocalState.denied.title,
             JARVISNotificationLocalState.error.title: return JarvisPalette.warning
        default: return .secondary
        }
    }

    private var settingsDivider: some View {
        Divider().padding(.leading, 35)
    }

    private func statusRow(
        title: String,
        symbol: String,
        state: JARVISNotificationLocalState
    ) -> some View {
        SettingsNavigationRow(
            title: title,
            systemImage: symbol,
            value: state.title,
            color: state == .active ? JarvisPalette.accent : (state == .error || state == .denied ? JarvisPalette.warning : .secondary)
        )
    }

    private func valueRow(title: String, value: String, color: Color) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text(value)
                .foregroundStyle(color)
        }
        .font(.subheadline)
    }
}
