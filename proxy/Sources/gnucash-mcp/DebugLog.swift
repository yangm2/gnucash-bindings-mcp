import Foundation

nonisolated(unsafe) private let _logTSFormatter: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()

private func _logTS() -> String { _logTSFormatter.string(from: Date()) }

/// Stderr logger with ISO8601 timestamp prefix. Drop-in replacement for
/// `fputs(msg, stderr)`. Always emits (release and debug); never writes to stdout.
@inline(__always)
func slog(_ message: String) {
    fputs("\(_logTS()) \(message)", stderr)
    fflush(stderr)
}

/// Debug-only stderr logger. Calls are stripped from release builds by `#if DEBUG`,
/// and the @autoclosure message argument is never evaluated in release.
///
/// Convention: same as the rest of the codebase — `subsystem: message`. Always
/// writes to stderr; never to stdout (which is the MCP JSON-RPC channel).
@inline(__always)
func dlog(_ subsystem: String, _ message: @autoclosure () -> String) {
    #if DEBUG
    fputs("\(_logTS()) [debug] \(subsystem): \(message())\n", stderr)
    fflush(stderr)
    #endif
}

/// Truncate a payload preview for logs. Avoids dumping multi-KB JSON to stderr.
@inline(__always)
func dlogPreview(_ data: Data, max: Int = 200) -> String {
    #if DEBUG
    let s = String(data: data, encoding: .utf8) ?? "<non-utf8 \(data.count)B>"
    if s.count <= max { return s }
    let prefix = s.prefix(max)
    return "\(prefix)… (\(s.count)B)"
    #else
    return ""
    #endif
}
