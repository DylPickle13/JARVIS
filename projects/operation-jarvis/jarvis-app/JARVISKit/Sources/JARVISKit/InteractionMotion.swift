import SwiftUI

public enum InteractionMotionPolicy {
    public static func pressScale(pressed: Bool, allowed: Bool) -> Double {
        pressed && allowed ? 0.98 : 1
    }
}

/// Short, input- or confirmed-value-driven motion; never starts work or predicts success.
public struct JarvisPressStyle: ButtonStyle {
    public init() {}
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var dimmed

    public func makeBody(configuration: Configuration) -> some View {
        let allowed = ActivityMotionGate.allows(active: isEnabled, sceneActive: scenePhase == .active,
                                                reduceMotion: reduceMotion, luminanceReduced: dimmed)
        configuration.label
            .scaleEffect(InteractionMotionPolicy.pressScale(pressed: configuration.isPressed, allowed: allowed))
            .animation(allowed ? .easeOut(duration: 0.1) : nil, value: configuration.isPressed)
            .transaction { if !allowed { $0.animation = nil; $0.disablesAnimations = true } }
    }
}

public extension View {
    /// Apply only to a presentation leaf or page container, never to command admission.
    func interactionTransition<Value: Equatable>(value: Value, allowed: Bool = true,
                                                  duration: Double = 0.2) -> some View {
        modifier(InteractionTransition(value: value, allowed: allowed, duration: duration))
    }
}

private struct InteractionTransition<Value: Equatable>: ViewModifier {
    let value: Value
    let allowed: Bool
    let duration: Double
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var dimmed

    func body(content: Content) -> some View {
        let enabled = ActivityMotionGate.allows(active: allowed, sceneActive: scenePhase == .active,
                                                reduceMotion: reduceMotion, luminanceReduced: dimmed)
        content
            .animation(enabled ? .easeOut(duration: duration) : nil, value: value)
            .transaction { if !enabled { $0.animation = nil; $0.disablesAnimations = true } }
    }
}
