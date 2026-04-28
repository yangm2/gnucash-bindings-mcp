// swift-tools-version: 6.3
import PackageDescription

let package = Package(
    name: "gnucash-mcp",
    platforms: [.macOS(.v26)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.3.0"),
        .package(url: "https://github.com/apple/swift-nio.git", from: "2.65.0")
    ],
    targets: [
        .executableTarget(
            name: "gnucash-mcp",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                .product(name: "NIO", package: "swift-nio")
            ],
            path: "Sources/gnucash-mcp",
        ),
        .testTarget(
            name: "gnucash-mcpTests",
            dependencies: ["gnucash-mcp"],
            path: "Tests/gnucash-mcpTests",
        )
    ],
)
