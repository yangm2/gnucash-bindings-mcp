import Foundation

// Size-1 container pool with 5-second TTL.
//
// Strategy: after each dispatch, immediately pre-start a new container. The
// Python worker blocks on sys.stdin.buffer.read() until stdin closes, so the
// warm container just sits waiting. On the next tool call we write to it
// directly and avoid startup latency. If no call arrives within `ttl` seconds,
// the reaper kills the waiting container.
actor ContainerPool {
    private var warm: ContainerAPIClient?
    private var warmSince: Date?
    private let ttl: TimeInterval
    private var reaperTask: Task<Void, Never>?

    init(ttl: TimeInterval = 5) {
        self.ttl = ttl
    }

    /// Acquire a ready-to-use client. Validates liveness for sleep/wake safety (KU-11).
    func acquire() throws -> ContainerAPIClient {
        if let client = warm, client.isAlive {
            warm = nil
            warmSince = nil
            cancelReaper()
            return client
        }
        // Warm client gone or stale — start fresh.
        warm = nil
        warmSince = nil
        return try ContainerAPIClient()
    }

    /// Release after use: pre-start next container and arm the reaper.
    func release() {
        do {
            let next = try ContainerAPIClient()
            warm = next
            warmSince = Date()
            armReaper()
        } catch {
            // If pre-start fails, next acquire() will just start on demand.
        }
    }

    // Drain: terminate warm container (called on SIGTERM/SIGINT).
    func drain() {
        cancelReaper()
        warm?.terminate()
        warm = nil
        warmSince = nil
    }

    var isWarm: Bool {
        warm?.isAlive == true
    }

    var lastActivityDate: Date? {
        warmSince
    }

    // MARK: - Reaper

    private func armReaper() {
        cancelReaper()
        reaperTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(self?.ttl ?? 5))
            guard !Task.isCancelled else { return }
            await self?.reap()
        }
    }

    private func cancelReaper() {
        reaperTask?.cancel()
        reaperTask = nil
    }

    private func reap() {
        guard let since = warmSince,
              Date().timeIntervalSince(since) >= ttl
        else { return }
        warm?.terminate()
        warm = nil
        warmSince = nil
    }
}
