# Phase 8 — Hardening and Claude Desktop Integration

## Phase 8 — Hardening and Claude Desktop Integration

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
- `scripts/verify-backup.zsh` — weekly manual trigger:
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
  - Writes `claude_desktop_config.json` entry (`streamable-http`, `localhost:8980`)
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
    <string>/usr/local/bin/gnucash-mcp</string>
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
  <string>/tmp/gnucash-mcp.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/gnucash-mcp-error.log</string>
</dict>
</plist>
```

`KeepAlive: SuccessfulExit: false` means launchd restarts the proxy if it crashes
but does NOT restart it after a clean `gnucash-mcp stop` (exit 0). This is the
correct behaviour: stop is intentional, crash is not.

**Note:** The Swift proxy is the only thing that starts at login. No container runs
at login — containers are spun up on first tool call. Claude Desktop connects to
`localhost:8980` independently once the proxy is running.

**Tests:**
```
T8.4.1  gnucash-mcp install writes correct config entries without error
T8.4.2  Claude Desktop shows gnucash-myproject connected after launchctl load + restart
T8.4.3  get_project_summary() callable from Claude.ai chat window
T8.4.4  After clean gnucash-mcp stop (exit 0), launchd does NOT restart the proxy
T8.4.5  After simulated crash (kill -9 on proxy), launchd restarts it within 5s
T8.4.6  Server startup latency < 2s from gnucash-mcp start to first tools/list response
        (proxy only — no container started yet)
T8.4.7  First tool call latency < 1.5s (includes container start via ContainerAPIClient)
T8.4.8  CoWork session shows gnucash-myproject tools available via SDK bridge
T8.4.9  Mac sleep → wake → tool call succeeds (KU-11 sleep/wake recovery confirmed;
        record in TEST_RESULTS.md)
```

---

### Phase 8 exit criteria

- Swift proxy registered via launchd, starts at login, survives crash-restart
- Claude Desktop connected via `streamable-http` to `localhost:8980`
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
- Swift proxy issues `Mcp-Session-Id` in `initialize` response
- `sessions: [SessionID: PoolEntry]` dictionary replaces single `pool` entry
- On `tools/call` with session ID: reuse that session's container, extend TTL
- On session termination (client sends DELETE `/mcp` with session ID per spec):
  drain that session's container immediately
- TTL fallback (dirty disconnect — client quits without terminating): 60s idle
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
    response.sessionID = sessionID          // Mcp-Session-Id header
    sessions[sessionID] = PoolEntry(...)    // create entry; container starts on first call
    return response
}
```

**Tests:**
```
T8.5.1  Two concurrent initialize requests produce two distinct session IDs
T8.5.2  Tool calls within same session reuse warm container (no cold start after first call)
T8.5.3  Tool call with unknown/expired session ID starts fresh container, returns result
T8.5.4  Session termination (DELETE /mcp) drains that session's container within 2s
T8.5.5  After 60s idle, expired session's container is reaped by reap loop
T8.5.6  10-step CoWork agentic task: only 1 cold start (first call), remaining 9 are warm
        (manual — measure wall clock time in CoWork; record in TEST_RESULTS.md)
```

---

