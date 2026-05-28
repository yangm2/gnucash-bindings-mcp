import Foundation

enum SingletonLockError: Error, CustomStringConvertible, Equatable {
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
/// The lock and fd are released automatically when this object is deallocated.
final class SingletonLock {
    static let lockURL = URL.temporaryDirectory.appending(component: "gnucash-mcp.lock")

    private let fd: Int32

    private init(fd: Int32) {
        self.fd = fd
    }

    deinit { close(fd) }

    /// Acquire the lock at `url` (defaults to the production lock file).
    /// Throws `SingletonLockError.alreadyRunning` if another instance holds it.
    ///
    /// If the holder is an orphan (reparented to launchd, PID 1) it can no longer
    /// serve any client — SIGKILL it and reclaim the lock once.
    static func acquire(lockURL: URL = SingletonLock.lockURL) throws -> SingletonLock {
        let fd = open(lockURL.path, O_CREAT | O_RDWR, 0o644)
        guard fd >= 0 else { throw SingletonLockError.openFailed(errno) }

        if flock(fd, LOCK_EX | LOCK_NB) != 0 {
            if let holderPID = readPID(lockURL: lockURL), parentPID(of: holderPID) == 1 {
                slog("singleton: reclaiming orphan lock from PID \(holderPID)\n")
                kill(holderPID, SIGKILL)
                // Give the kernel a moment to release the holder's flock.
                for _ in 0 ..< 20 {
                    if flock(fd, LOCK_EX | LOCK_NB) == 0 { break }
                    usleep(50_000) // 50ms × 20 = 1s max
                }
            }
            if flock(fd, LOCK_EX | LOCK_NB) != 0 {
                close(fd)
                throw SingletonLockError.alreadyRunning
            }
        }

        // Truncate then write PID so stop can read it.
        ftruncate(fd, 0)
        let pid = "\(ProcessInfo.processInfo.processIdentifier)\n"
        pid.withCString { ptr in _ = write(fd, ptr, strlen(ptr)) }

        return SingletonLock(fd: fd)
    }

    /// Read the PID written by the running instance from `url`.
    /// Returns the parent PID of `pid`, or nil if the process doesn't exist.
    /// Uses sysctl(KERN_PROC_PID); avoids shelling out to `ps`.
    private static func parentPID(of pid: pid_t) -> pid_t? {
        var info = kinfo_proc()
        var size = MemoryLayout<kinfo_proc>.size
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, pid]
        let rc = mib.withUnsafeMutableBufferPointer { ptr in
            sysctl(ptr.baseAddress, u_int(ptr.count), &info, &size, nil, 0)
        }
        guard rc == 0, size > 0, info.kp_proc.p_pid == pid else { return nil }
        return info.kp_eproc.e_ppid
    }

    static func readPID(lockURL: URL = SingletonLock.lockURL) -> pid_t? {
        guard let data = try? Data(contentsOf: lockURL),
              let str = String(data: data, encoding: .utf8),
              let pid = pid_t(str.trimmingCharacters(in: .whitespacesAndNewlines))
        else { return nil }
        return pid
    }
}
