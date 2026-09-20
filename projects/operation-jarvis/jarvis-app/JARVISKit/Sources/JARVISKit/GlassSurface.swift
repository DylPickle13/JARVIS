#if canImport(SwiftUI)
import SwiftUI

/// Appearance only: never changes layout, hit targets, gestures, or animations.
/// Controls use native Liquid Glass on supported systems; dense content keeps a
/// quieter material surface. The caller supplies its original fill for fallback.
public extension View {
    func jarvisGlassSurface<S: InsettableShape, F: ShapeStyle>(
        _ fallback: F, in shape: S, glass: Bool = false, tint: Color? = nil
    ) -> some View {
        background {
            JarvisGlassSurface(fallback: fallback, shape: shape, glass: glass, tint: tint)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

private struct JarvisGlassSurface<S: InsettableShape, F: ShapeStyle>: View {
    let fallback: F
    let shape: S
    let glass: Bool
    let tint: Color?
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.colorSchemeContrast) private var contrast
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    // The Watch's small, dark canvas needs less decorative edge contrast.
    // Keep accessibility borders and native control glass unchanged.
    private var edgeHighlight: Double {
        #if os(watchOS)
        return 0.12
        #else
        return colorScheme == .dark ? 0.20 : 0.65
        #endif
    }

    var body: some View {
        if reduceTransparency || contrast == .increased {
            // Some original Watch fills are translucent: put an opaque base
            // beneath them rather than allowing content to show through.
            shape.fill(colorScheme == .dark ? Color(white: 0.10) : .white)
                .overlay { shape.fill(fallback) }
                .overlay { shape.strokeBorder(Color.primary.opacity(0.22), lineWidth: 0.75) }
        } else if #available(iOS 26.0, watchOS 26.0, macOS 26.0, *), glass {
            Color.clear.glassEffect(.regular.tint(tint), in: shape)
        } else {
            shape.fill(.thinMaterial)
                .overlay { shape.fill(fallback).opacity(0.35) }
                .overlay {
                    shape.strokeBorder(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(edgeHighlight),
                                Color.white.opacity(0.035),
                                Color.primary.opacity(0.08),
                            ],
                            startPoint: .topLeading, endPoint: .bottomTrailing
                        ),
                        lineWidth: 0.75
                    )
                }
        }
    }
}
#endif
