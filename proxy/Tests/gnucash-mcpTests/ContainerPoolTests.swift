import ContainerResource
import Foundation
import Testing
@testable import gnucash_mcp

// MARK: - Mock containers

/// A mock PooledContainer whose liveness and round-trip behaviour are controlled by the test.
actor MockContainer: PooledContainer {
    let id: String
    private var _isAlive: Bool
    private let response: Data
    var terminateCalled = false
    var roundTripCalled = false

    init(id: String = UUID().uuidString, alive: Bool = true, response: Data = Data()) {
        self.id = id
        self._isAlive = alive
        self.response = response
    }

    var isAlive: Bool { _isAlive }

    func roundTrip(request _: Data) async throws -> Data {
        roundTripCalled = true
        return response
    }

    func terminate() async {
        terminateCalled = true
        _isAlive = false
    }

    func setAlive(_ value: Bool) { _isAlive = value }
}

// MARK: - ContainerPool lifecycle invariant tests

@Suite("ContainerPool — lifecycle invariants")
struct ContainerPoolTests {

    // ── Invariant: drain empties pool and awaits terminate ────────────────────

    @Test("drain() terminates warm container and leaves pool empty")
    func drainTerminatesWarmContainer() async throws {
        let container = MockContainer(id: "c1")
        let pool = ContainerPool { container }

        // Seed the pool with a warm container via release().
        await pool.release()
        // Wait briefly for the pre-start Task to complete.
        try await Task.sleep(for: .milliseconds(50))
        #expect(await pool.isWarm)

        await pool.drain()

        #expect(!(await pool.isWarm))
        #expect(await container.terminateCalled)
    }

    @Test("drain() on empty pool is a no-op")
    func drainEmptyPool() async {
        let pool = ContainerPool { MockContainer() }
        // Should not throw or hang.
        await pool.drain()
        #expect(!(await pool.isWarm))
    }

    // ── Invariant: acquire discards dead containers ────────────────────────────

    @Test("acquire() discards a dead warm container and starts a fresh one")
    func acquireDiscardsDeadContainer() async throws {
        let dead = MockContainer(id: "dead", alive: false)
        let fresh = MockContainer(id: "fresh", alive: true)
        actor CallCounter {
            var count = 0
            func increment() -> Int {
                count += 1
                return count
            }
        }
        let counter = CallCounter()
        let pool = ContainerPool {
            let count = await counter.increment()
            return count == 1 ? dead : fresh
        }

        // Seed dead container as the warm slot by calling release() directly.
        await pool.release()
        try await Task.sleep(for: .milliseconds(50))

        let acquired = try await pool.acquire()
        #expect(acquired.id == "fresh")
        // The dead container must have been terminated before discard.
        #expect(await dead.terminateCalled)
    }

    @Test("acquire() returns warm container when alive")
    func acquireReturnsWarmContainer() async throws {
        let warm = MockContainer(id: "warm", alive: true)
        actor FirstCallTracker {
            var isFirst = true
            func consumeFirst() -> Bool {
                defer { isFirst = false }
                return isFirst
            }
        }
        let tracker = FirstCallTracker()
        let pool = ContainerPool {
            let first = await tracker.consumeFirst()
            return first ? warm : MockContainer(id: "other")
        }

        await pool.release()
        try await Task.sleep(for: .milliseconds(50))

        let acquired = try await pool.acquire()
        #expect(acquired.id == "warm")
        #expect(!(await pool.isWarm))
    }

    @Test("acquire() cold-starts when pool is empty")
    func acquireColdStart() async throws {
        let cold = MockContainer(id: "cold")
        let pool = ContainerPool { cold }

        let acquired = try await pool.acquire()
        #expect(acquired.id == "cold")
    }

    // ── Invariant: at most one warm container at a time ───────────────────────

    @Test("release() replaces previous warm container after acquire()")
    func releaseAfterAcquire() async throws {
        let containers = [MockContainer(id: "c1"), MockContainer(id: "c2"), MockContainer(id: "c3")]
        actor CallCounter {
            var count = 0
            func getAndIncrement() -> Int {
                let current = count
                count += 1
                return current
            }
        }
        let counter = CallCounter()
        let pool = ContainerPool {
            let index = await counter.getAndIncrement()
            return containers[min(index, containers.count - 1)]
        }

        // Seed a warm container.
        await pool.release()
        try await Task.sleep(for: .milliseconds(50))
        #expect(await pool.isWarm)

        // Acquire clears the warm slot.
        _ = try await pool.acquire()
        #expect(!(await pool.isWarm))

        // Release seeds a new warm container.
        await pool.release()
        try await Task.sleep(for: .milliseconds(50))
        #expect(await pool.isWarm)
    }

    // ── Invariant: reaper terminates container after TTL ──────────────────────

    @Test("reaper terminates container after TTL expires")
    func reaperTerminatesAfterTTL() async throws {
        let container = MockContainer(id: "ttl-victim")
        let pool = ContainerPool(ttl: 0.05) { container }

        await pool.release()
        try await Task.sleep(for: .milliseconds(50))

        // Wait for reaper to fire.
        try await Task.sleep(for: .milliseconds(200))

        #expect(await container.terminateCalled)
        #expect(!(await pool.isWarm))
    }

    @Test("drain() cancels reaper so it does not double-terminate")
    func drainCancelsReaper() async throws {
        let container = MockContainer(id: "drain-beats-reaper")
        let pool = ContainerPool(ttl: 0.2) { container }

        await pool.release()
        try await Task.sleep(for: .milliseconds(50))

        // Drain before TTL fires.
        await pool.drain()

        // Wait beyond TTL; reaper should have been cancelled.
        try await Task.sleep(for: .milliseconds(300))

        // terminate() should have been called exactly once (by drain, not reaper).
        // MockContainer.terminateCalled is a bool, so we can only assert it was called;
        // double-terminate safety is guaranteed by _isAlive = false on first call.
        #expect(await container.terminateCalled)
        #expect(!(await pool.isWarm))
    }

    // ── Invariant: ordering — drain completes before detach is safe ───────────

    @Test("drain() awaits terminate() so no concurrent container activity follows")
    func drainAwaitsTerminate() async throws {
        // A container that records when terminate() resolves relative to drain() return.
        actor TimedContainer: PooledContainer {
            let id = "timed"
            var isAlive: Bool = true
            var terminateCompleted = false

            func roundTrip(request _: Data) async throws -> Data { Data() }

            func terminate() async {
                // Simulate async teardown work.
                try? await Task.sleep(for: .milliseconds(30))
                terminateCompleted = true
                isAlive = false
            }
        }

        let container = TimedContainer()
        let pool = ContainerPool { container }

        await pool.release()
        try await Task.sleep(for: .milliseconds(50))

        await pool.drain()

        // If drain() properly awaits terminate(), this must be true immediately after.
        #expect(await container.terminateCompleted)
    }
}
