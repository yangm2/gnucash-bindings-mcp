import Foundation

enum SparsebundleError: Error, CustomStringConvertible {
    case attachFailed(Int32)
    case detachFailed(Int32)
    case bundleNotFound(String)

    var description: String {
        switch self {
        case let .attachFailed(code): "hdiutil attach exited with status \(code)"
        case let .detachFailed(code): "hdiutil detach exited with status \(code)"
        case let .bundleNotFound(path): "Sparsebundle not found at \(path)"
        }
    }
}

struct SparsebundleManager {
    let bundlePath: String
    let mountPoint: String

    init(
        bundlePath: String = "\(NSHomeDirectory())/books/project.sparsebundle",
        mountPoint: String = "/Volumes/GnuCash-Project",
    ) {
        self.bundlePath = bundlePath
        self.mountPoint = mountPoint
    }

    var bookURL: URL {
        URL(fileURLWithPath: "\(mountPoint)/project.gnucash")
    }

    var isMounted: Bool {
        FileManager.default.fileExists(atPath: mountPoint)
    }

    func attachIfNeeded() throws {
        guard !isMounted else { return }
        guard FileManager.default.fileExists(atPath: bundlePath) else {
            throw SparsebundleError.bundleNotFound(bundlePath)
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/hdiutil")
        process.arguments = ["attach", "-readwrite", "-nobrowse", bundlePath]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw SparsebundleError.attachFailed(process.terminationStatus)
        }
    }

    func detach() throws {
        guard isMounted else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/hdiutil")
        process.arguments = ["detach", mountPoint]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw SparsebundleError.detachFailed(process.terminationStatus)
        }
    }
}
