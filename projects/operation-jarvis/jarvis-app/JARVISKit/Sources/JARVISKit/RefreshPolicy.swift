import Foundation

/// Shared foreground refresh behavior for the native iPhone and Apple Watch apps.
public enum JARVISRefreshPolicy {
    /// Host apps refresh immediately on activation, then use this cadence while visible.
    public static let activeInterval: Duration = .seconds(15)

    /// jarvisd may return a safe last-good snapshot as `stale + refreshing`
    /// when an idle control collector exceeds its bounded activation wait.
    /// Foreground clients briefly converge that in-flight read instead of
    /// waiting for the ordinary active cadence.
    public static let staleConvergenceInterval: Duration = .milliseconds(500)
    public static let staleConvergenceAttempts = 8
}
