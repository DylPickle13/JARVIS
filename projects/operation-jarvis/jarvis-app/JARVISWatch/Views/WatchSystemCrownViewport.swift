import SwiftUI
import JARVISKit

/// System uses the accepted Jobs viewport pattern: Crown moves clipped content;
/// no native ScrollView/pan competes with the stable outer page-swipe recognizer.
struct WatchSystemCrownViewport<Content: View>: View {
    let active: Bool
    @ViewBuilder let content: () -> Content
    @State private var contentHeight: CGFloat = 0
    @State private var crown = 0.0
    @FocusState private var crownFocused: Bool

    var body: some View {
        GeometryReader { viewport in
            let maximum = CrownViewportBounds.maximum(content: contentHeight, viewport: viewport.size.height)
            ZStack(alignment: .topLeading) {
                content()
                    .frame(width: viewport.size.width, alignment: .topLeading)
                    .fixedSize(horizontal: false, vertical: true)
                    .background(GeometryReader { geometry in
                        Color.clear.preference(key: SystemContentHeight.self, value: geometry.size.height)
                    })
                    .offset(y: -CrownViewportBounds.offset(crown, content: contentHeight, viewport: viewport.size.height))
            }
            .frame(width: viewport.size.width, height: viewport.size.height, alignment: .topLeading)
            .clipped()
            .contentShape(Rectangle())
            .focusable(active)
            .focused($crownFocused)
            .digitalCrownRotation($crown, from: 0, through: max(1, maximum), by: 12,
                sensitivity: .medium, isContinuous: false, isHapticFeedbackEnabled: true)
            .onPreferenceChange(SystemContentHeight.self) { height in
                contentHeight = height
                crown = CrownViewportBounds.offset(crown, content: height, viewport: viewport.size.height)
            }
            .onChange(of: viewport.size.height) { _, height in
                crown = CrownViewportBounds.offset(crown, content: contentHeight, viewport: height)
            }
            .onAppear { crownFocused = active }
            .onChange(of: active) { _, value in crownFocused = value }
            .task(id: active) {
                // Initial onChange can run before the focus node is mounted.
                // Reassert after mounting, and cancel this rearm under sheets/AOD.
                await Task.yield()
                guard active, !Task.isCancelled else { return }
                crownFocused = true
            }
            .accessibilityScrollAction { direction in
                guard active else { return }
                let step = viewport.size.height * 0.8
                if direction == .bottom { crown = min(maximum, crown + step) }
                if direction == .top { crown = max(0, crown - step) }
            }
        }
    }
}

private struct SystemContentHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}
