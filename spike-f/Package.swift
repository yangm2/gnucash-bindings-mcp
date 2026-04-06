// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "spike-f",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-nio.git", from: "2.65.0"),
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.3.0"),
    ],
    targets: [
        .executableTarget(
            name: "spike-f",
            dependencies: [
                .product(name: "NIO", package: "swift-nio"),
                .product(name: "NIOHTTP1", package: "swift-nio"),
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
            ]
        ),
    ]
)
