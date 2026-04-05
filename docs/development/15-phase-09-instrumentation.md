# Phase 9 — Observability and Hybrid Architecture Profiling

**Goal:** Instrument the Swift proxy and Python dispatcher to collect per-call
latency, session structure, and token-budget-proxy data. The output is a metrics
stream and analysis script that empirically answers the question in Appendix E:
whether the hybrid gpt-oss:20b coordinator (Option D) is warranted, and which
sessions and tools are the strongest candidates for offloading.

**Prerequisites:** Phase 5 complete (Swift proxy exists); M8.1 complete (JSONL
log streams established). Phase 9 runs concurrently with normal ledger operation —
there is no gate on having all prior phases complete. Collect at least two weeks of
live data before running M9.4.

**Dependency on M8.1:** M8.1 establishes the two log file paths
(`proxy.log` and `mcp.log`). Phase 9 adds a third stream (`metrics.jsonl`,
`dispatch-timing.jsonl`) at different granularity — summaries and histograms
rather than event-by-event narrative. Do not merge the streams; they serve different
audiences (operations vs. architecture analysis).

---

### M9.1 — Proxy-side metrics collection

**Deliverables:** Additions to `Sources/gnucash-mcp/Metrics.swift`:

- One `CallRecord` written to `~/.local/share/gnucash-mcp/metrics.jsonl` per
  completed tool call:

```swift
struct CallRecord: Codable {
    let timestamp: String       // ISO 8601
    let sessionID: String?      // nil until Phase 2 proxy (M8.5)
    let tool: String            // e.g. "receive_invoice"
    let method: String          // "tools/call", "resources/read", etc.
    let durationMs: Int         // proxy-side wall clock: receive → send response
    let coldStart: Bool         // true = pool miss; container started for this call
    let responseSizeBytes: Int  // raw JSON response size; token proxy
    let success: Bool           // false if dispatcher returned JSON-RPC error
}
```

- One `SessionSummary` written at session end (Phase 2 proxy) or inferred by the
  analysis script (Phase 1 proxy, grouped by 5-minute idle gaps):

```swift
struct SessionSummary: Codable {
    let sessionID: String?
    let start: String           // ISO 8601
    let end: String
    let durationSeconds: Int
    let toolSequence: [String]  // ordered list of tool names called
    let totalCalls: Int
    let writeOps: Int           // calls to write tools (receive_invoice, pay_invoice, etc.)
    let walEntries: Int         // WAL entries written; sourced from dispatcher response
    let coldStarts: Int
}
```

**`gnucash-mcp metrics` subcommand** — reads `metrics.jsonl`, prints a table:

```
$ gnucash-mcp metrics
Tool                      calls   p50ms  p95ms   cold%  avg_resp_kb
__unlock_ledger__            18       8     22      11%         1.2
get_project_summary          41      38     91       7%         2.8
list_transactions            33      72    160       9%         8.4
receive_invoice              15     340    820      27%         0.9
pay_invoice                  12     290    710      25%         0.9
get_ap_aging                 22      58    130       9%         4.1
get_budget_vs_actual         19      61    144       5%         6.3
get_audit_log                11      44    112       9%         3.7
...

Sessions: 23 total | avg 5.4 tools/session | max 17 | write sessions: 14
Cold starts: 38 of 139 calls (27%) | avg cold-start penalty: 410ms
Total response data: 1.8 MB across all sessions
```

**`--since` flag:** `gnucash-mcp metrics --since 2025-06-01` to filter by date.
**`--json` flag:** Machine-readable output for the analysis script.

**Tests:**
```
T9.1.1  metrics.jsonl entry written for each tool call with all required fields
T9.1.2  durationMs reflects wall-clock time from request receipt to response sent
T9.1.3  coldStart is true for pool-miss calls and false for pool-hit calls
        (verify by timing: cold calls should show durationMs > 300ms)
T9.1.4  responseSizeBytes matches the byte length of the JSON response body
T9.1.5  gnucash-mcp metrics reads metrics.jsonl and outputs p50/p95 per tool
T9.1.6  gnucash-mcp metrics --json emits valid JSON (parse with jq)
T9.1.7  gnucash-mcp metrics --since flag filters correctly (entries before date absent)
T9.1.8  Static calls (initialize, tools/list, resources/read static) recorded but
        flagged method != "tools/call"; excluded from tool-name columns
T9.1.9  metrics.jsonl survives proxy restart — append-only, not truncated on start
```

---

### M9.2 — Python dispatcher timing instrumentation

**Deliverables:** `src/instrumentation.py` — timing context manager used by the
dispatcher to bracket each phase of a tool call:

```python
import time, json
from dataclasses import dataclass, field
from pathlib import Path

TIMING_LOG = Path("/data/dispatch-timing.jsonl")

@dataclass
class TimingRecord:
    timestamp: str
    tool: str
    gnc_open_ms: int    # time from Session() call to book ready for queries
    tool_exec_ms: int   # time from book open to session.save() call
    gnc_close_ms: int   # time from save() to end() returning
    total_ms: int       # wall clock across all three phases
    success: bool
    error: str = ""

def record_timing(tool: str, gnc_open_ms: int, tool_exec_ms: int,
                  gnc_close_ms: int, success: bool, error: str = "") -> None:
    rec = TimingRecord(
        timestamp=datetime.utcnow().isoformat() + "Z",
        tool=tool,
        gnc_open_ms=gnc_open_ms,
        tool_exec_ms=tool_exec_ms,
        gnc_close_ms=gnc_close_ms,
        total_ms=gnc_open_ms + tool_exec_ms + gnc_close_ms,
        success=success,
        error=error,
    )
    with TIMING_LOG.open("a") as f:
        f.write(json.dumps(dataclasses.asdict(rec)) + "\n")
```

Dispatcher integration in `src/session.py`:

```python
def run_with_timing(tool: str, fn):
    t0 = time.monotonic_ns()
    with GnuCashSession() as session:
        t1 = time.monotonic_ns()
        result = fn(session)
        t2 = time.monotonic_ns()
    t3 = time.monotonic_ns()
    record_timing(
        tool=tool,
        gnc_open_ms=(t1 - t0) // 1_000_000,
        tool_exec_ms=(t2 - t1) // 1_000_000,
        gnc_close_ms=(t3 - t2) // 1_000_000,
        success=True,
    )
    return result
```

**Purpose of the three phases:**
- `gnc_open_ms` — GnuCash session startup overhead. If this consistently exceeds
  300ms it is the bottleneck; revisit MC-2 (persistent session) review trigger.
- `tool_exec_ms` — actual business logic. High values for specific tools indicate
  Python query optimization opportunities.
- `gnc_close_ms` — `save()` + `end()` (XML write). High values indicate book size
  growth; normal for XML but worth tracking over the project lifetime.

**Tests:**
```
T9.2.1  dispatch-timing.jsonl created on first tool call; entries have all four fields
T9.2.2  gnc_open_ms + tool_exec_ms + gnc_close_ms == total_ms (exact integer check)
T9.2.3  Read-only tool (get_project_summary) has gnc_close_ms ≈ 0
        (no session.save() called for read-only tools)
T9.2.4  Write tool (receive_invoice) has gnc_close_ms > 0
T9.2.5  Timing records survive container restart — written to /data/ inside sparsebundle
T9.2.6  Failed tool call produces record with success=false and non-empty error field
T9.2.7  gnc_open_ms variance across 10 cold-start calls < 2× the mean
        (session startup is stable; large variance signals VirtioFS contention)
```

---

### M9.3 — Session replay log

**Deliverables:** Session-level summary appended to
`~/.local/share/gnucash-mcp/sessions.jsonl` at the end of each session (Phase 2
proxy) or reconstructed from `metrics.jsonl` by the analysis script (Phase 1 proxy).

```json
{
  "session_id": "3f8a1c2d",
  "start": "2025-06-15T10:32:00Z",
  "end": "2025-06-15T10:34:18Z",
  "duration_s": 138,
  "tool_sequence": [
    "__unlock_ledger__",
    "get_project_summary",
    "list_transactions",
    "receive_invoice",
    "get_ap_aging"
  ],
  "total_calls": 5,
  "write_ops": 1,
  "wal_entries": 1,
  "cold_starts": 2,
  "total_response_kb": 18.4,
  "hybrid_candidate": false
}
```

`hybrid_candidate` is set by the proxy (or analysis script) when
`total_calls >= 6 OR (write_ops >= 3 AND total_calls >= 4)`.
This is the threshold at which offloading to the Option D gpt-oss coordinator
saves at least one Claude context-window overhead worth of tokens.

**Tests:**
```
T9.3.1  Session record written after last tool call in a conversation
T9.3.2  tool_sequence order matches the actual call order (verify against proxy.log)
T9.3.3  write_ops count matches WAL entries written (cross-reference mcp-wal.jsonl)
T9.3.4  hybrid_candidate true for a synthetic 7-call session; false for a 3-call session
T9.3.5  total_response_kb sum matches sum of responseSizeBytes in CallRecords for that session
```

---

### M9.4 — Hybrid architecture readiness report

**Deliverables:** `scripts/analyze-sessions.py` — offline analysis script.

Reads `metrics.jsonl` and `dispatch-timing.jsonl`; produces a Markdown report
`HYBRID_READINESS.md` alongside a JSON summary for machine consumption.

**Report sections:**

**1. Session structure**
```
Total sessions: 47
Hybrid candidates (≥6 calls): 11 (23%)
Avg calls per session: 4.8
Max calls per session: 17  ← flag for hybrid review
Write sessions: 31 (66%)
```

**2. Per-tool latency table (from dispatch-timing.jsonl)**
```
Tool                    calls   gnc_open  tool_exec  gnc_close  total_p95
get_project_summary        41     280ms       15ms        0ms     365ms
receive_invoice            15     295ms       38ms      210ms     890ms
list_transactions          33     270ms       68ms        0ms     490ms
get_budget_vs_actual       19     285ms       71ms        0ms     510ms
```

**3. Cold-start analysis**
```
Cold-start rate: 29% (41 of 139 calls)
Avg cold-start overhead: +380ms vs warm
Tools most affected by cold starts: receive_invoice (33%), pay_invoice (31%)
Recommendation: increase pool TTL from 5s → 15s to reduce write-tool cold starts
```

**4. Token-budget proxy (response volume as surrogate)**
```
Avg total response data per session: 22 KB
High-volume sessions (>50 KB): 6 sessions
High-volume tools: list_transactions (avg 8.4 KB), get_budget_vs_actual (avg 6.3 KB)

Claude context consumed (estimated at 4 bytes/token):
  Startup tool schemas (full profile): ~8,000 tokens
  Avg per-session tool responses:      ~5,500 tokens
  Total avg session cost:              ~13,500 tokens (≈ 0.3 × 5-hour Pro window)
```

**5. Hybrid architecture recommendation**
```
Hybrid candidate sessions: 23% of total
If Option D were active for those sessions:
  Estimated Claude delegation cost: ~1,000 tokens per session
  Estimated Claude context saved:   ~12,500 tokens per qualifying session
  Break-even: >1 qualifying session per 5-hour Pro window

RECOMMENDATION: Implement Option D when qualifying sessions reach ≥2 per day.
Current rate: 0.5 qualifying sessions/day → DEFER Option D.
Revisit when rate exceeds threshold.
```

**Tests:**
```
T9.4.1  analyze-sessions.py runs on ≥10 sessions of recorded data without error
T9.4.2  Session count and hybrid_candidate count in report match sessions.jsonl
T9.4.3  Per-tool latency table matches manual inspection of dispatch-timing.jsonl sample
T9.4.4  Cold-start rate in report matches manual count from a 20-entry metrics.jsonl sample
T9.4.5  HYBRID_READINESS.md written and human-readable (no JSON raw output in Markdown body)
T9.4.6  JSON summary emitted alongside Markdown; parseable by jq
T9.4.7  Recommendation section updates correctly when synthetic data pushed above threshold:
        inject 20 sessions with total_calls=8 → report recommends Option D
```

---

### Phase 9 exit criteria

- `metrics.jsonl` collecting data in production for ≥2 weeks with ≥30 sessions
- `dispatch-timing.jsonl` showing stable `gnc_open_ms` variance (< 2× mean)
- `gnucash-mcp metrics` produces a complete p50/p95 table
- `analyze-sessions.py` generates `HYBRID_READINESS.md` with a concrete recommendation
- If cold-start rate for write tools > 25%: increase pool TTL in `ContainerPool.swift`
  and re-run one week of data; document new rate
- If hybrid candidate rate > 2 sessions/day: proceed with Option D subagent from
  Appendix E; update Appendix E Option D status from "deferred" to "active"
- `HYBRID_READINESS.md` committed to repository alongside final metrics snapshot

---

### Relationship to Appendix E

The three metrics that drive the Option D decision map directly to Appendix E sections:

| Metric | Appendix E implication |
|---|---|
| Hybrid candidate rate (sessions/day) | When to stand up the gpt-oss:20b subagent |
| Tool-call frequency by tool name | Which tools to expose via the subagent MCP interface |
| Total response volume per session | Whether Claude context savings justify Option D overhead |
| `gnc_open_ms` mean | If > 400ms consistently: revisit MC-2 persistent session; this also changes Option D latency math |

The readiness report's threshold (`≥2 qualifying sessions/day`) corresponds to the
point at which the Option D delegation overhead (~1,000 Claude tokens per session)
is recovered within a single 5-hour Pro window.

---
