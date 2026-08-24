import CoreText
import Foundation
import SwiftUI
import JARVISKit

/// Registers the tiny alternating-glyph font used only as an alpha mask. The
/// Cathedral frames themselves remain native procedural SwiftUI geometry.
enum JARVISWidgetTimerAnimationFont {
    static let postScriptName = "FillRect-Regular"
    static let resourceName = "FillRect-Regular"
    static let resourceExtension = "otf"

    @discardableResult
    static func register() -> Bool {
        guard let url = Bundle.main.url(
            forResource: resourceName,
            withExtension: resourceExtension
        ) else {
            return false
        }

        if isAvailable {
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
        return registered || isAvailable
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

    @Environment(\.isLuminanceReduced) private var isLuminanceReduced
    @Environment(\.accessibilityReduceMotion) private var accessibilityReduceMotion

    private var usesContinuousFrames: Bool {
        allowsMotion
            && !telemetry.signalLost
            && !isLuminanceReduced
            && !accessibilityReduceMotion
            && JARVISWidgetTimerAnimationFont.isAvailable
    }

    var body: some View {
        Group {
            if usesContinuousFrames {
                GeometryReader { geometry in
                    let extent = max(1, max(geometry.size.width, geometry.size.height))

                    ZStack {
                        ForEach(0..<layout.continuousFrameCount, id: \.self) { index in
                            JARVISNeuralCoreArtwork(
                                telemetry: telemetry,
                                layout: layout,
                                motionPhase: JARVISNeuralCoreMotion.continuousPhase(
                                    basePhase: basePhase,
                                    frameIndex: index,
                                    frameCount: layout.continuousFrameCount
                                ),
                                allowsMotion: true,
                                hidesAccessibility: true
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
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(JARVISNeuralCoreAccessibility.label(for: telemetry))
        .accessibilityHint(JARVISNeuralCoreAccessibility.hint(for: layout))
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
