import Foundation

enum SingletonLockError: Error, CustomStringConvertible {
    case alreadyRunning
    case openFailed(Int32)

    var description: String {
        switch self {
        case .alreadyRunning: "gnucash-mcp is already running"
        case let .openFailed(code): "could not open lock file: errno \(code)"
        }
    }
}

/// Exclusive process-lifetime lock backed by flock(2).
///
/// Acquiring writes the current PID to the lock file so `gnucash-mcp stop`
/// can find the process without shelling out to pgrep.
/// The lock is released automatically when the process exits (fd close-on-exit).
struct SingletonLock {
    static let lockURL = URL.temporaryDirectory.appending(component: "gnucash-mcp.lock")

    private let fd: Int32

    /// Acquire the lock. Throws `SingletonLockError.alreadyRunning` if another
    /// instance holds it.
    static func acquire() throws -> SingletonLock {
        let fd = open(lockURL.path, O_CREAT | O_RDWR, 0o644)
        guard fd >= 0 else { throw SingletonLockError.openFailed(errno) }

        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            close(fd)
            throw SingletonLockError.alreadyRunning
        }

        // Truncate then write PID so stop can read it.
        ftruncate(fd, 0)
        let pid = "\(ProcessInfo.processInfo.processIdentifier)\n"
        pid.withCString { ptr in _ = write(fd, ptr, strlen(ptr)) }

        return SingletonLock(fd: fd)
    }

    /// Read the PID written by the running instance, if any.
    static func readPID() -> pid_t? {
        guard let data = try? Data(contentsOf: lockURL),
              let str = String(data: data, encoding: .utf8),
              let pid = pid_t(str.trimmingCharacters(in: .whitespacesAndNewlines))
        else { return nil }
        return pid
    }
}
