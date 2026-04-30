import ContainerAPIClient // SDK: ContainerClient (XPC), ClientImage, ClientKernel, ClientProcess
import ContainerResource // SDK: ContainerConfiguration, ProcessConfiguration, etc.
import Foundation

// MARK: - Errors

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

// MARK: - Backend and process protocols

//
// These mirror the pattern from buck2-macos-local-reapi/ContainerBackend.swift:
// thin protocols over the SDK types so ContainerPool tests can drive a mock
// without a running daemon.

/// A running init process inside a container.
protocol ManagedContainerProcess: Sendable {
    func start() async throws
    /// Waits for exit and returns the exit code.
    func wait() async throws -> Int32
    func kill(_ signal: Int32) async throws
}

/// Abstracts container-daemon interactions.
///
/// The live implementation (LiveManagedContainerBackend) talks to
/// com.apple.container.apiserver via XPC using the ContainerAPIClient SDK.
/// Tests supply a mock that drives deterministic behaviour without a daemon.
protocol ManagedContainerBackend: Sendable {
    func create(id: String, config: ContainerConfiguration) async throws
    func bootstrap(
        id: String,
        stdin: FileHandle,
        stdout: FileHandle,
        stderr: FileHandle,
    ) async throws -> any ManagedContainerProcess
    /// Force-deletes the container, stopping the VM if it is still running.
    /// Awaiting this method guarantees the VM has fully halted —
    /// safe to call sparsebundle.detach() immediately after.
    func delete(id: String) async throws
    func imageExists(_ reference: String) async throws -> Bool
}

// MARK: - Pool-level container protocol

/// A pre-started container with the Python worker blocked on stdin read,
/// ready to handle one JSON-RPC round-trip.
///
/// Lifecycle (invariants asserted by ContainerPoolTests):
///   factory call  — container created + Python worker started; blocks on stdin.read()
///   roundTrip()   — write request → close stdin → read response → await exit → delete
///   terminate()   — force-stop and delete; returns only after VM has fully halted
///
/// Only one of roundTrip() or terminate() is ever called on a given instance.
protocol PooledContainer: Sendable {
    var id: String { get }
    /// False if the Python worker exited unexpectedly (e.g. after sleep/wake; KU-11).
    var isAlive: Bool { get async }
    func roundTrip(request: Data) async throws -> Data
    func terminate() async
}

// MARK: - SDK wrappers

/// Wraps the SDK's ClientProcess as a ManagedContainerProcess.
private struct ClientProcessWrapper: ManagedContainerProcess {
    let wrapped: any ClientProcess

    func start() async throws {
        try await wrapped.start()
    }

    func wait() async throws -> Int32 {
        try await wrapped.wait()
    }

    func kill(_ signal: Int32) async throws {
        try await wrapped.kill(signal)
    }
}

/// Production ManagedContainerBackend backed by com.apple.container.apiserver via XPC.
/// Excluded from unit-test coverage; covered via mock in ContainerPoolTests.
actor LiveManagedContainerBackend: ManagedContainerBackend {
    private let client = ContainerClient()

    func create(id _: String, config: ContainerConfiguration) async throws {
        let kernel = try await ClientKernel.getDefaultKernel(for: .current)
        try await client.create(configuration: config, options: .default, kernel: kernel)
    }

    func bootstrap(
        id: String,
        stdin: FileHandle,
        stdout: FileHandle,
        stderr: FileHandle,
    ) async throws -> any ManagedContainerProcess {
        let proc = try await client.bootstrap(id: id, stdio: [stdin, stdout, stderr])
        return ClientProcessWrapper(wrapped: proc)
    }

    func delete(id: String) async throws {
        try await client.delete(id: id, force: true)
    }

    func imageExists(_ reference: String) async throws -> Bool {
        do {
            _ = try await ClientImage.get(reference: reference)
            return true
        } catch {
            return false
        }
    }
}

// MARK: - GnuCashContainerClient

/// One pre-started container process waiting for a single JSON-RPC request.
///
/// The Python worker does sys.stdin.buffer.read() then exits — it blocks until
/// stdin is closed, so we can pre-start it and send the request later.
///
/// Why SDK instead of `container run` CLI (previous approach):
///   client.delete(id:force:true) is fully awaitable and guaranteed to halt the VM.
///   Relying on process.terminate() (SIGTERM to the CLI) was not sufficient:
///   the VM runs under com.apple.Virtualization.VirtualMachine and outlives the CLI.
///   This was confirmed in logs showing the VM still running after proxy exit.
actor GnuCashContainerClient: PooledContainer {
    let id: String
    private let process: any ManagedContainerProcess
    private let backend: any ManagedContainerBackend
    private let stdinPipe: Pipe
    private let stdoutPipe: Pipe
    private let stderrPipe: Pipe
    /// Set to false by a background task when the worker exits unexpectedly (KU-11).
    private var _isAlive = true

    private static let imageName = "gnucash-mcp:latest"
    private static let dataMount = "/Volumes/GnuCash-Project"
    private static let bookPath = "/data/project.gnucash"

    init(backend: any ManagedContainerBackend) async throws {
        let containerId = "gnucash-mcp-\(UUID().uuidString.prefix(8).lowercased())"
        let imageDesc = try await {
            guard try await backend.imageExists(Self.imageName) else {
                throw ContainerError.imageNotFound(Self.imageName)
            }
            return try await ClientImage.get(reference: Self.imageName)
        }()

        let stdinP = Pipe()
        let stdoutP = Pipe()
        let stderrP = Pipe()

        let processConfig = ProcessConfiguration(
            executable: "/usr/bin/python3",
            arguments: ["-m", "gnucash_mcp"],
            environment: ["GNUCASH_BOOK_PATH=\(Self.bookPath)"],
            workingDirectory: "/",
        )
        var config = ContainerConfiguration(
            id: containerId,
            image: imageDesc.description,
            process: processConfig,
        )
        config.mounts = [.virtiofs(source: Self.dataMount, destination: "/data", options: [])]
        config.networks = [] // no network access needed

        try await backend.create(id: containerId, config: config)
        let proc = try await backend.bootstrap(
            id: containerId,
            stdin: stdinP.fileHandleForReading,
            stdout: stdoutP.fileHandleForWriting,
            stderr: stderrP.fileHandleForWriting,
        )
        try await proc.start()

        id = containerId
        process = proc
        self.backend = backend
        stdinPipe = stdinP
        stdoutPipe = stdoutP
        stderrPipe = stderrP
        fputs("container: started \(containerId)\n", stderr)

        // Background sentinel: marks container dead if the worker exits before roundTrip.
        // This is the KU-11 sleep/wake guard — a woken-from-sleep container may have been
        // killed by the OS, and we want acquire() to discard it rather than deadlock.
        let weakSelf = self // actors don't support [weak self] directly; capture via nonisolated ref
        Task.detached {
            _ = try? await weakSelf.process.wait()
            await weakSelf.markDead()
        }
    }

    var isAlive: Bool {
        _isAlive
    }

    private func markDead() {
        _isAlive = false
    }

    /// Write the request JSON to stdin, close stdin, read the response, await exit, delete.
    func roundTrip(request: Data) async throws -> Data {
        stdinPipe.fileHandleForWriting.write(request)
        try stdinPipe.fileHandleForWriting.close()

        // Close our write ends so the daemon's copies signal EOF when the worker exits.
        try? stdoutPipe.fileHandleForWriting.close()
        try? stderrPipe.fileHandleForWriting.close()

        // Drain I/O concurrently to avoid pipe-buffer deadlock (same pattern as buck2).
        async let responseData = Task.detached {
            (try? self.stdoutPipe.fileHandleForReading.readToEnd()) ?? Data()
        }.value
        async let stderrData = Task.detached {
            (try? self.stderrPipe.fileHandleForReading.readToEnd()) ?? Data()
        }.value

        let exitCode = try await process.wait()
        let response = await responseData
        let errOutput = await stderrData

        try await backend.delete(id: id)
        _isAlive = false
        fputs("container: exited \(id) status=\(exitCode)\n", stderr)

        if exitCode != 0 {
            let msg = String(data: errOutput, encoding: .utf8) ?? ""
            throw ContainerError.containerExitedWithError(exitCode, msg)
        }
        guard !response.isEmpty else {
            throw ContainerError.noResponse
        }
        return response
    }

    /// Kill and delete the container. Returns only after the VM has fully halted,
    /// so sparsebundle.detach() can safely follow.
    func terminate() async {
        _isAlive = false
        // Close stdin so the Python worker unblocks from read() and exits cleanly.
        try? stdinPipe.fileHandleForWriting.close()
        // delete(force:true) stops the VM if still running, then removes it.
        // This is the reliable path — see comment on LiveManagedContainerBackend.delete.
        try? await backend.delete(id: id)
        fputs("container: terminated \(id)\n", stderr)
    }
}

// MARK: - Container system startup checks

//
// These use the CLI for now; the SDK equivalent is to call imageExists() on a
// LiveManagedContainerBackend instance, which is done in App.swift at startup.
// TODO: Remove CLI calls once ContainerKit SDK docs for system-start are stable.
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
}
