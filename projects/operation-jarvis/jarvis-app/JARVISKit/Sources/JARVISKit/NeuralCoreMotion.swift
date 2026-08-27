import Foundation

/// Deterministic motion values for the native-vector Neural Core.
///
/// WidgetKit animates only when it transitions between timeline entries. The
/// phase therefore advances with real timeline dates; it is not a timer and it
/// does not attempt to create continuous widget updates.
public enum JARVISNeuralCoreMotion {
    public static let transitionDuration: TimeInterval = 1.8
    public static let staticPhase: Double = 0.18

    /// The system-updated timer-text workaround uses a platform-specific stack:
    /// sixty scenes on iPhone (30 FPS) and forty-eight complete motion phases on
    /// Watch (24 FPS) over the same two-second loop. Both surfaces use the same
    /// normalized artwork and synchronized phase origin, while rendering only
    /// the phase-independent halo and wordmark once around their selector stack.
    /// It never asks WidgetKit for extra timeline entries or keeps either
    /// extension process alive.
    public static let phoneContinuousFrameCount = 60
    public static let watchContinuousFrameCount = 48
    public static let continuousLoopDuration: TimeInterval = 2
    public static let continuousReferenceDate = Date(timeIntervalSinceReferenceDate: 0)
    public static let continuousSynchronizedBasePhase: Double = 0

    public static func continuousFrameDuration(frameCount: Int) -> TimeInterval {
        precondition(frameCount > 0)
        return continuousLoopDuration / Double(frameCount)
    }

    /// Returns a normalized Cathedral phase for a frame in the continuous loop.
    public static func continuousPhase(
        basePhase: Double,
        frameIndex: Int,
        frameCount: Int
    ) -> Double {
        precondition(frameCount > 0)
        let normalizedIndex = ((frameIndex % frameCount) + frameCount) % frameCount
        let rawPhase = basePhase + Double(normalizedIndex) / Double(frameCount)
        let remainder = rawPhase.truncatingRemainder(dividingBy: 1)
        return remainder >= 0 ? remainder : remainder + 1
    }

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
