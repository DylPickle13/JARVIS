import XCTest
@testable import JARVISKit

final class ScheduledJobNotificationRouteTests: XCTestCase {
    func testAcceptsOnlyPositiveOpaqueResultSequence() {
        XCTAssertEqual(
            ScheduledJobNotificationRoute(payload: ["resultSequence": .string("41")])?.resultSequence,
            41
        )
        XCTAssertEqual(
            ScheduledJobNotificationRoute(payload: ["resultSequence": .number(42)])?.resultSequence,
            42
        )
        XCTAssertNil(ScheduledJobNotificationRoute(payload: ["resultSequence": .string("0")]))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: ["resultSequence": .string("result output")]))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: ["resultSequence": .number(1.5)]))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: ["output": .string("private")]))
    }
}
