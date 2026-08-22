import Foundation

/// Shared foreground refresh behavior for the native iPhone and Apple Watch apps.
public enum JARVISRefreshPolicy {
    /// Host apps refresh immediately on activation, then use this cadence while visible.
    public static let activeInterval: Duration = .seconds(15)
}
