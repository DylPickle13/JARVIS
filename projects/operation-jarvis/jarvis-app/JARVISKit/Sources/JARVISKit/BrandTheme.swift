import Foundation

/// Target-neutral colour tokens for JARVIS-owned interface chrome.
///
/// The values mirror Pi's built-in `thinkingXhigh` colours. Platform targets
/// convert them to SwiftUI colours without coupling JARVISKit to SwiftUI.
public struct JARVISBrandRGB: Equatable, Sendable {
    public let red: UInt8
    public let green: UInt8
    public let blue: UInt8

    public init(red: UInt8, green: UInt8, blue: UInt8) {
        self.red = red
        self.green = green
        self.blue = blue
    }

    public var normalizedRed: Double { Double(red) / 255 }
    public var normalizedGreen: Double { Double(green) / 255 }
    public var normalizedBlue: Double { Double(blue) / 255 }
}

public enum JARVISBrandTheme {
    /// Pi dark theme `thinkingXhigh`: #D183E8.
    public static let darkAccent = JARVISBrandRGB(red: 209, green: 131, blue: 232)

    /// Pi light theme `thinkingXhigh`: #8B008B.
    public static let lightAccent = JARVISBrandRGB(red: 139, green: 0, blue: 139)
}
