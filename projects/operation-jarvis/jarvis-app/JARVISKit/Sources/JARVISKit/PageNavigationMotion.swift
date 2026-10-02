import SwiftUI

/// One short ease-out language for horizontal phone tabs and vertical Watch pages.
/// Presentation only: selection, routing and command admission never wait for it.
public enum PageNavigationMotion {
    public static let duration = 0.30
    public static let travelFraction = 0.14

    public enum Direction: Equatable {
        case forward, backward
        public var sign: Double { self == .forward ? 1 : -1 }
    }

    public static func direction(from: Int, to: Int) -> Direction? {
        guard from != to else { return nil }
        return to > from ? .forward : .backward
    }

    public static func travel(extent: Double) -> Double {
        guard extent.isFinite, extent > 0 else { return 0 }
        return extent * travelFraction
    }

    public static func allows(active: Bool, reduceMotion: Bool, covered: Bool = false,
                              dimmed: Bool = false) -> Bool {
        active && !reduceMotion && !covered && !dimmed
    }
}

@available(macOS 14, *)
public extension AnyTransition {
    static func jarvisPageSlide(direction: PageNavigationMotion.Direction, axis: Axis) -> AnyTransition {
        .asymmetric(
            insertion: .modifier(active: PageSlideFade(progress: direction.sign, axis: axis),
                                 identity: PageSlideFade(progress: 0, axis: axis)),
            removal: .modifier(active: PageSlideFade(progress: -direction.sign, axis: axis),
                               identity: PageSlideFade(progress: 0, axis: axis))
        )
    }
}

@available(macOS 14, *)
private struct PageSlideFade: ViewModifier, Animatable {
    var progress: Double
    let axis: Axis
    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }

    func body(content: Content) -> some View {
        // Geometry is read as a visual effect: no extra layout container, scroll
        // owner, hit target or page identity is introduced by the animation.
        content.visualEffect { effect, geometry in
            effect
                .offset(x: axis == .horizontal ? progress * PageNavigationMotion.travel(extent: geometry.size.width) : 0,
                        y: axis == .vertical ? progress * PageNavigationMotion.travel(extent: geometry.size.height) : 0)
                .opacity(max(0, 1 - abs(progress)))
        }
    }
}
