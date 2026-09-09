import Foundation

/// Pixel bounds, not rounded steps: no blank overscroll at the bottom. Shared
/// math permits deterministic tests without sending events to a live Watch.
public enum CrownViewportBounds {
    public static func maximum(content: Double, viewport: Double) -> Double {
        guard content.isFinite, viewport.isFinite, content >= 0, viewport > 0 else { return 0 }
        return max(0, content - viewport)
    }
    public static func offset(_ proposed: Double, content: Double, viewport: Double) -> Double {
        guard proposed.isFinite else { return 0 }
        return min(maximum(content: content, viewport: viewport), max(0, proposed))
    }
}
