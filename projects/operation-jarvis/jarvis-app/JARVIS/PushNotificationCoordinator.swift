import Foundation
import JARVISKit
import Security
import SwiftUI
import UIKit
import UserNotifications

extension Notification.Name {
    static let jarvisPushRoute = Notification.Name("com.operation-jarvis.jarvis.push-route")
}

@MainActor
final class PushNotificationCoordinator: NSObject, ObservableObject {
    static let shared = PushNotificationCoordinator()

    @Published private(set) var desiredEnabled: Bool
    @Published private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published private(set) var iphoneState: JARVISNotificationLocalState = .off
    @Published private(set) var watchState: JARVISNotificationLocalState = .off
    @Published private(set) var hostStatus: JARVISNotificationStatus?
    @Published private(set) var pendingResultSequence: Int?
    @Published private(set) var isWorking = false
    @Published private(set) var errorMessage: String?

    private weak var app: AppState?
    private let defaults = UserDefaults.standard
    private let desiredKey = "jarvis.notifications.desired-enabled.v1"
    private let installationKey = "jarvis.notifications.iphone-installation-id.v1"
    private let watchInstallationKey = "jarvis.notifications.watch-installation-id.v1"
    private var pendingRegistrations: [JARVISPushPlatform: JARVISPushRegistration] = [:]
    private var queuedRegistrations: [JARVISPushPlatform: JARVISPushRegistration] = [:]
    private var activeUploads: Set<JARVISPushPlatform> = []

    private override init() {
        desiredEnabled = UserDefaults.standard.bool(forKey: "jarvis.notifications.desired-enabled.v1")
        super.init()
        iphoneState = desiredEnabled ? .registering : .off
        watchState = desiredEnabled ? .registering : .off
    }

    var overallTitle: String {
        if !desiredEnabled { return JARVISNotificationLocalState.off.title }
        if authorizationStatus == .denied { return JARVISNotificationLocalState.denied.title }
        if iphoneState == .active && watchState == .active {
            return hostStatus?.providerConfigured == true && hostStatus?.dispatchEnabled == true
                ? JARVISNotificationLocalState.active.title
                : "Registered"
        }
        if iphoneState == .error || watchState == .error { return JARVISNotificationLocalState.error.title }
        if iphoneState == .pendingSecureUpload || watchState == .pendingSecureUpload {
            return JARVISNotificationLocalState.pendingSecureUpload.title
        }
        return JARVISNotificationLocalState.registering.title
    }

    var canRetrySecureUpdate: Bool {
        guard !isWorking else { return false }
        if desiredEnabled { return true }
        return pendingRegistrations.values.contains { $0.action == .deactivate }
    }

    func configure(app: AppState) {
        self.app = app
        UNUserNotificationCenter.current().delegate = self
        Task {
            await refreshAuthorizationStatus()
            await refreshHostStatus()
            if desiredEnabled, authorizationAllowsAlerts {
                UIApplication.shared.registerForRemoteNotifications()
                _ = WatchBridge.shared.sendPushPreference(enabled: true)
            }
        }
    }

    func setEnabled(_ enabled: Bool) async {
        guard enabled != desiredEnabled else {
            if enabled { await retryPendingRegistrations() }
            return
        }
        errorMessage = nil
        desiredEnabled = enabled
        defaults.set(enabled, forKey: desiredKey)
        if enabled {
            pendingRegistrations = pendingRegistrations.filter { $0.value.action == .register }
            iphoneState = .needsPermission
            watchState = .registering
            let granted: Bool
            do {
                granted = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            } catch {
                iphoneState = .error
                errorMessage = error.localizedDescription
                await refreshAuthorizationStatus()
                return
            }
            await refreshAuthorizationStatus()
            guard granted, authorizationAllowsAlerts else {
                iphoneState = authorizationStatus == .denied ? .denied : .error
                errorMessage = "Notifications were not authorized."
                return
            }
            iphoneState = .registering
            UIApplication.shared.registerForRemoteNotifications()
            if !WatchBridge.shared.sendPushPreference(enabled: true) {
                watchState = .pendingSecureUpload
                errorMessage = "Open JARVIS on Apple Watch, then retry notification setup."
            }
        } else {
            UIApplication.shared.unregisterForRemoteNotifications()
            iphoneState = .off
            watchState = .off
            pendingRegistrations.removeAll()
            _ = WatchBridge.shared.sendPushPreference(enabled: false)
            await uploadDeactivations()
        }
        await refreshHostStatus()
    }

    func retryPendingRegistrations() async {
        errorMessage = nil
        await refreshAuthorizationStatus()
        guard desiredEnabled else {
            for registration in pendingRegistrations.values where registration.action == .deactivate {
                await upload(registration)
            }
            await refreshHostStatus()
            return
        }
        if authorizationAllowsAlerts {
            iphoneState = pendingRegistrations[.iphone] == nil ? .registering : .pendingSecureUpload
            UIApplication.shared.registerForRemoteNotifications()
        }
        if !WatchBridge.shared.sendPushPreference(enabled: true), watchState != .active {
            watchState = .pendingSecureUpload
        }
        for registration in pendingRegistrations.values where registration.action == .register {
            await upload(registration)
        }
        await refreshHostStatus()
    }

    func refreshHostStatus() async {
        guard let app, let endpoint = app.store.endpoint else { return }
        do {
            hostStatus = try await app.client.notificationStatus(endpoint)
            if desiredEnabled {
                if authorizationAllowsAlerts,
                   hostStatus?.devices.iphone.registered == true,
                   pendingRegistrations[.iphone] == nil {
                    iphoneState = .active
                }
                if hostStatus?.devices.watch.registered == true, pendingRegistrations[.watch] == nil {
                    watchState = .active
                }
            }
        } catch {
            // Registration uses SSH and must remain independent from this
            // sanitized, read-only HTTP status surface.
        }
    }

    func didRegisterForRemoteNotifications(deviceToken: Data) {
        guard desiredEnabled else { return }
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        guard let installationID = installationID(for: installationKey),
              let registration = JARVISPushRegistration(
                action: .register,
                platform: .iphone,
                environment: Self.environment,
                installationID: installationID,
                deviceToken: token
              ) else {
            iphoneState = .error
            errorMessage = "iPhone returned an invalid APNs registration token."
            return
        }
        pendingRegistrations[.iphone] = registration
        iphoneState = .pendingSecureUpload
        Task { await upload(registration) }
    }

    func present(resultSequence: Int) {
        guard resultSequence > 0 else { return }
        pendingResultSequence = resultSequence
    }

    func consumePendingResultSequence() {
        pendingResultSequence = nil
    }

    func didFailToRegisterForRemoteNotifications(_ error: Error) {
        guard desiredEnabled else { return }
        iphoneState = .error
        errorMessage = "iPhone APNs registration failed: \(error.localizedDescription)"
    }

    func receiveWatchRegistration(_ registration: JARVISPushRegistration) {
        guard registration.platform == .watch, registration.isValid else { return }
        guard saveInstallationID(registration.installationID, for: watchInstallationKey) else {
            watchState = .error
            errorMessage = "Could not secure the Apple Watch installation identity."
            return
        }
        if !desiredEnabled, registration.action == .register {
            // A stale Watch opt-in can never reactivate host delivery after the
            // owner disabled the iPhone control.
            return
        }
        pendingRegistrations[.watch] = registration
        watchState = registration.action == .register ? .pendingSecureUpload : .off
        Task { await upload(registration) }
    }

    private var authorizationAllowsAlerts: Bool {
        switch authorizationStatus {
        case .authorized, .provisional, .ephemeral: return true
        default: return false
        }
    }

    private func refreshAuthorizationStatus() async {
        authorizationStatus = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
        if authorizationStatus == .denied, desiredEnabled { iphoneState = .denied }
    }

    private func upload(_ registration: JARVISPushRegistration) async {
        guard activeUploads.insert(registration.platform).inserted else {
            // Keep only the newest desired action for this fixed platform. This
            // prevents an in-flight registration from defeating owner disable.
            queuedRegistrations[registration.platform] = registration
            return
        }
        isWorking = true
        defer {
            activeUploads.remove(registration.platform)
            isWorking = !activeUploads.isEmpty
            if let queued = queuedRegistrations.removeValue(forKey: registration.platform) {
                Task { await self.upload(queued) }
            }
        }
        do {
            let settings = PiTerminalSettings()
            guard let configuration = settings.configuration(fallbackHost: app?.currentEndpoint?.host),
                  let trustedHostKey = settings.trustedHostKey(host: configuration.host, port: configuration.port) else {
                throw PushNotificationCoordinatorError.missingSecureConfiguration
            }
            _ = try await PushRegistrationSSHTransport().upload(
                registration,
                configuration: configuration,
                trustedHostKey: trustedHostKey
            )
            pendingRegistrations.removeValue(forKey: registration.platform)
            if registration.action == .register, !desiredEnabled {
                if let deactivation = JARVISPushRegistration(
                    action: .deactivate,
                    platform: registration.platform,
                    environment: registration.environment,
                    installationID: registration.installationID,
                    deviceToken: nil
                ) {
                    queuedRegistrations[registration.platform] = deactivation
                }
            } else if registration.action == .register {
                if registration.platform == .iphone { iphoneState = .active }
                if registration.platform == .watch { watchState = .active }
            } else {
                if registration.platform == .iphone { iphoneState = .off }
                if registration.platform == .watch { watchState = .off }
            }
            await refreshHostStatus()
        } catch {
            if registration.action == .register {
                if registration.platform == .iphone { iphoneState = .pendingSecureUpload }
                if registration.platform == .watch { watchState = .pendingSecureUpload }
            } else if !desiredEnabled {
                // Deactivation carries no token and remains retryable in memory
                // until the fixed host command acknowledges owner disable.
                pendingRegistrations[registration.platform] = registration
            }
            errorMessage = error.localizedDescription
        }
    }

    private func uploadDeactivations() async {
        let iphone = installationID(for: installationKey).flatMap {
            JARVISPushRegistration(
                action: .deactivate,
                platform: .iphone,
                environment: Self.environment,
                installationID: $0,
                deviceToken: nil
            )
        }
        let watchID = storedInstallationID(for: watchInstallationKey)
        let watch = watchID.flatMap {
            JARVISPushRegistration(
                action: .deactivate,
                platform: .watch,
                environment: Self.environment,
                installationID: $0,
                deviceToken: nil
            )
        }
        if let iphone { await upload(iphone) }
        if let watch { await upload(watch) }
    }

    private func installationID(for key: String) -> String? {
        if let existing = storedInstallationID(for: key), let uuid = UUID(uuidString: existing) {
            return uuid.uuidString.lowercased()
        }
        let created = UUID().uuidString.lowercased()
        return saveInstallationID(created, for: key) ? created : nil
    }

    private func storedInstallationID(for account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.operation-jarvis.jarvis.push-installation",
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else { return nil }
        return value
    }

    @discardableResult
    private func saveInstallationID(_ value: String, for account: String) -> Bool {
        let data = Data(value.utf8)
        let identity: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.operation-jarvis.jarvis.push-installation",
            kSecAttrAccount as String: account,
        ]
        let update: [String: Any] = [kSecValueData as String: data]
        let updated = SecItemUpdate(identity as CFDictionary, update as CFDictionary)
        if updated == errSecSuccess { return true }
        guard updated == errSecItemNotFound else { return false }
        var insertion = identity
        insertion[kSecValueData as String] = data
        insertion[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(insertion as CFDictionary, nil) == errSecSuccess
    }

    // Direct device builds use Apple Development provisioning. Distribution
    // builds must change this together with the signed aps-environment.
    private static let environment: JARVISPushEnvironment = .development

    nonisolated static func route(from userInfo: [AnyHashable: Any]) -> ScheduledJobNotificationRoute? {
        let route = userInfo["route"] as? String
        let version: Int?
        if let value = userInfo["routeVersion"] as? Int {
            version = value
        } else if let value = userInfo["routeVersion"] as? String {
            version = Int(value)
        } else {
            version = nil
        }
        return ScheduledJobNotificationRoute(
            route: route,
            version: version,
            resultSequence: userInfo["resultSequence"]
        )
    }
}

extension PushNotificationCoordinator: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        guard Self.route(from: notification.request.content.userInfo) != nil else { return [] }
        return [.banner, .sound]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        guard let route = Self.route(from: response.notification.request.content.userInfo) else { return }
        await MainActor.run {
            PushNotificationCoordinator.shared.present(resultSequence: route.resultSequence)
        }
        NotificationCenter.default.post(
            name: .jarvisPushRoute,
            object: nil,
            userInfo: ["resultSequence": route.resultSequence]
        )
    }
}

private enum PushNotificationCoordinatorError: LocalizedError {
    case missingSecureConfiguration

    var errorDescription: String? {
        "Save Pi Terminal credentials and trust the Mac before uploading APNs registration."
    }
}
