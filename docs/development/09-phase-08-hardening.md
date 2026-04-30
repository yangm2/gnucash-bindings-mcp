# Phase 8 — Hardening and Claude Desktop Integration

**Goal:** Production-ready reliability for a project expected to run 18–24 months.
The MCP server is the default interface; macOS GnuCash is the occasional inspector.

### M8.1 — Structured logging

**Deliverables (two log streams):**

*Proxy-level log* — Swift proxy writes to `~/.local/share/gnucash-mcp/proxy.log`:
- Every request received: method, tool name, session ID (if Phase 5), timestamp
- Container pool events: start, reuse, TTL expiry, sleep/wake invalidation
- Sparsebundle mount/unmount events
- JSONL format

*Dispatcher-level log* — Python writes to `/data/mcp.log` (inside sparsebundle):
- Tool call start/end with wall-clock duration
- GnuCash session open/save/end events
- WAL entry IDs for write operations
- Crash recovery replay events (distinguishable from new posts)
- JSONL format; persists across container restarts

**Tests:**
```
T8.1.1  Proxy log records tool name, duration, and success/failure for each request
T8.1.2  Proxy log records container pool events (start, reuse, expire)
T8.1.3  Dispatcher log records GnuCash session open/save/end with timestamps
T8.1.4  Failed tool call in dispatcher produces log entry with error and stack trace
T8.1.5  Crash recovery replay produces dispatcher log entry with replay=true field,
        distinguishable from new posts
T8.1.6  After Mac sleep/wake, proxy log records pool invalidation event
```

---

### M8.2 — Schema version guard

**Deliverables:**
- In Python dispatcher `src/__main__.py`, before dispatching any `tools/call`:
  - Parse GnuCash version from XML header (`<gnc-v2 xmlns:...>` or book slot)
  - Compare against container GnuCash version string
  - If book version > container version: return JSON-RPC error response, do not
    open a session
- Swift proxy propagates the error to Claude Desktop as a tool call failure
  with a human-readable message

**Tests:**
```
T8.2.1  Guard passes when book version matches container version
T8.2.2  Guard returns JSON-RPC error -32603 with clear message when book version
        > container version; no GnuCash session opened
T8.2.3  Guard does not false-positive on a book created by same version
T8.2.4  Claude Desktop surfaces the error message rather than silently failing
        (manual — trigger by temporarily decrementing container version string)
```

---

### M8.3 — Backup verification

**Deliverables:**
- `bin/verify-backup.zsh` — weekly manual trigger (runs on macOS host, not in container):
  - Mounts latest APFS snapshot (or most recent `.YYYYMMDDHHMMSS.gnucash` backup)
  - Opens book read-only via Python bindings in container
  - Verifies: account count matches expected, root balance sane (assets = liabilities + equity)
  - Prints PASS/FAIL summary

**Tests:**
```
T8.3.1  verify-backup.zsh PASS on a known-good snapshot
T8.3.2  verify-backup.zsh FAIL on a book with manually corrupted XML
T8.3.3  Script runs to completion without hanging (max 30 second timeout)
```

---

### M8.4 — Claude Desktop configuration and launchd integration

**Deliverables:**
- `gnucash-mcp install` subcommand:
  - Writes `claude_desktop_config.json` `command` entry pointing to the
    `gnucash-mcp` binary with `--stdio` flag (MC-4; not `streamable-http`)
  - Writes `~/Library/LaunchAgents/com.youruser.gnucash-mcp.plist`
  - Instructions to load: `launchctl load ~/Library/LaunchAgents/com.youruser.gnucash-mcp.plist`
- launchd plist configuration:

```xml
<!-- com.youruser.gnucash-mcp.plist -->
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.youruser.gnucash-mcp</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/youruser/Library/Application Support/gnucash-mcp/gnucash-mcp</string>
    <string>start</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/youruser/Library/Logs/gnucash-mcp/gnucash-mcp.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/youruser/Library/Logs/gnucash-mcp/gnucash-mcp.err</string>
</dict>
</plist>
```

`KeepAlive: SuccessfulExit: false` means launchd restarts the proxy if it crashes
but does NOT restart it after a clean `gnucash-mcp stop` (exit 0). This is the
correct behaviour: stop is intentional, crash is not.

**Note:** The Swift proxy is the only thing that starts at login. No container runs
at login — containers are spun up on first tool call. Claude Desktop spawns the
proxy as a child process via the `command` entry in `claude_desktop_config.json`;
the launchd plist ensures the proxy is running before Claude Desktop is used.

**Tests:**
```
T8.4.1  gnucash-mcp install writes correct config entries without error
T8.4.2  Claude Desktop shows gnucash-myproject connected after launchctl load + restart
T8.4.3  get_project_summary() callable from Claude.ai chat window
T8.4.4  After clean gnucash-mcp stop (exit 0), launchd does NOT restart the proxy
T8.4.5  After simulated crash (kill -9 on proxy), launchd restarts it within 5s
T8.4.6  Server startup latency < 2s from gnucash-mcp start to first tools/list response
        to stdio (proxy only — no container started yet)
T8.4.7  First tool call latency < 1.5s (includes container start via ContainerAPIClient)
T8.4.8  CoWork session shows gnucash-myproject tools available via SDK bridge
T8.4.9  Mac sleep → wake → tool call succeeds (KU-11 sleep/wake recovery confirmed;
        record in TEST_RESULTS.md)
```

---

### M8.6 — Agent hallucination guards

**Goal:** Reduce the risk of an LLM agent posting fabricated, duplicated, or
misclassified entries. The macOS GUI is read-only and human review is
out-of-band, so guards must live at the dispatcher / WAL layer where they are
unbypassable from prompt context.

**Deliverables:**

*Idempotency keys (highest priority).* Every write tool computes a stable
content hash over its semantically-identifying fields and stores it in the WAL:
- `book_invoice`: hash(vendor, invoice_number, amount, invoice_date)
- `record_eco`: hash(eco_number, line_item, amount)
- `record_payment`: hash(vendor, amount, payment_date, source_ref)
- On WAL append, reject with JSON-RPC error if the hash already has a
  `committed_at` entry. Replay-safe: WAL replay re-checks before re-posting.

*Vendor-name canonicalization.* `book_invoice` will not implicitly create a new
`Liabilities:AP — {vendor}` account. If the vendor string does not exact-match
an existing AP account, the tool returns an error listing the closest fuzzy
matches (Levenshtein ≤ 3 or shared token prefix) and requires the agent to
either pick one or call an explicit `create_vendor` tool. Prevents silent
duplicate AP accounts ("ABC Electric" vs "ABC Electrical LLC").

*Per-tool account allowlists.* Schema-level (not prompt-level) restriction on
which account paths each tool may touch:
- `book_invoice`: credit must match `Liabilities:AP — *`; debit must match
  `Expenses:Construction:*` or `Expenses:*` leaves (not parents).
- `record_eco`: debit must match `Expenses:Change Orders:*`.
- `record_payment`: debit must match `Liabilities:AP — *`; credit must match
  `Assets:*`.
- Violations return JSON-RPC error before the WAL entry is written.

*Amount and date sanity checks.* Reject at dispatcher boundary:
- Dates more than 7 days in the future → error.
- Dates more than 2 years in the past → error (typo guard for current year).
- Negative amounts on expense legs → error.
- Single-entry amounts above a configurable threshold (default $25,000)
  require an explicit `confirm=true` argument.

*Dry-run / preview mode.* Each write tool gains a `plan_*` sibling
(`plan_book_invoice`, `plan_record_eco`, `plan_record_payment`) that returns
the journal entry that *would* be posted — accounts, amounts, debits/credits,
resolved vendor — without opening a GnuCash session or writing to the WAL.
Enables agent self-review and end-user confirmation flows.

*Trial-balance assertion after every write.* Inside `book_session()`, after
`session.save()` and before `session.end()`, sum all account balances rooted
at Assets, Liabilities, Equity, Income, Expenses; assert the accounting
equation holds within $0.01. On failure: log, set WAL `committed_at` anyway
(the save already happened) but emit a `trial_balance_violation` field so
operators can investigate. Cheap; catches binding-level imbalance bugs.

*Source-doc attachment.* Every write tool requires a `source_ref` argument
(file path on host, email Message-ID, manual entry note ≥ 10 chars). Stored
verbatim in the GnuCash transaction's `notes` slot and in the WAL entry.
Makes after-the-fact audit tractable and creates a paper trail back to the
originating document.

**Tests:**
```
T8.6.1   Posting same invoice twice (same vendor, invoice#, amount, date)
         returns idempotency error on second attempt; ledger unchanged
T8.6.2   Idempotency key survives WAL replay: replay does not double-post
         already-committed entries
T8.6.3   book_invoice with vendor "ABC Electric" when only "ABC Electrical LLC"
         exists returns error listing the fuzzy match
T8.6.4   book_invoice with credit account = "Assets:Checking" rejected by
         allowlist before WAL write
T8.6.5   record_eco with debit = "Expenses:Construction:Framing" rejected
         (must be Change Orders subtree)
T8.6.6   Date 30 days in future rejected; date 5 days in future accepted
T8.6.7   Date 3 years in past rejected
T8.6.8   Amount $30,000 without confirm=true rejected; same with confirm=true
         posts successfully
T8.6.9   plan_book_invoice returns full JE without opening session, without
         writing WAL, without creating .LCK file
T8.6.10  Trial balance assertion fires (logged, surfaced in response) when
         accounting equation violated by ≥ $0.01
T8.6.11  Write tool called without source_ref returns argument validation
         error; with source_ref, value appears in transaction notes slot
```

---

### Phase 8 exit criteria

- Swift proxy registered via launchd, starts at login, survives crash-restart
- Claude Desktop connected via stdio `command` entry; `gnucash-myproject` shows connected
- CoWork session confirmed working via SDK bridge (T8.4.8 documented)
- Schema version guard catches a deliberate version mismatch in testing
- Backup verification script runs clean on current book state
- Proxy startup latency (tools/list, no container) < 2s documented
- First tool call latency (cold container start) < 1.5s documented
- Sleep/wake recovery confirmed (T8.4.9 documented)
- M8.5 (session-aware pool) implemented if CoWork multi-step latency unacceptable

---

### M8.5 — Swift proxy Phase 2 (session-aware pool, optional)

**Goal:** Upgrade the proxy's container pool from TTL-based to session-aware,
so the warm container stays alive for the duration of a Claude Desktop
conversation rather than expiring on an arbitrary 5-second idle timer.

**When to implement:** If CoWork multi-step tasks (5+ sequential tool calls)
reveal that mid-session cold-starts are perceptible. The TTL pool is correct
for single-tool interactions; this upgrade is a quality-of-life improvement
for agentic workflows.

**Deliverables (purely Swift proxy changes — Python container unchanged):**
- Swift proxy generates an internal session ID on each `initialize` and includes it
  in the `initialize` result JSON (not as an HTTP header — transport is stdio)
- `sessions: [SessionID: PoolEntry]` dictionary replaces single `pool` entry
- On `tools/call` bearing the session ID: reuse that session's container, extend TTL
- On stdin EOF (Claude Desktop closed the connection): drain all active sessions
- TTL fallback (dirty disconnect — stdin stays open but goes idle): 60s idle
  per-session TTL, not 5s global TTL

```swift
// Phase 2 pool model
struct PoolEntry {
    let container: ContainerHandle
    var lastUsed: Date
    let sessionID: String

    var isExpired: Bool {
        Date().timeIntervalSince(lastUsed) > 60.0  // longer TTL per-session
    }
}

var sessions: [String: PoolEntry] = [:]

func handleInitialize(_ request: JSONRPCRequest) -> JSONRPCResponse {
    let sessionID = UUID().uuidString
    var response = staticInitializeResponse
    // Include session ID in result body; client echoes it in subsequent requests
    response.result["sessionId"] = .string(sessionID)
    sessions[sessionID] = PoolEntry(...)    // create entry; container starts on first call
    return response
}

// stdin EOF handler — Claude Desktop closed the pipe
func handleDisconnect() async {
    for (_, entry) in sessions { await entry.container.stop() }
    sessions.removeAll()
}
```

**Tests:**
```
T8.5.1  Two sequential initialize requests produce two distinct session IDs
T8.5.2  Tool calls within same session reuse warm container (no cold start after first call)
T8.5.3  Tool call with unknown/expired session ID starts fresh container, returns result
T8.5.4  stdin EOF → all active session containers drained within 2s; sparsebundle detached
T8.5.5  After 60s idle, expired session's container is reaped by reap loop
T8.5.6  10-step CoWork agentic task: only 1 cold start (first call), remaining 9 are warm
        (manual — measure wall clock time in CoWork; record in TEST_RESULTS.md)
```

---

### M8.7 — Replace `pgrep` singleton guard with lock file ✅

**Implemented.** `SingletonLock.swift` acquires `flock(LOCK_EX | LOCK_NB)` on
`$TMPDIR/gnucash-mcp.lock` at startup and writes the PID to the file.
`gnucash-mcp stop` reads the PID from the lock file instead of shelling out to
`pgrep`. `shellOutput()` helper removed from `App.swift` entirely.

**Lock file:** `URL.temporaryDirectory/gnucash-mcp.lock` (`$TMPDIR/gnucash-mcp.lock`)

**Tests:**
```
T8.7.1  Second invocation with lock already held exits non-zero and prints "already running"
T8.7.2  After first process exits, lock is released and a new invocation succeeds
```

---

### M8.8 — Replace `container system status/start` CLI calls with SDK

**Goal:** Remove the two `Process()` calls in `ContainerAPIClient.swift`
(`ContainerSystem.ensureRunning()`) that shell out to the `container` CLI.
The comment already marks this as a TODO pending SDK documentation stability.

**Approach:**
- Use `LiveManagedContainerBackend` (already imported via `ContainerAPIClient`) to check
  whether the container system daemon is reachable: attempt a lightweight SDK call
  (e.g. `backend.images()`) and treat a connection failure as "system not running"
- If not running, surface a clear `ContainerError.containerSystemNotRunning` rather than
  attempting to start it programmatically (starting the daemon from inside an app is
  outside the SDK's intended use; users should have the daemon running)
- Remove `ContainerSystem.ensureRunning()` or replace its body with the SDK check

**Prerequisite:** Verify that the Container SDK XPC connection error is reliably
distinguishable from other errors (e.g. image-not-found) so the not-running path
is unambiguous.

**Tests:**
```
T8.8.1  When SDK backend returns a connection error, proxy exits with ContainerError.containerSystemNotRunning
T8.8.2  No Process() calls remain in ContainerAPIClient.swift (static assertion / grep in CI)
```

---

