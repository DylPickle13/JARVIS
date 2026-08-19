// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "JARVISKit",
    platforms: [
        .macOS(.v13), // local `swift test` only; app targets are iOS/watchOS
        .iOS(.v17),
        .watchOS(.v10),
    ],
    products: [
        .library(name: "JARVISKit", targets: ["JARVISKit"]),
    ],
    targets: [
        .target(name: "JARVISKit"),
        .testTarget(name: "JARVISKitTests", dependencies: ["JARVISKit"]),
    ]
)
