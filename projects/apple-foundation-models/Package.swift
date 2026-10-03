// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "apple-foundation-models",
    platforms: [.macOS("27.0")],
    products: [.executable(name: "apple-model", targets: ["AppleModel"])],
    targets: [.executableTarget(name: "AppleModel")]
)
