import SwiftUI

/// Presentation only: no button, transport, policy changes, or confirmation ownership.
/// Phone geometry matches PlugCard; Watch uses a much smaller two-column row.
public struct HomeAutomationCardContent: View {
    public enum Size: Equatable, Sendable { case phone, watch }
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    public let control: HomeAutomationControl
    public let status: String
    public let enabled: Bool?
    public let busy: Bool
    public let hasWarning: Bool
    public let size: Size
    public let accent: Color
    public let warning: Color
    public let surface: Color

    public init(control: HomeAutomationControl, status: String, enabled: Bool?, busy: Bool,
                hasWarning: Bool = false, size: Size, accent: Color, warning: Color, surface: Color) {
        self.control = control; self.status = status; self.enabled = enabled; self.busy = busy
        self.hasWarning = hasWarning; self.size = size
        self.accent = accent; self.warning = warning; self.surface = surface
    }

    private var watch: Bool { size == .watch }
    private var growsForAccessibility: Bool { watch && dynamicTypeSize.isAccessibilitySize }
    private var iconColor: Color { enabled == true ? accent : .secondary }
    private var stateColor: Color { busy || hasWarning || status == "Unconfirmed" ? warning : iconColor }
    private var height: CGFloat { watch ? 44 : 54 }
    private var corner: CGFloat { watch ? 9 : 14 }

    public var body: some View {
        HStack(spacing: watch ? 3 : 8) {
            ZStack {
                if !watch { Circle().fill(iconColor.opacity(0.12)) }
                if busy {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: control.symbol)
                        .font(watch ? .system(size: 11, weight: .semibold) : .caption.weight(.semibold))
                        .foregroundStyle(iconColor)
                }
            }
            .frame(width: watch ? 12 : 30, height: watch ? 16 : 30)
            if watch {
                VStack(alignment: .leading, spacing: 1) {
                    title
                    state
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                title
                Spacer(minLength: 4)
                state
            }
        }
        .padding(.horizontal, watch ? 5 : 10)
        .padding(.vertical, growsForAccessibility ? 5 : 0)
        .frame(maxWidth: .infinity, minHeight: height, maxHeight: growsForAccessibility ? nil : height,
               alignment: .leading)
        .jarvisGlassSurface(surface, in: RoundedRectangle(cornerRadius: corner, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: corner, style: .continuous)
                .stroke(enabled == true ? accent.opacity(0.28) : Color.primary.opacity(0.055), lineWidth: 0.75)
        }
        .contentShape(RoundedRectangle(cornerRadius: corner, style: .continuous))
        // The owning Button ignores decorative children and supplies full semantics.
    }

    private var title: some View {
        Text(control.title)
            .font(watch && !growsForAccessibility ? .system(size: 10, weight: .semibold) : .caption.weight(.semibold))
            .foregroundStyle(.primary)
            .lineLimit(growsForAccessibility ? nil : 2)
            .minimumScaleFactor(watch ? 0.85 : 0.72)
    }

    private var state: some View {
        Text(HomeAutomationControl.compactStatus(status, warning: hasWarning))
            .font(watch && !growsForAccessibility ? .system(size: 9, weight: .bold) : .caption2.weight(.bold))
            .foregroundStyle(stateColor)
            .lineLimit(1)
    }
}
