import Foundation

// Size-1 pool of PooledContainer instances with a TTL-based reaper.
//
// Strategy: after each dispatch, immediately pre-start a new container. The
// Python worker blocks on sys.stdin.buffer.read() until stdin closes, so the
// warm container just sits waiting. On the next tool call we hand it the request
// directly and avoid startup latency. If no call arrives within `ttl` seconds,
// the reaper kills the waiting container.
//
// Lifecycle invariants (asserted by ContainerPoolTests):
//   - At most one warm container exists at any time.
//   - After drain(), isWarm is false and the warm container's terminate() has been awaited.
//   - After reap(), the reaped container's terminate() has been awaited.
//   - acquire() discards a dead container (isAlive == false) and starts a fresh one.
actor ContainerPool {
    private var warm: (any PooledContainer)?
    private var warmSince: Date?
    private let ttl: TimeInterval
    private var reaperTask: Task<Void, Never>?
    /// Factory injected at init; production code passes GnuCashContainerClient,
    /// tests pass a mock. Async because container creation is async.
    private let factory: @Sendable () async throws -> any PooledContainer

    init(
        ttl: TimeInterval = 5,
        factory: @escaping @Sendable () async throws -> any PooledContainer,
    ) {
        self.ttl = ttl
        self.factory = factory
    }

    // MARK: - Acquire / release

    /// Returns a ready-to-use container. Validates liveness for sleep/wake safety (KU-11).
    func acquire() async throws -> any PooledContainer {
        if let client = warm {
            if await client.isAlive {
                fputs("pool: acquired warm container \(client.id)\n", stderr)
                warm = nil
                warmSince = nil
                cancelReaper()
                return client
            } else {
                // Dead warm container (e.g. OS killed VM after sleep/wake).
                fputs("pool: warm container \(client.id) is dead, discarding\n", stderr)
                await client.terminate()
                warm = nil
                warmSince = nil
                cancelReaper()
            }
        }
        fputs("pool: cold start — no warm container\n", stderr)
        return try await factory()
    }

    /// Called after dispatch completes: pre-starts the next container for warm reuse.
    func release() {
        Task {
            do {
                let next = try await factory()
                fputs("pool: pre-started warm container \(next.id)\n", stderr)
                warm = next
                warmSince = Date()
                armReaper()
            } catch {
                // If pre-start fails, next acquire() starts on demand — not fatal.
                fputs("pool: pre-start failed: \(error)\n", stderr)
            }
        }
    }

    /// Terminate the warm container, if any. Called on SIGTERM, SIGINT, and stdin EOF.
    /// Returns only after the container has fully halted (via PooledContainer.terminate()).
    func drain() async {
        cancelReaper()
        if let client = warm {
            fputs("pool: draining warm container \(client.id)\n", stderr)
            await client.terminate()
            fputs("pool: drained\n", stderr)
        } else {
            fputs("pool: drain — no warm container\n", stderr)
        }
        warm = nil
        warmSince = nil
    }

    var isWarm: Bool {
        warm != nil
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

    private func reap() async {
        guard let since = warmSince,
              Date().timeIntervalSince(since) >= ttl,
              let client = warm
        else { return }
        fputs("pool: TTL expired, reaping \(client.id)\n", stderr)
        warm = nil
        warmSince = nil
        await client.terminate()
        fputs("pool: reaped \(client.id)\n", stderr)
    }
}
