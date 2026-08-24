import Foundation

/// Deterministic motion values for the native-vector Neural Core.
///
/// WidgetKit animates only when it transitions between timeline entries. The
/// phase therefore advances with real timeline dates; it is not a timer and it
/// does not attempt to create continuous widget updates.
public enum JARVISNeuralCoreMotion {
    public static let transitionDuration: TimeInterval = 1.8
    public static let staticPhase: Double = 0.18

    /// Completes one visual cycle per hour. A normal 15-minute widget reload
    /// advances one quarter-cycle, giving the system a meaningful transition
    /// without requesting any additional timeline reloads.
    public static func phase(for date: Date) -> Double {
        let cycle: TimeInterval = 60 * 60
        let remainder = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: cycle)
        let positiveRemainder = remainder >= 0 ? remainder : remainder + cycle
        return positiveRemainder / cycle
    }
}
