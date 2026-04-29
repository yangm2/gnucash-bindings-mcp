// swift-tools-version: 6.3
// When bumping the `container` package version, also update:
//   - README.md  Prerequisites table ("Apple Container" minimum version row)
//   - worker/Dockerfile  FROM ubuntu line (if the GnuCash universe version changes)
import PackageDescription

let package = Package(
    name: "gnucash-mcp",
    platforms: [.macOS(.v26)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.7.1"),
        .package(url: "https://github.com/apple/swift-nio.git", from: "2.99.0"),
        .package(url: "https://github.com/apple/container.git", exact: "0.12.1"),
    ],
    targets: [
        .executableTarget(
            name: "gnucash-mcp",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                .product(name: "NIO", package: "swift-nio"),
                .product(name: "ContainerAPIClient", package: "container"),
                .product(name: "ContainerResource", package: "container"),
            ],
            path: "Sources/gnucash-mcp",
        ),
        .testTarget(
            name: "gnucash-mcpTests",
            dependencies: [
                "gnucash-mcp",
                .product(name: "ContainerResource", package: "container"),
            ],
            path: "Tests/gnucash-mcpTests",
        ),
    ],
)
