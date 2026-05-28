import Foundation

enum BackupError: Error, CustomStringConvertible {
    case copyFailed(Error)

    var description: String {
        switch self {
        case let .copyFailed(error): "backup copy failed: \(error)"
        }
    }
}

enum BackupManager {
    // Backup naming: {book}.pre-YYYYMMDD-HHMMSS.gnucash
    // e.g. project.gnucash.pre-20250428-143022.gnucash

    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    static func createBackup(bookURL: URL) throws -> URL {
        let timestamp = formatter.string(from: Date())
        let backupName = "\(bookURL.lastPathComponent).pre-\(timestamp).gnucash"
        let backupURL = bookURL.deletingLastPathComponent().appending(component: backupName)

        let start = Date()
        do {
            try FileManager.default.copyItem(at: bookURL, to: backupURL)
        } catch {
            throw BackupError.copyFailed(error)
        }
        let elapsedMs = Int(Date().timeIntervalSince(start) * 1000)
        dlog("backup", "\(bookURL.lastPathComponent) → \(backupURL.lastPathComponent) (\(elapsedMs)ms)")
        return backupURL
    }

    static func pruneBackups(bookURL: URL, keepCount: Int) throws {
        let dir = bookURL.deletingLastPathComponent()
        let prefix = bookURL.lastPathComponent + ".pre-"

        let backups = try FileManager.default
            .contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix(prefix) && $0.pathExtension == "gnucash" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent } // lexicographic = chronological

        for url in backups.dropLast(keepCount) {
            try FileManager.default.removeItem(at: url)
        }
    }
}
