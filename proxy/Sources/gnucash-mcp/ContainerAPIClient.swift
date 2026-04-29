import Foundation

enum ContainerError: Error, CustomStringConvertible {
    case launchFailed(Error)
    case noResponse
    case containerExitedWithError(Int32, String)
    case imageNotFound(String)
    case containerSystemNotRunning

    var description: String {
        switch self {
        case let .launchFailed(e): "Container launch failed: \(e)"
        case .noResponse: "Container produced no response on stdout"
        case let .containerExitedWithError(code, stderr):
            "Container exited with status \(code): \(stderr)"
        case let .imageNotFound(image):
            "Container image '\(image)' not found. Run: mise build"
        case .containerSystemNotRunning:
            "Container system is not running. Run: container system start"
        }
    }
}

/// One pre-started container process waiting for a single JSON-RPC request.
/// The Python worker does sys.stdin.buffer.read() then exits — it blocks until
/// stdin is closed, so we can pre-start it and send the request later.
final class ContainerAPIClient: Sendable {
    private let process: Process
    private let stdinPipe: Pipe
    private let stdoutPipe: Pipe
    private let stderrPipe: Pipe

    private static let imageName = "gnucash-mcp:latest"
    private static let mountPath = "/Volumes/GnuCash-Project"
    private static let bookPath = "/data/project.gnucash"

    init() throws {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/local/bin/container")
        proc.arguments = [
            "run", "--rm", "-i",
            "-v", "\(ContainerAPIClient.mountPath):/data:rw",
            "-e", "GNUCASH_BOOK_PATH=\(ContainerAPIClient.bookPath)",
            ContainerAPIClient.imageName,
        ]
        let stdin = Pipe()
        let stdout = Pipe()
        let stderr = Pipe()
        proc.standardInput = stdin
        proc.standardOutput = stdout
        proc.standardError = stderr

        do {
            try proc.run()
        } catch {
            throw ContainerError.launchFailed(error)
        }

        process = proc
        stdinPipe = stdin
        stdoutPipe = stdout
        stderrPipe = stderr
    }

    /// Send request JSON, close stdin, read response. Container exits after one round-trip.
    func roundTrip(request: Data) throws -> Data {
        stdinPipe.fileHandleForWriting.write(request)
        try stdinPipe.fileHandleForWriting.close()

        let responseData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
        let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        let status = process.terminationStatus
        if status != 0 {
            let msg = String(data: stderrData, encoding: .utf8) ?? ""
            throw ContainerError.containerExitedWithError(status, msg)
        }
        guard !responseData.isEmpty else {
            throw ContainerError.noResponse
        }
        return responseData
    }

    /// Check if the pre-started process is still alive (for sleep/wake recovery KU-11).
    var isAlive: Bool {
        process.isRunning
    }

    func terminate() {
        if process.isRunning {
            process.terminate()
        }
    }
}

// MARK: - Container system management

// TODO: Replace Process-based CLI calls with ContainerKit SDK calls when the
// macOS 26 framework API is documented. The SDK approach avoids spawning a shell
// and allows querying container system state programmatically.
enum ContainerSystem {
    static func ensureRunning() throws {
        let status = Process()
        status.executableURL = URL(fileURLWithPath: "/usr/local/bin/container")
        status.arguments = ["system", "status"]
        status.standardOutput = FileHandle.nullDevice
        status.standardError = FileHandle.nullDevice
        try status.run()
        status.waitUntilExit()

        if status.terminationStatus != 0 {
            let start = Process()
            start.executableURL = URL(fileURLWithPath: "/usr/local/bin/container")
            start.arguments = ["system", "start"]
            start.standardOutput = FileHandle.nullDevice
            start.standardError = FileHandle.nullDevice
            try start.run()
            start.waitUntilExit()
            if start.terminationStatus != 0 {
                throw ContainerError.containerSystemNotRunning
            }
        }
    }

    static func imageExists(_ name: String) throws -> Bool {
        let inspect = Process()
        inspect.executableURL = URL(fileURLWithPath: "/usr/local/bin/container")
        inspect.arguments = ["image", "inspect", name]
        inspect.standardOutput = FileHandle.nullDevice
        inspect.standardError = FileHandle.nullDevice
        try inspect.run()
        inspect.waitUntilExit()
        return inspect.terminationStatus == 0
    }
}
