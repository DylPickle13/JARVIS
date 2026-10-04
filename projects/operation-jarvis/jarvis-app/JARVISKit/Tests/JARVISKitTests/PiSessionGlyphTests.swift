import XCTest
@testable import JARVISKit

final class PiSessionGlyphTests: XCTestCase {
    private let states: [PiSessionLifecycle] = [.running, .compacting, .idle, .new, .offline, .unknown]

    func testBothBusyStatesUseTheSameForwardPiSequenceAndCadence() {
        let expected = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        XCTAssertEqual(PiSessionGlyphs.busyFrames, expected)
        XCTAssertEqual(PiSessionGlyphs.frameInterval, 0.08)
        for state in [PiSessionLifecycle.running, .compacting] {
            for cycle in [0, 1, 100, 108_000] {
                for (index, frame) in expected.enumerated() {
                    let time = (Double(cycle * expected.count + index) + 0.5) * 0.08
                    XCTAssertEqual(PiSessionGlyphs.glyph(lifecycle: state, time: time, animating: true), frame)
                }
            }
        }
    }

    func testFrameBoundariesAndWrapAround() {
        for state in [PiSessionLifecycle.running, .compacting] {
            for (time, expected) in [(0.0, "⠋"), (0.079, "⠋"), (0.08, "⠙"),
                                     (0.719, "⠇"), (0.721, "⠏"), (0.799, "⠏"),
                                     (0.8, "⠋"), (0.881, "⠙")] {
                XCTAssertEqual(PiSessionGlyphs.glyph(lifecycle: state, time: time, animating: true), expected)
            }
        }
    }

    func testStaticStatesHaveDistinctShapesAndNeverAnimate() {
        let expected: [(PiSessionLifecycle, String)] = [(.idle, "●"), (.new, "○"), (.offline, "×"), (.unknown, "?")]
        for (state, glyph) in expected {
            XCTAssertFalse(PiSessionGlyphs.isBusy(state))
            for time in [0.0, 0.08, 0.72, 86_400, .nan, .infinity] {
                XCTAssertEqual(PiSessionGlyphs.glyph(lifecycle: state, time: time, animating: true), glyph)
            }
        }
        XCTAssertEqual(Set(expected.map(\.1)).count, 4)
    }

    func testInactiveAndReducedMotionBusyGlyphsAreRecognisableAndStatic() {
        for state in [PiSessionLifecycle.running, .compacting] {
            XCTAssertTrue(PiSessionGlyphs.isBusy(state))
            for time in [0.0, 0.08, 0.72, 86_400] {
                XCTAssertEqual(PiSessionGlyphs.glyph(lifecycle: state, time: time), "⠋")
            }
            XCTAssertNotEqual(PiSessionGlyphs.glyph(lifecycle: state), PiSessionGlyphs.glyph(lifecycle: .idle))
        }
    }

    func testInvalidAndExtremeTimeIsBoundedWithoutIntegerOverflow() {
        for state in [PiSessionLifecycle.running, .compacting] {
            for time in [-1.0, -.infinity, .infinity, .nan] {
                XCTAssertEqual(PiSessionGlyphs.glyph(lifecycle: state, time: time, animating: true), "⠋")
            }
            XCTAssertTrue(PiSessionGlyphs.busyFrames.contains(
                PiSessionGlyphs.glyph(lifecycle: state, time: .greatestFiniteMagnitude, animating: true)))
        }
    }

    func testOnlyVisibleBusyInteractiveNonReducedMotionScenesAnimate() {
        for state in states {
            for active in [false, true] {
                for sceneActive in [false, true] {
                    for reduceMotion in [false, true] {
                        for dimmed in [false, true] {
                            let expected = [.running, .compacting].contains(state)
                                && active && sceneActive && !reduceMotion && !dimmed
                            XCTAssertEqual(PiSessionGlyphs.animates(lifecycle: state, active: active,
                                sceneActive: sceneActive, reduceMotion: reduceMotion,
                                luminanceReduced: dimmed), expected)
                        }
                    }
                }
            }
        }
    }
}
