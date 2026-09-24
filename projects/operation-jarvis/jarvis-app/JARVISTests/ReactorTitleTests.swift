import XCTest
import SwiftUI
@testable import JARVIS

final class ReactorTitleTests: XCTestCase {
    func testIgnitionSettlesWithoutRepeatedFlashes() {
        XCTAssertEqual(ReactorTitlePhase(elapsed: 0, animated: true).reveal, 0)
        XCTAssertEqual(ReactorTitlePhase(elapsed: 0, animated: true).flash, 1)
        for time in [1.2, 5, 30, 3600] {
            let phase = ReactorTitlePhase(elapsed: time, animated: true)
            XCTAssertEqual(phase.reveal, 1)
            XCTAssertEqual(phase.flash, 0)
            XCTAssertTrue((0.19...0.51).contains(phase.glow))
        }
    }

    func testReducedMotionAndInactiveAreStatic() {
        for time in [0.0, 0.5, 30] {
            let phase = ReactorTitlePhase(elapsed: time, animated: false)
            XCTAssertEqual(phase.reveal, 1)
            XCTAssertEqual(phase.flash, 0)
            XCTAssertEqual(phase.glow, 0.3)
            XCTAssertEqual(phase.energy, 0)
        }
    }

    func testEnergyKeepsCyclingAfterIgnition() {
        for cycle in [0.0, 1, 10, 100] {
            let start = 1.2 + cycle * 3.6
            XCTAssertEqual(ReactorTitlePhase(elapsed: start, animated: true).energy, 0, accuracy: 0.0001)
            XCTAssertEqual(ReactorTitlePhase(elapsed: start + 1.8, animated: true).energy, 0.85, accuracy: 0.0001)
            XCTAssertEqual(ReactorTitlePhase(elapsed: start + 3.6, animated: true).energy, 0, accuracy: 0.0001)
        }
    }

    func testStatusStaysOutsideCenteredTitle() {
        XCTAssertEqual(ReactorHeaderLayout.statusWidth(headerWidth: 358, titleWidth: 140), 97)
        XCTAssertEqual(ReactorHeaderLayout.statusWidth(headerWidth: 200, titleWidth: 220), 0)
    }

    func testNeuralCoreUsesWidgetTwoSecondCycle() {
        XCTAssertEqual(ReactorNeuralCore.phase(time: -1), 0)
        XCTAssertEqual(ReactorNeuralCore.phase(time: 0.5), 0.25)
        XCTAssertEqual(ReactorNeuralCore.phase(time: 1), 0.5)
        XCTAssertEqual(ReactorNeuralCore.phase(time: 2), 0)
        XCTAssertEqual(ReactorNeuralCore.phase(time: 100.5), 0.25)
    }

    @MainActor func testFullWidthCorePreview() throws {
        let header = ReactorHeaderLayout {
            ReactorTitle(connected: true, active: false)
            Text("")
        }
        .frame(width: 358, height: 84)
        .background { ReactorNeuralCore(time: 0.5, energy: 0.7) }
        .background(Color.black)
        .environment(\.colorScheme, .dark)
        let renderer = ImageRenderer(content: header)
        renderer.scale = 3
        let image = try XCTUnwrap(renderer.uiImage)
        XCTAssertEqual(image.size.width, 358)
        XCTAssertEqual(image.size.height, 84)
        try XCTUnwrap(image.pngData()).write(to: URL(fileURLWithPath: "/tmp/jarvis-header-core-preview.png"))
    }

    @MainActor func testEnlargedTitleFitsExistingHeader() {
        let original = UIHostingController(rootView: Text("JARVIS").font(ReactorTitle.titleFont))
        let reactor = UIHostingController(rootView: ReactorTitle(connected: true, active: false))
        let proposal = CGSize(width: 390, height: 100)
        let expected = original.sizeThatFits(in: proposal)
        let actual = reactor.sizeThatFits(in: proposal)
        XCTAssertLessThanOrEqual(actual.height, 84)
        XCTAssertLessThan(actual.width, 300)
        XCTAssertGreaterThan(actual.height, 50)
        XCTAssertEqual(actual.width, expected.width, accuracy: 0.5)
        XCTAssertEqual(actual.height, expected.height, accuracy: 0.5)
    }
}
