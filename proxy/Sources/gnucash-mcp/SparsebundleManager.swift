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

    /// Fallback when the MCP client does not support the roots protocol.
    static let defaultBundlePath =
        URL.homeDirectory.appending(components: "books", "project.sparsebundle").path

    init(bundlePath: String, mountPoint: String = "/Volumes/GnuCash-Project") {
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
        if isMounted {
            slog("sparsebundle: already mounted at \(mountPoint)\n")
            return
        }
        guard FileManager.default.fileExists(atPath: bundlePath) else {
            throw SparsebundleError.bundleNotFound(bundlePath)
        }
        slog("sparsebundle: attaching \(bundlePath)\n")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/hdiutil")
        process.arguments = ["attach", "-readwrite", "-nobrowse", bundlePath]
        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        try process.run()
        process.waitUntilExit()
        let out = String(
            data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8,
        ) ?? ""
        let err = String(
            data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8,
        ) ?? ""
        if !out.isEmpty { slog("sparsebundle: hdiutil stdout: \(out)") }
        if !err.isEmpty { slog("sparsebundle: hdiutil stderr: \(err)") }
        guard process.terminationStatus == 0 else {
            throw SparsebundleError.attachFailed(process.terminationStatus)
        }
        slog("sparsebundle: mounted at \(mountPoint)\n")
    }

    func detach() throws {
        guard isMounted else {
            slog("sparsebundle: detach skipped — not mounted\n")
            return
        }
        slog("sparsebundle: detaching \(mountPoint)\n")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/hdiutil")
        process.arguments = ["detach", mountPoint]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            slog("sparsebundle: detach failed (status \(process.terminationStatus))\n")
            throw SparsebundleError.detachFailed(process.terminationStatus)
        }
        slog("sparsebundle: detached \(mountPoint)\n")
    }
}
