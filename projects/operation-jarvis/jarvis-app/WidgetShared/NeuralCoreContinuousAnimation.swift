import CoreText
import Foundation
import OSLog
import SwiftUI
import JARVISKit

/// Registers the tiny alternating-glyph font used only as an alpha mask. The
/// Cathedral frames themselves remain native procedural SwiftUI geometry.
enum JARVISWidgetTimerAnimationFont {
    static let postScriptName = "FillRect-Regular"
    static let resourceName = "FillRect-Regular"
    static let resourceExtension = "otf"
    private static let logger = Logger(
        subsystem: "com.operation-jarvis.jarvis.widgets",
        category: "animation-font"
    )

    @discardableResult
    static func register() -> Bool {
        guard let url = Bundle.main.url(
            forResource: resourceName,
            withExtension: resourceExtension
        ) else {
            logger.error("Timer animation font registration outcome=resource-missing")
            return false
        }

        if isAvailable {
            logger.info("Timer animation font registration outcome=already-available")
            return true
        }

        var unmanagedError: Unmanaged<CFError>?
        let registered = CTFontManagerRegisterFontsForURL(
            url as CFURL,
            .process,
            &unmanagedError
        )
        if let unmanagedError {
            _ = unmanagedError.takeRetainedValue()
        }
        let available = registered || isAvailable
        let outcome = available ? "available" : "unavailable"
        logger.info(
            "Timer animation font registration outcome=\(outcome, privacy: .public)"
        )
        return available
    }

    static var isAvailable: Bool {
        let font = CTFontCreateWithName(postScriptName as CFString, 12, nil)
        return CTFontCopyPostScriptName(font) as String == postScriptName
    }
}

/// Uses WidgetKit's system-maintained timer text as a deterministic frame
/// selector. This is intentionally isolated from the telemetry provider: no
/// timeline reload, process timer, network request, or queued work drives it.
struct JARVISNeuralCoreContinuousArtwork: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let basePhase: Double
    let allowsMotion: Bool
    let selectorGeneration: TimeInterval

    @Environment(\.isLuminanceReduced) private var isLuminanceReduced
    @Environment(\.accessibilityReduceMotion) private var accessibilityReduceMotion

    private var motionDecision: JARVISNeuralCoreContinuousMotionDecision {
        JARVISNeuralCoreContinuousMotionPolicy.decision(
            allowsMotion: allowsMotion,
            isLuminanceReduced: isLuminanceReduced,
            accessibilityReduceMotion: accessibilityReduceMotion,
            fontAvailable: JARVISWidgetTimerAnimationFont.isAvailable
        )
    }

    var body: some View {
        let decision = motionDecision
        Group {
            if decision == .animate {
                GeometryReader { geometry in
                    let extent = max(1, max(geometry.size.width, geometry.size.height))

                    ZStack(alignment: .topLeading) {
                        if layout == .watch {
                            // Keep the complete-view wrapper that physically animates
                            // on Watch. Every authored phase-driven layer remains in
                            // each of the 48 nominal-24-FPS selector scenes.
                            JARVISNeuralCoreArtwork(
                                telemetry: telemetry,
                                layout: layout,
                                motionPhase: basePhase,
                                allowsMotion: true,
                                hidesAccessibility: true,
                                layerSet: .staticBackground,
                                includesWordmark: false
                            )

                            ForEach(0..<layout.continuousFrameCount, id: \.self) { index in
                                JARVISNeuralCoreArtwork(
                                    telemetry: telemetry,
                                    layout: layout,
                                    motionPhase: JARVISNeuralCoreMotion.continuousPhase(
                                        basePhase: JARVISNeuralCoreMotion.continuousSynchronizedBasePhase,
                                        frameIndex: index,
                                        frameCount: layout.continuousFrameCount
                                    ),
                                    allowsMotion: true,
                                    hidesAccessibility: true,
                                    layerSet: .phaseArtwork,
                                    includesWordmark: false
                                )
                                .mask {
                                    JARVISWidgetTimerFrameWindow(
                                        frameIndex: index,
                                        frameCount: layout.continuousFrameCount,
                                        extent: extent
                                    )
                                    .frame(
                                        width: geometry.size.width,
                                        height: geometry.size.height
                                    )
                                }
                            }
                        } else {
                            // Phone keeps 48 authored phases at nominal 24 FPS.
                            // Its lightweight wrapper and the common static halo avoid
                            // redundant view work without changing any moving layer.
                            JARVISNeuralCoreAnimationFrame(
                                telemetry: telemetry,
                                layout: layout,
                                motionPhase: basePhase,
                                layerSet: .staticBackground
                            )

                            ForEach(0..<layout.continuousFrameCount, id: \.self) { index in
                                JARVISNeuralCoreAnimationFrame(
                                    telemetry: telemetry,
                                    layout: layout,
                                    motionPhase: JARVISNeuralCoreMotion.continuousPhase(
                                        basePhase: JARVISNeuralCoreMotion.continuousSynchronizedBasePhase,
                                        frameIndex: index,
                                        frameCount: layout.continuousFrameCount
                                    ),
                                    layerSet: .phaseArtwork
                                )
                                .mask {
                                    JARVISWidgetTimerFrameWindow(
                                        frameIndex: index,
                                        frameCount: layout.continuousFrameCount,
                                        extent: extent
                                    )
                                    .frame(
                                        width: geometry.size.width,
                                        height: geometry.size.height
                                    )
                                }
                            }
                        }

                        // Both surfaces draw the phase-independent wordmark once at
                        // the same final z-position as the complete artwork.
                        JARVISNeuralCoreWordmark(layout: layout)
                            .accessibilityHidden(true)
                    }
                }
            } else {
                JARVISNeuralCoreArtwork(
                    telemetry: telemetry,
                    layout: layout,
                    motionPhase: basePhase,
                    allowsMotion: allowsMotion,
                    hidesAccessibility: true
                )
            }
        }
        // A timeline replacement, reduced-luminance transition, Reduce Motion
        // transition, or font-state change receives a distinct selector identity.
        // Returning from Watch Always-On therefore reconstructs the live timer
        // masks instead of reusing a suspended archived subtree.
        .id(
            JARVISNeuralCoreSelectorGeneration(
                timelineGeneration: selectorGeneration,
                decision: decision
            )
        )
        .background {
            JARVISNeuralCoreMotionDiagnostic(
                layout: layout,
                timelineGeneration: selectorGeneration,
                decision: decision,
                telemetrySignalLost: telemetry.signalLost
            )
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(JARVISNeuralCoreAccessibility.label(for: telemetry))
        .accessibilityHint(JARVISNeuralCoreAccessibility.hint(for: layout))
    }
}

private struct JARVISNeuralCoreSelectorGeneration: Hashable {
    let timelineGeneration: TimeInterval
    let decision: JARVISNeuralCoreContinuousMotionDecision
}

private struct JARVISNeuralCoreMotionDiagnostic: View {
    private static let logger = Logger(
        subsystem: "com.operation-jarvis.jarvis.widgets",
        category: "motion-decision"
    )

    init(
        layout: JARVISNeuralCoreLayout,
        timelineGeneration: TimeInterval,
        decision: JARVISNeuralCoreContinuousMotionDecision,
        telemetrySignalLost: Bool
    ) {
        let surface = layout == .watch ? "watch" : "phone"
        Self.logger.debug(
            "Neural Core render surface=\(surface, privacy: .public) generation=\(Int(timelineGeneration), privacy: .public) decision=\(decision.rawValue, privacy: .public) telemetrySignalLost=\(telemetrySignalLost, privacy: .public)"
        )
    }

    var body: some View {
        EmptyView()
    }
}

private struct JARVISNeuralCoreAnimationFrame: View {
    let telemetry: JARVISNeuralCoreTelemetry
    let layout: JARVISNeuralCoreLayout
    let motionPhase: Double
    let layerSet: JARVISNeuralCoreArtworkLayerSet

    var body: some View {
        JARVISNeuralCoreFrameArtwork(
            telemetry: telemetry,
            layout: layout,
            motionPhase: motionPhase,
            layerSet: layerSet
        )
    }
}

private struct JARVISWidgetTimerFrameWindow: View {
    let frameIndex: Int
    let frameCount: Int
    let extent: CGFloat

    private var frameDuration: TimeInterval {
        JARVISNeuralCoreMotion.continuousFrameDuration(frameCount: frameCount)
    }

    private var start: Date {
        JARVISNeuralCoreMotion.continuousReferenceDate.addingTimeInterval(
            Double(frameIndex) * frameDuration
        )
    }

    private var end: Date {
        start.addingTimeInterval(frameDuration)
    }

    var body: some View {
        JARVISWidgetTimerBlink(date: start, extent: extent)
            .mask {
                // The alternating font changes every second. Offsetting the
                // second mask to just before the next edge narrows the overlap
                // to this frame's fraction of the two-second cycle.
                JARVISWidgetTimerBlink(
                    date: end.addingTimeInterval(-0.99),
                    extent: extent
                )
            }
            .accessibilityHidden(true)
    }
}

private struct JARVISWidgetTimerBlink: View {
    let date: Date
    let extent: CGFloat

    var body: some View {
        Text(date, style: .timer)
            .font(.custom(JARVISWidgetTimerAnimationFont.postScriptName, size: extent))
            .foregroundStyle(.white)
            .lineLimit(1)
            .multilineTextAlignment(.trailing)
            .truncationMode(.head)
            .dynamicTypeSize(.large)
            .frame(width: 2.5 * extent, height: extent, alignment: .trailing)
            .fixedSize()
            .frame(width: extent, alignment: .trailing)
            .clipped()
            .accessibilityHidden(true)
    }
}
