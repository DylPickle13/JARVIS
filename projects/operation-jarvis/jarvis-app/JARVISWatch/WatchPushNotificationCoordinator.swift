import Foundation
import JARVISKit
import Security
import UserNotifications
import WatchKit

extension Notification.Name {
    static let jarvisWatchPushRoute = Notification.Name("com.operation-jarvis.jarvis.watch.push-route")
}

@MainActor
final class WatchPushNotificationCoordinator: NSObject, ObservableObject {
    static let shared = WatchPushNotificationCoordinator()

    @Published private(set) var desiredEnabled: Bool
    @Published private(set) var state: JARVISNotificationLocalState
    @Published private(set) var pendingResultSequence: Int?
    @Published var showPermissionExplanation = false
    @Published private(set) var errorMessage: String?

    private let defaults = UserDefaults.standard
    private let desiredKey = "jarvis.notifications.watch-desired-enabled.v1"
    private let installationKey = "jarvis.notifications.watch-installation-id.v1"
    private var pendingRegistration: JARVISPushRegistration?

    private override init() {
        let desired = UserDefaults.standard.bool(forKey: "jarvis.notifications.watch-desired-enabled.v1")
        desiredEnabled = desired
        state = desired ? .registering : .off
        super.init()
        UNUserNotificationCenter.current().delegate = self
    }

    func configure() {
        UNUserNotificationCenter.current().delegate = self
        if desiredEnabled {
            Task { await receiveDesiredEnabled(true) }
        }
    }

    /// The iPhone sends desired state only. A not-determined Watch never shows
    /// Apple's prompt until the owner separately taps Allow on the Watch.
    func receiveDesiredEnabled(_ enabled: Bool) async {
        desiredEnabled = enabled
        defaults.set(enabled, forKey: desiredKey)
        errorMessage = nil
        guard enabled else {
            showPermissionExplanation = false
            WKExtension.shared().unregisterForRemoteNotifications()
            state = .off
            pendingRegistration = nil
            if let installationID,
               let deactivation = JARVISPushRegistration(
                action: .deactivate,
                platform: .watch,
                environment: Self.environment,
                installationID: installationID,
                deviceToken: nil
               ) {
                send(deactivation)
            }
            return
        }

        let settings = await UNUserNotificationCenter.current().notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            state = .registering
            showPermissionExplanation = false
            WKExtension.shared().registerForRemoteNotifications()
            if let pendingRegistration { send(pendingRegistration) }
        case .notDetermined:
            state = .needsPermission
            showPermissionExplanation = true
        case .denied:
            state = .denied
            showPermissionExplanation = false
            errorMessage = "Enable JARVIS notifications in Apple Watch settings."
        @unknown default:
            state = .error
            showPermissionExplanation = false
        }
    }

    func authorizeFromExplanation() async {
        guard desiredEnabled else { return }
        showPermissionExplanation = false
        do {
            let granted = try await UNUserNotificationCenter.current()
                .requestAuthorization(options: [.alert, .sound])
            guard granted else {
                state = .denied
                errorMessage = "Apple Watch notifications were not authorized."
                return
            }
            state = .registering
            WKExtension.shared().registerForRemoteNotifications()
        } catch {
            state = .error
            errorMessage = error.localizedDescription
        }
    }

    func deferAuthorization() {
        showPermissionExplanation = false
        state = .needsPermission
    }

    func didRegister(deviceToken: Data) {
        guard desiredEnabled else { return }
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        guard let installationID,
              let registration = JARVISPushRegistration(
                action: .register,
                platform: .watch,
                environment: Self.environment,
                installationID: installationID,
                deviceToken: token
              ) else {
            state = .error
            errorMessage = "Apple Watch returned an invalid APNs registration token."
            return
        }
        pendingRegistration = registration
        state = .pendingSecureUpload
        send(registration)
    }

    func present(resultSequence: Int) {
        guard resultSequence > 0 else { return }
        pendingResultSequence = resultSequence
    }

    func consumePendingResultSequence() {
        pendingResultSequence = nil
    }

    func didFailToRegister(_ error: Error) {
        guard desiredEnabled else { return }
        state = .error
        errorMessage = error.localizedDescription
    }

    private func send(_ registration: JARVISPushRegistration) {
        if WatchBridge.shared.sendPushRegistration(registration) {
            if registration.action == .register {
                // WCSession acceptance is not host acknowledgement. Retain the
                // in-memory token and remain pending; iPhone Settings reads the
                // sanitized host registration state authoritatively.
                state = .pendingSecureUpload
            }
        } else if registration.action == .register {
            state = .pendingSecureUpload
            errorMessage = "Open JARVIS on the paired iPhone and retry."
        }
    }

    private var installationID: String? {
        let identity: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.operation-jarvis.jarvis.watch.push-installation",
            kSecAttrAccount as String: installationKey,
        ]
        var query = identity
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        if SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
           let data = item as? Data,
           let value = String(data: data, encoding: .utf8),
           let uuid = UUID(uuidString: value) {
            return uuid.uuidString.lowercased()
        }

        let created = UUID().uuidString.lowercased()
        var insertion = identity
        insertion[kSecValueData as String] = Data(created.utf8)
        insertion[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(insertion as CFDictionary, nil) == errSecSuccess else { return nil }
        return created
    }

    // Direct device builds use Apple Development provisioning. Distribution
    // builds must change this together with the signed aps-environment.
    private static let environment: JARVISPushEnvironment = .development

    nonisolated static func route(from userInfo: [AnyHashable: Any]) -> ScheduledJobNotificationRoute? {
        let version: Int?
        if let value = userInfo["routeVersion"] as? Int {
            version = value
        } else if let value = userInfo["routeVersion"] as? String {
            version = Int(value)
        } else {
            version = nil
        }
        return ScheduledJobNotificationRoute(
            route: userInfo["route"] as? String,
            version: version,
            resultSequence: userInfo["resultSequence"]
        )
    }
}

extension WatchPushNotificationCoordinator: UNUserNotificationCenterDelegate {
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
            WatchPushNotificationCoordinator.shared.present(resultSequence: route.resultSequence)
        }
        NotificationCenter.default.post(
            name: .jarvisWatchPushRoute,
            object: nil,
            userInfo: ["resultSequence": route.resultSequence]
        )
    }
}
