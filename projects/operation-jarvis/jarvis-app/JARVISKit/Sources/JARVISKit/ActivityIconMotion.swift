import SwiftUI

/// Shared fixed-speed decorative motion, never a rate/progress indicator.
public enum ActivityMotionGate {
    /// Source age plus elapsed receipt time; cached activity must not pulse forever.
    public static func roomAudioActive(_ status: RoomAudioStatus?, receivedAt: Date?, now: Date) -> Bool {
        guard let status, ["processing", "speaking"].contains(status.phase) else { return false }
        return roomAudioFresh(status, receivedAt: receivedAt, now: now)
    }

    public static func roomAudioFresh(_ status: RoomAudioStatus?, receivedAt: Date?, now: Date) -> Bool {
        guard let status, status.ok, status.clientOnline,
              let age = status.ageSeconds, age.isFinite, age >= 0,
              let receivedAt else { return false }
        let elapsed = now.timeIntervalSince(receivedAt)
        return elapsed.isFinite && elapsed >= 0 && age + elapsed <= 6
    }

    public static func allows(active: Bool, sceneActive: Bool,
                              reduceMotion: Bool, luminanceReduced: Bool) -> Bool {
        active && sceneActive && !reduceMotion && !luminanceReduced
    }
}

public extension View {
    func activityIconPulse(active: Bool) -> some View {
        modifier(ActivityIconPulse(active: active))
    }
}

private struct ActivityIconPulse: ViewModifier {
    let active: Bool
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    @ViewBuilder func body(content: Content) -> some View {
        let enabled = ActivityMotionGate.allows(active: active, sceneActive: scenePhase == .active,
            reduceMotion: reduceMotion, luminanceReduced: luminanceReduced)
        // macOS13 remains supported for shared-package tests; apps target iOS17/watchOS10.
        if #available(iOS 17, watchOS 10, macOS 14, *) {
            content
                .symbolEffect(.pulse, options: .repeating.speed(0.45), isActive: enabled)
                .symbolEffectsRemoved(!enabled)
        } else {
            content
        }
    }
}
