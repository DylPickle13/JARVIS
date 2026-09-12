import AppKit
import SwiftUI
import JARVISKit

/// Exercise actual shared widget artwork without loading a WidgetKit extension,
/// contacting a service, or changing native accessibility settings.
@main struct NeuralCoreRenderChecks {
    @MainActor static func main() throws {
        let output = URL(fileURLWithPath: CommandLine.arguments[1])
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        var assertions = 0
        func check(_ condition: Bool, _ message: String) {
            if !condition {
                fputs("FAIL: \(message)\n", stderr)
                exit(1)
            }
            assertions += 1
        }
        func pixels(_ image: CGImage) -> [UInt8] {
            var bytes = [UInt8](repeating: 0, count: image.width * image.height * 4)
            bytes.withUnsafeMutableBytes { raw in
                let context = CGContext(data: raw.baseAddress, width: image.width, height: image.height, bitsPerComponent: 8, bytesPerRow: image.width*4, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
            }
            return bytes
        }
        func difference(_ lhs: [UInt8], _ rhs: [UInt8]) -> Double {
            zip(lhs, rhs).reduce(0.0) { $0 + Double(abs(Int($1.0)-Int($1.1))) } / Double(lhs.count)
        }
        func save(_ image: CGImage, _ name: String) throws {
            try NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent(name + ".png"))
        }
        @MainActor func render<V: View>(_ view: V, size: CGSize) -> CGImage {
            let renderer = ImageRenderer(content: view.frame(width: size.width, height: size.height).environment(\.colorScheme, .dark))
            renderer.scale = 2
            guard let image = renderer.cgImage else { preconditionFailure("Missing native render") }
            check(image.width == Int(size.width*2) && image.height == Int(size.height*2), "Changed widget footprint")
            return image
        }
        let states = [JARVISNeuralCoreTelemetry(cached: nil, placeholder: true), JARVISNeuralCoreTelemetry(cached: nil)]
        for (name, layout, size) in [
            ("iphone", JARVISNeuralCoreLayout.phone, CGSize(width: 360, height: 170)),
            ("iphone-small", .phone, CGSize(width: 329, height: 155)),
            ("watch", .watch, CGSize(width: 172, height: 76)),
            ("watch-small", .watch, CGSize(width: 150, height: 64))
        ] {
            for (stateIndex, telemetry) in states.enumerated() {
                for phase in [0.0, 0.19, 0.50, 0.81] {
                    let complete = render(ZStack {
                        Color.black
                        JARVISNeuralCoreArtwork(telemetry: telemetry, layout: layout, motionPhase: phase, allowsMotion: true)
                    }, size: size)
                    let split = render(ZStack(alignment: .topLeading) {
                        Color.black
                        JARVISNeuralCoreFrameArtwork(telemetry: telemetry, layout: layout, motionPhase: phase, layerSet: .staticBackground)
                        JARVISNeuralCoreFrameArtwork(telemetry: telemetry, layout: layout, motionPhase: phase, layerSet: .phaseArtwork)
                        JARVISNeuralCoreFrameArtwork(telemetry: telemetry, layout: layout, motionPhase: phase, layerSet: .staticForeground)
                        JARVISNeuralCoreWordmark(layout: layout)
                    }, size: size)
                    let delta = difference(pixels(complete), pixels(split))
                    check(delta < 1.5, "Split/complete compositing mismatch \(name): \(delta)")
                    if stateIndex == 0 && phase == 0.19 { try save(complete, name + "-c2-vibrant") }
                }
            }
            let frozenA = render(JARVISNeuralCoreArtwork(telemetry: states[0], layout: layout, motionPhase: 0, allowsMotion: false), size: size)
            let frozenB = render(JARVISNeuralCoreArtwork(telemetry: states[0], layout: layout, motionPhase: 0.81, allowsMotion: false), size: size)
            check(pixels(frozenA) == pixels(frozenB), "Disabled motion must remain phase-independent")
            try save(frozenA, name + "-static")
            for layer in [JARVISNeuralCoreArtworkLayerSet.staticBackground, .staticForeground] {
                let a = render(JARVISNeuralCoreFrameArtwork(telemetry: states[0], layout: layout, motionPhase: 0, layerSet: layer), size: size)
                let b = render(JARVISNeuralCoreFrameArtwork(telemetry: states[1], layout: layout, motionPhase: 0.81, layerSet: layer), size: size)
                check(pixels(a) == pixels(b), "Hoisted C2 decoration must not vary with phase or freshness")
            }
            // Dominance concerns the full visible core, not just its added shell.
            let visibleCore = render(ZStack {
                Color.black
                JARVISNeuralCoreFrameArtwork(telemetry: states[0], layout: layout, motionPhase: 0.19, layerSet: .complete)
            }, size: size)
            for fullColor in [true, false] {
                let beams = render(Decoration(shell: false, fullColor: fullColor), size: size)
                let shell = render(Decoration(shell: true, fullColor: fullColor), size: size)
                for image in [beams, shell] {
                    let data = pixels(image)
                    var channelSpread = 0
                    for index in stride(from: 0, to: data.count, by: 4) {
                        let red = Int(data[index]), green = Int(data[index+1]), blue = Int(data[index+2])
                        channelSpread = max(channelSpread, max(red, green, blue) - min(red, green, blue))
                    }
                    // SwiftUI gradient/blur colour conversion has small 8-bit
                    // rounding differences; this is not a native accented-mode test.
                    print("\(name) fullColor=\(fullColor) max RGB spread=\(channelSpread)")
                    check(channelSpread <= 4, "C2 monochrome render exceeded conversion tolerance: \(channelSpread)")
                }
                let beamBytes = pixels(beams), centreBytes = pixels(visibleCore)
                func mean(_ data: [UInt8], from: Int, to: Int) -> Double {
                    var sum = 0.0
                    for y in 0..<beams.height { for x in from..<to { sum += Double(data[(y*beams.width+x)*4]) } }
                    return sum / Double(beams.height*(to-from))
                }
                let w = beams.width
                let sides = max(mean(beamBytes, from: 0, to: w/3), mean(beamBytes, from: w*2/3, to: w))
                let centre = mean(centreBytes, from: w/3, to: w*2/3)
                print("\(name) fullColor=\(fullColor) centre=\(centre) sides=\(sides) centre/sides=\(centre/sides)")
                check(sides > 0.01 && centre > sides*3, "Centre must dominate non-empty sides")
            }
        }
        print("PASS: \(assertions) Neural Core native-render assertions; footprints, layers, static fallback, phase/freshness invariance, monochrome palette and centre dominance. Native OS/animation/energy acceptance remains separate.")
    }
}

private struct Decoration: View {
    let shell: Bool
    let fullColor: Bool
    var body: some View {
        ZStack {
            Color.black
            Canvas { context, size in
                let r = min(size.height*0.325, size.width*0.22)
                let palette = JARVISNeuralCoreC2Decoration.Palette(usesFullColor: fullColor)
                if shell {
                    JARVISNeuralCoreC2Decoration.drawShell(context: &context, center: CGPoint(x: size.width/2, y: size.height/2), radius: r, palette: palette)
                } else {
                    JARVISNeuralCoreC2Decoration.drawBeams(context: &context, size: size, radius: r, palette: palette)
                }
            }
        }
    }
}
