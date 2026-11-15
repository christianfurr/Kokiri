// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Kokiri",
    platforms: [.macOS("26.0")],
    products: [.executable(name: "Kokiri", targets: ["Kokiri"])],
    targets: [
        .binaryTarget(name: "Sparkle", path: ".build/vendor/Sparkle.xcframework"),
        .target(name: "KokiriSupport", publicHeadersPath: "include"),
        .target(name: "KokiriCore", dependencies: ["KokiriSupport"]),
        .executableTarget(name: "Kokiri", dependencies: ["KokiriCore", "Sparkle"]),
        .testTarget(name: "KokiriCoreTests", dependencies: ["KokiriCore"])
    ],
    swiftLanguageModes: [.v5]
)
