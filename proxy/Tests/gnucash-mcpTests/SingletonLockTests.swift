import Foundation
@testable import gnucash_mcp
import Testing

@Suite("SingletonLock")
struct SingletonLockTests {
    private func tempLockURL() -> URL {
        FileManager.default.temporaryDirectory
            .appending(component: "gnucash-mcp-test-\(UUID().uuidString).lock")
    }

    // ── T8.7.1a  acquire succeeds when no lock held ───────────────────────────

    @Test func `acquire succeeds when lock is free`() throws {
        let url = tempLockURL()
        defer { try? FileManager.default.removeItem(at: url) }

        let lock = try SingletonLock.acquire(lockURL: url)
        _ = lock
    }

    // ── T8.7.1b  second acquire on held lock throws alreadyRunning ────────────

    @Test func `second acquire throws alreadyRunning`() throws {
        let url = tempLockURL()
        defer { try? FileManager.default.removeItem(at: url) }

        let first = try SingletonLock.acquire(lockURL: url)
        defer { _ = first }

        #expect(throws: SingletonLockError.alreadyRunning) {
            try SingletonLock.acquire(lockURL: url)
        }
    }

    // ── T8.7.2  after lock is released, re-acquire succeeds ───────────────────

    @Test func `re-acquire succeeds after release`() throws {
        let url = tempLockURL()
        defer { try? FileManager.default.removeItem(at: url) }

        do {
            let first = try SingletonLock.acquire(lockURL: url)
            _ = first
            // first goes out of scope here → deinit closes fd → lock released
        }

        // Should not throw
        let second = try SingletonLock.acquire(lockURL: url)
        _ = second
    }

    // ── readPID returns the current process PID after acquire ─────────────────

    @Test func `readPID returns current process PID`() throws {
        let url = tempLockURL()
        defer { try? FileManager.default.removeItem(at: url) }

        let lock = try SingletonLock.acquire(lockURL: url)
        defer { _ = lock }

        let pid = SingletonLock.readPID(lockURL: url)
        #expect(pid == ProcessInfo.processInfo.processIdentifier)
    }

    // ── readPID returns nil when no lock file exists ──────────────────────────

    @Test func `readPID returns nil when lock file absent`() {
        let url = tempLockURL() // never created
        #expect(SingletonLock.readPID(lockURL: url) == nil)
    }

    // ── readPID returns nil after lock is released (file exists but PID gone) ─

    @Test func `readPID still returns PID after release (file persists)`() throws {
        let url = tempLockURL()
        defer { try? FileManager.default.removeItem(at: url) }

        do {
            let lock = try SingletonLock.acquire(lockURL: url)
            _ = lock
        }

        // File still exists after release; PID content is still there.
        // A new acquire would overwrite it — this documents the current behaviour.
        let pid = SingletonLock.readPID(lockURL: url)
        #expect(pid == ProcessInfo.processInfo.processIdentifier)
    }
}
