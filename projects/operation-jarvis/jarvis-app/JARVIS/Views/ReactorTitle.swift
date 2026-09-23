import SwiftUI

/// All effects are overlays: they never increase the title's layout footprint.
struct ReactorTitle: View {
    let connected: Bool
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var ignition = Date()

    private var animates: Bool { connected && active && !reduceMotion }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !animates)) { context in
            let phase = ReactorTitlePhase(elapsed: context.date.timeIntervalSince(ignition), animated: animates)
            Text("JARVIS")
                .font(.largeTitle.bold())
                .foregroundStyle(connected ? JarvisPalette.accent.opacity(0.15 + 0.7 * phase.reveal) : Color.secondary)
                .overlay {
                    if connected {
                        GeometryReader { geometry in
                            ZStack {
                                // Energy races outward from the core through the lettering.
                                Rectangle()
                                    .fill(Color.white.opacity(phase.flash))
                                    .frame(width: geometry.size.width * phase.reveal)
                                LinearGradient(colors: [.clear, JarvisPalette.accent, .white, JarvisPalette.accent, .clear],
                                               startPoint: .leading, endPoint: .trailing)
                                    .frame(width: 24)
                                    .offset(x: geometry.size.width * (phase.sweep - 0.5))
                                    .opacity(phase.energy)
                            }
                            .frame(width: geometry.size.width, height: geometry.size.height)
                        }
                        .mask(Text("JARVIS").font(.largeTitle.bold()))
                        .allowsHitTesting(false)
                    }
                }
                .shadow(color: JarvisPalette.accent.opacity(connected ? phase.glow : 0), radius: 5)
                .overlay {
                    GeometryReader { geometry in
                        Ellipse()
                            .stroke(JarvisPalette.accent.opacity(connected ? phase.energy * 0.65 : 0), lineWidth: 1.5)
                            .frame(width: geometry.size.width * phase.sweep,
                                   height: geometry.size.height * phase.sweep)
                            .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
                    }
                    .allowsHitTesting(false)
                }
                .clipped()
        }
        .onAppear { ignition = Date() }
        .onChange(of: connected) { _, online in if online { ignition = Date() } }
        .onChange(of: active) { _, visible in if visible { ignition = Date() } }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("JARVIS")
        .accessibilityAddTraits(.isHeader)
    }
}

struct ReactorTitlePhase {
    let reveal: Double
    let flash: Double
    let glow: Double
    let sweep: Double
    let energy: Double

    init(elapsed: TimeInterval, animated: Bool) {
        guard animated else {
            reveal = 1
            flash = 0
            glow = 0.3
            sweep = 1
            energy = 0
            return
        }
        let time = max(0, elapsed)
        reveal = min(1, time / 0.85)
        flash = max(0, 1 - time / 1.2)
        glow = time < 1.2 ? 0.9 : 0.35 + 0.15 * sin((time - 1.2) * .pi / 2.5)
        // A slow, seamless energy cycle continues after the initial ignition.
        // Fade to zero at both ends so resetting the sweep never flashes.
        sweep = time < 1.2 ? reveal : (time - 1.2).truncatingRemainder(dividingBy: 3.6) / 3.6
        energy = time < 1.2 ? flash : 0.85 * pow(sin(.pi * sweep), 2)
    }
}

/// Keep the title truly centered, irrespective of the trailing status width.
/// Status is constrained to the remaining side space, never over the title.
struct ReactorHeaderLayout: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let title = subviews.first?.sizeThatFits(.unspecified) ?? .zero
        return CGSize(width: proposal.width ?? title.width, height: max(42, title.height))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard let title = subviews.first else { return }
        let size = title.sizeThatFits(.unspecified)
        title.place(at: CGPoint(x: bounds.midX, y: bounds.midY), anchor: .center,
                    proposal: ProposedViewSize(size))
        if subviews.count > 1 {
            let width = Self.statusWidth(headerWidth: bounds.width, titleWidth: size.width)
            subviews[1].place(at: CGPoint(x: bounds.maxX, y: bounds.midY), anchor: .trailing,
                              proposal: ProposedViewSize(width: width, height: bounds.height))
        }
    }

    static func statusWidth(headerWidth: CGFloat, titleWidth: CGFloat) -> CGFloat {
        max(0, (headerWidth - titleWidth) / 2 - 12)
    }
}
