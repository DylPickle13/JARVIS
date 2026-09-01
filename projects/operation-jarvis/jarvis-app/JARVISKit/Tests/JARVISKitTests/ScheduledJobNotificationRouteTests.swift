import XCTest
@testable import JARVISKit

final class ScheduledJobNotificationRouteTests: XCTestCase {
    private let base: [String: JSONValue] = [
        "route": .string("scheduled-job-result"),
        "routeVersion": .number(1),
    ]

    func testAcceptsOnlyFixedRouteVersionAndPositiveOpaqueResultSequence() {
        XCTAssertEqual(
            ScheduledJobNotificationRoute(payload: base.merging(["resultSequence": .string("41")]) { _, new in new })?.resultSequence,
            41
        )
        XCTAssertEqual(
            ScheduledJobNotificationRoute(payload: base.merging(["resultSequence": .number(42)]) { _, new in new })?.resultSequence,
            42
        )
        XCTAssertNil(ScheduledJobNotificationRoute(payload: ["resultSequence": .string("41")]))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: base.merging(["routeVersion": .number(2)]) { _, new in new }))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: base.merging(["route": .string("private")]) { _, new in new }))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: base.merging(["resultSequence": .string("0")]) { _, new in new }))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: base.merging(["resultSequence": .string("result output")]) { _, new in new }))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: base.merging(["resultSequence": .number(1.5)]) { _, new in new }))
        XCTAssertNil(ScheduledJobNotificationRoute(payload: base.merging(["output": .string("private")]) { _, new in new }))
    }

    func testRegistrationEnvelopeRejectsInvalidTokensAndDeactivationTokens() throws {
        let installation = "123e4567-e89b-42d3-a456-426614174000"
        let registration = try XCTUnwrap(
            JARVISPushRegistration(
                action: .register,
                platform: .watch,
                environment: .development,
                installationID: installation,
                deviceToken: String(repeating: "ab", count: 32)
            )
        )
        XCTAssertTrue(registration.isValid)
        XCTAssertEqual(registration.platform.topic, "com.operation-jarvis.jarvis.watchkitapp")
        XCTAssertNil(
            JARVISPushRegistration(
                action: .register,
                platform: .iphone,
                environment: .development,
                installationID: installation,
                deviceToken: "not-a-token"
            )
        )
        XCTAssertNil(
            JARVISPushRegistration(
                action: .deactivate,
                platform: .iphone,
                environment: .development,
                installationID: installation,
                deviceToken: String(repeating: "ab", count: 32)
            )
        )
    }
}
