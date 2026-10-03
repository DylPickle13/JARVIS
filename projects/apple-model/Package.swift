// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "apple-model",
    platforms: [.macOS("27.0")],
    products: [.executable(name: "apple-model", targets: ["AppleModel"])],
    targets: [.executableTarget(name: "AppleModel")]
)
