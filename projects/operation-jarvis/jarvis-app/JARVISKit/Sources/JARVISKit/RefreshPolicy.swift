import Foundation

/// Shared foreground refresh behavior for the native iPhone and Apple Watch apps.
public enum JARVISRefreshPolicy {
    /// Non-control pages keep a modest foreground cadence.
    public static let activeInterval: Duration = .seconds(15)

    /// Visible control pages read jarvisd's cheap warm cache frequently. Device
    /// collection remains independently bounded on the always-on host.
    public static let controlActiveInterval: Duration = .seconds(5)

    /// A visible Codex panel may request one immediate read per minute rather
    /// than waiting for the host's idle quota cadence.
    public static let visibleCodexRefreshInterval: TimeInterval = 60

    /// jarvisd may return a safe last-good snapshot as `stale + refreshing`
    /// when an idle control collector exceeds its bounded activation wait.
    /// Foreground clients briefly converge that in-flight read instead of
    /// waiting for the ordinary active cadence.
    public static let staleConvergenceInterval: Duration = .milliseconds(500)
    public static let staleConvergenceAttempts = 8
}
