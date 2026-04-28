import Foundation
@testable import gnucash_mcp
import Testing

@Suite("BackupManager")
struct BackupTests {
    // ── helpers ───────────────────────────────────────────────────────────────

    private func makeTempBook() throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appending(component: "BackupTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let book = dir.appending(component: "project.gnucash")
        try Data("fake gnucash book content".utf8).write(to: book)
        return book
    }

    // ── T5.4.1  backup file created with correct name pattern ─────────────────

    @Test func `create backup produces correct filename`() throws {
        let book = try makeTempBook()
        defer { try? FileManager.default.removeItem(at: book.deletingLastPathComponent()) }

        let before = Date()
        let backup = try BackupManager.createBackup(bookURL: book)
        let after = Date()

        let name = backup.lastPathComponent
        #expect(name.hasPrefix("project.gnucash.pre-"))
        #expect(name.hasSuffix(".gnucash"))

        // Timestamp embedded in name falls within test window
        let tsString = String(name.dropFirst("project.gnucash.pre-".count).dropLast(".gnucash".count))
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyyMMdd-HHmmss"
        fmt.locale = Locale(identifier: "en_US_POSIX")
        let ts = try #require(fmt.date(from: tsString))
        #expect(ts >= before.addingTimeInterval(-1))
        #expect(ts <= after.addingTimeInterval(1))

        #expect(FileManager.default.fileExists(atPath: backup.path))
    }

    // ── T5.4.2  backup content matches source ─────────────────────────────────

    @Test func `create backup content matches source`() throws {
        let book = try makeTempBook()
        defer { try? FileManager.default.removeItem(at: book.deletingLastPathComponent()) }

        let backup = try BackupManager.createBackup(bookURL: book)

        let originalData = try Data(contentsOf: book)
        let backupData = try Data(contentsOf: backup)
        #expect(originalData == backupData)
    }

    // ── T5.4.3  createBackup completes in < 500ms ─────────────────────────────

    @Test func `create backup completes quickly`() throws {
        let book = try makeTempBook()
        defer { try? FileManager.default.removeItem(at: book.deletingLastPathComponent()) }

        let start = Date()
        _ = try BackupManager.createBackup(bookURL: book)
        let elapsed = Date().timeIntervalSince(start)

        #expect(elapsed < 0.5, "createBackup took \(elapsed)s, expected < 0.5s")
    }

    // ── T5.4.4  pruneBackups keeps exactly keepCount files ────────────────────

    @Test func `prune backups keeps correct count`() throws {
        let book = try makeTempBook()
        let dir = book.deletingLastPathComponent()
        defer { try? FileManager.default.removeItem(at: dir) }

        // Create 15 backup files with distinct timestamps
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyyMMdd-HHmmss"
        fmt.locale = Locale(identifier: "en_US_POSIX")
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        for i in 0 ..< 15 {
            let ts = fmt.string(from: base.addingTimeInterval(Double(i * 60)))
            let name = "project.gnucash.pre-\(ts).gnucash"
            try Data("backup \(i)".utf8).write(to: dir.appending(component: name))
        }

        try BackupManager.pruneBackups(bookURL: book, keepCount: 10)

        let remaining = try FileManager.default
            .contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("project.gnucash.pre-") }
        #expect(remaining.count == 10)

        // Live book untouched
        #expect(FileManager.default.fileExists(atPath: book.path))

        // Oldest 5 deleted, newest 10 kept
        let names = remaining.map(\.lastPathComponent).sorted()
        let expectedOldest = "project.gnucash.pre-\(fmt.string(from: base.addingTimeInterval(5 * 60))).gnucash"
        #expect(names.first == expectedOldest)
    }

    // ── pruneBackups with fewer files than keepCount leaves all untouched ──────

    @Test func `prune backups no op when below keep count`() throws {
        let book = try makeTempBook()
        let dir = book.deletingLastPathComponent()
        defer { try? FileManager.default.removeItem(at: dir) }

        let fmt = DateFormatter()
        fmt.dateFormat = "yyyyMMdd-HHmmss"
        fmt.locale = Locale(identifier: "en_US_POSIX")
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        for i in 0 ..< 3 {
            let ts = fmt.string(from: base.addingTimeInterval(Double(i * 60)))
            let name = "project.gnucash.pre-\(ts).gnucash"
            try Data("backup \(i)".utf8).write(to: dir.appending(component: name))
        }

        try BackupManager.pruneBackups(bookURL: book, keepCount: 10)

        let remaining = try FileManager.default
            .contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("project.gnucash.pre-") }
        #expect(remaining.count == 3)
    }
}
