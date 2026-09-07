import Foundation
import UserNotifications

/// Only validated Pi-completion deliveries enter the cleanup policy. No prompt,
/// output, scheduled-job result, or routing inbox is retained here.
struct CompletionNotificationDelivery: Sendable {
    let identifier: String
    let deliveredAt: Date

    init?(identifier: String, deliveredAt: Date, userInfo: [AnyHashable: Any]) {
        guard !identifier.isEmpty, deliveredAt.timeIntervalSinceReferenceDate.isFinite,
              PiSessionCompletionNotificationRoute(
                route: userInfo["route"] as? String,
                version: userInfo["routeVersion"], sessionID: userInfo["sessionID"]
              ) != nil else { return nil }
        self.identifier = identifier
        self.deliveredAt = deliveredAt
    }
}

/// Target-local, active-scene-only cleanup. This is not an APNs expiry or a
/// background execution guarantee. Never clears pending notifications or Jobs.
@MainActor
public final class CompletionNotificationCleanup {
    private let delivered: () async -> [CompletionNotificationDelivery]
    private let remove: ([String]) -> Void
    private let now: () -> Date
    private let automaticallyPoll: Bool
    private var activeSince: Date?
    private var generation = 0
    private var task: Task<Void, Never>?

    init(
        delivered: @escaping () async -> [CompletionNotificationDelivery],
        remove: @escaping ([String]) -> Void,
        now: @escaping () -> Date = Date.init,
        automaticallyPoll: Bool = true
    ) {
        self.delivered = delivered
        self.remove = remove
        self.now = now
        self.automaticallyPoll = automaticallyPoll
    }

    public static func live() -> CompletionNotificationCleanup {
        let center = UNUserNotificationCenter.current()
        return CompletionNotificationCleanup(delivered: {
            await center.deliveredNotifications().compactMap { notification in
                CompletionNotificationDelivery(
                    identifier: notification.request.identifier,
                    deliveredAt: notification.date,
                    userInfo: notification.request.content.userInfo
                )
            }
        }, remove: { identifiers in
            center.removeDeliveredNotifications(withIdentifiers: identifiers)
        })
    }

    public func sceneDidBecomeActive() {
        guard activeSince == nil else { return }
        generation += 1
        activeSince = now()
        guard automaticallyPoll else { return }
        task = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                // Do not retain the controller over the timer suspension.
                guard let delay = await self?.sweep() else { return }
                do { try await Task.sleep(for: .seconds(delay)) }
                catch { return }
            }
        }
    }

    public func sceneWillResignActive() {
        activeSince = nil
        generation += 1
        task?.cancel()
        task = nil
    }

    /// Re-read deliveries rather than retaining IDs across a 30-second timer:
    /// a collapsed/replaced alert must be judged by its current delivery date.
    /// Five seconds is the maximum discovery interval for new deliveries; the
    /// next known deadline is scheduled sooner. OS suspension can delay cleanup.
    func sweep() async -> TimeInterval? {
        guard let openedAt = activeSince else { return nil }
        let requestGeneration = generation
        let notifications = await delivered()
        guard !Task.isCancelled, requestGeneration == generation,
              activeSince != nil else { return nil }
        let current = now()
        var identifiers: Set<String> = []
        var delay: TimeInterval = 5
        for notification in notifications {
            let age = current.timeIntervalSince(notification.deliveredAt)
            if notification.deliveredAt <= openedAt || age >= 30 {
                identifiers.insert(notification.identifier)
            } else if age >= 0 {
                delay = min(delay, max(0.1, 30 - age))
            }
        }
        if !identifiers.isEmpty { remove(identifiers.sorted()) }
        return delay
    }
}
