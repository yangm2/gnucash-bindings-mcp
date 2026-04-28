import Foundation

enum BackupError: Error, CustomStringConvertible {
    case copyFailed(Int32)

    var description: String {
        switch self {
        case let .copyFailed(status): "cp -c exited with status \(status)"
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

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/cp")
        process.arguments = ["-c", bookURL.path, backupURL.path]
        try process.run()
        process.waitUntilExit()

        guard process.terminationStatus == 0 else {
            throw BackupError.copyFailed(process.terminationStatus)
        }
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
