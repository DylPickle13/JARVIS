import XCTest
@testable import JARVISKit

final class InteractionMotionTests: XCTestCase {
    func testPressOnlyScalesEligibleEnabledInput() {
        for active in [false, true] {
            for foreground in [false, true] {
                for reduced in [false, true] {
                    for dimmed in [false, true] {
                        let allowed = ActivityMotionGate.allows(active: active, sceneActive: foreground,
                            reduceMotion: reduced, luminanceReduced: dimmed)
                        XCTAssertEqual(InteractionMotionPolicy.pressScale(pressed: false, allowed: allowed), 1)
                        XCTAssertEqual(InteractionMotionPolicy.pressScale(pressed: true, allowed: allowed),
                            active && foreground && !reduced && !dimmed ? 0.98 : 1)
                    }
                }
            }
        }
    }
}
