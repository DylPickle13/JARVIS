// swift-tools-version: 6.2

import PackageDescription

let package = Package(
    name: "JarvisAppleASR",
    platforms: [
        .macOS(.v26),
    ],
    products: [
        .executable(name: "jarvis-apple-asr", targets: ["JarvisAppleASR"]),
    ],
    targets: [
        .executableTarget(name: "JarvisAppleASR"),
    ]
)
