import SwiftUI
import JARVISKit

#if os(iOS)
import UIKit
#endif

enum JARVISWidgetTheme {
    #if os(iOS)
    static let accent = Color(uiColor: UIColor { traits in
        UIColor(jarvisRGB: traits.userInterfaceStyle == .dark
            ? JARVISBrandTheme.darkAccent
            : JARVISBrandTheme.lightAccent)
    })
    #else
    static let accent = Color(jarvisRGB: JARVISBrandTheme.darkAccent)
    #endif
}

private extension Color {
    init(jarvisRGB value: JARVISBrandRGB) {
        self.init(
            red: value.normalizedRed,
            green: value.normalizedGreen,
            blue: value.normalizedBlue
        )
    }
}

#if os(iOS)
private extension UIColor {
    convenience init(jarvisRGB value: JARVISBrandRGB) {
        self.init(
            red: value.normalizedRed,
            green: value.normalizedGreen,
            blue: value.normalizedBlue,
            alpha: 1
        )
    }
}
#endif
