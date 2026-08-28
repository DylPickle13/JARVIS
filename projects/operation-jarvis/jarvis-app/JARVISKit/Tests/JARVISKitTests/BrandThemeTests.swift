import XCTest
@testable import JARVISKit

final class BrandThemeTests: XCTestCase {
    func testXHighThemeMatchesPiBuiltInPalettes() {
        XCTAssertEqual(JARVISBrandTheme.darkAccent, JARVISBrandRGB(red: 209, green: 131, blue: 232))
        XCTAssertEqual(JARVISBrandTheme.lightAccent, JARVISBrandRGB(red: 139, green: 0, blue: 139))
    }

    func testAdaptiveAccentHasAccessibleContrast() {
        XCTAssertGreaterThanOrEqual(contrast(JARVISBrandTheme.darkAccent, .black), 7)
        XCTAssertGreaterThanOrEqual(contrast(JARVISBrandTheme.lightAccent, .white), 7)
    }

    private func contrast(_ first: JARVISBrandRGB, _ second: JARVISBrandRGB) -> Double {
        let brighter = max(luminance(first), luminance(second))
        let darker = min(luminance(first), luminance(second))
        return (brighter + 0.05) / (darker + 0.05)
    }

    private func luminance(_ color: JARVISBrandRGB) -> Double {
        func linear(_ component: Double) -> Double {
            component <= 0.04045
                ? component / 12.92
                : pow((component + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linear(color.normalizedRed)
            + 0.7152 * linear(color.normalizedGreen)
            + 0.0722 * linear(color.normalizedBlue)
    }
}

private extension JARVISBrandRGB {
    static let black = JARVISBrandRGB(red: 0, green: 0, blue: 0)
    static let white = JARVISBrandRGB(red: 255, green: 255, blue: 255)
}
