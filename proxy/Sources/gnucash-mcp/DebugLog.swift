import Foundation

/// Debug-only stderr logger. Calls are stripped from release builds by `#if DEBUG`,
/// and the @autoclosure message argument is never evaluated in release.
///
/// Convention: same as the rest of the codebase — `subsystem: message`. Always
/// writes to stderr; never to stdout (which is the MCP JSON-RPC channel).
@inline(__always)
func dlog(_ subsystem: String, _ message: @autoclosure () -> String) {
    #if DEBUG
    fputs("[debug] \(subsystem): \(message())\n", stderr)
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
