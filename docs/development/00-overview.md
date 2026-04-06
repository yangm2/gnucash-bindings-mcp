# GnuCash MCP Server — Overview


This document plans the phased development of a GnuCash-backed MCP (Model Context
Protocol) server that Claude uses as the authoritative read-write interface to the
project ledger for a construction project. A native macOS GnuCash install serves
as a read-only inspection GUI.

### Stack summary

| Layer | Technology | Notes |
|---|---|---|
| Ledger storage | GnuCash 5.x, XML backend | `.sparsebundle` on macOS APFS |
| MCP proxy | Swift binary (`gnucash-mcp`) | Persistent daemon; owns MCP protocol + lifecycle |
| MCP transport | Streamable HTTP, `localhost:8980` | Proxy listens; Claude Desktop connects |
| CoWork integration | Claude Desktop SDK bridge | CoWork VM → Desktop → proxy |
| Tool catalog | Swift structs, compiled-in | Static; no container needed for `tools/list` |
| Static resources | Swift string constants | `gnucash://book-setup-guide` etc.; no container |
| Tool architecture | 3-tier: operational / administrative / resources | See MC-8 |
| Container runtime | Ubuntu 24 Linux container, per-request pool | Apple Container on macOS 26; pool size 1, 5s TTL |
| GnuCash bindings | Official Python bindings (`python3-gnucash`) | `ppa:gnucash/ppa` → 5.14 (`1:5.14-0build1`); no build from source |
| Python dispatcher | One-shot stdin→stdout JSON-RPC handler | No FastMCP/uvicorn; pure dispatch |
| Volume mount | APFS sparsebundle managed by Swift proxy | `hdiutil` via `Process`; mount before first call |
| Write-ahead log | Append-only JSONL | Crash recovery / replay |
| Snapshot management | APFS `tmutil` + `diskutil apfs` | Pre-session snapshots |
| GUI | macOS GnuCash 5.15 | Read-only via `-readonly` mount |
| GUI wrapper | zsh (`gnucash-browse`) | Read-only mount + wait on GnuCash PID |

### Key architectural decisions deferred to Phase 0

Several decisions have non-obvious answers and must be validated by experiment before
building on top of them. Phase 0 exists entirely to resolve these.

---

## Known Unknowns

The following unknowns must be resolved — in the order listed — before later phases
can proceed with confidence. Each has a designated spike in Phase 0.

| # | Unknown | Risk if wrong | Resolved in |
|---|---|---|---|
| KU-1 | Does `python3-gnucash` from `ppa:gnucash/ppa` on Ubuntu Noble arm64 install cleanly and successfully `import gnucash` inside an Apple Container? The PPA publishes the package for arm64/Noble but this has not been tested in the Apple Container VirtioFS environment. | If bindings fail, must pivot to piecash or XML parsing | Phase 0, Spike A |
| KU-2 | Does VirtioFS correctly expose an APFS sparsebundle mount point to the Linux container with read-write semantics? | File sharing architecture fails; must use alternative (SSHFS, copy-based) | Phase 0, Spike B |
| KU-3 | Can GnuCash 5.14 (container, from PPA) open a file last saved by GnuCash 5.15 (macOS) without triggering a schema migration? One minor version gap. | Cross-version file sharing fails; must pin both to same version | Phase 0, Spike C |
| KU-4 | Does `hdiutil attach -readonly` on a `.sparsebundle` genuinely prevent writes at the kernel level, or does macOS GnuCash find a writable path? | Read-only guarantee is illusory; need alternative enforcement | Phase 0, Spike D |
| KU-5 | Does `tmutil localsnapshot` work on a mounted sparsebundle volume (not the boot volume)? | Must use file-copy backup instead of APFS snapshots | Phase 0, Spike E |
| KU-6 | Does the GnuCash Python binding `Session.save()` durably flush to the XML file on disk, or does it require `Session.end()`? | Data loss on MCP crash between save and end | **Answered by example scripts** — `save()` and `end()` are separate: `save()` flushes to disk (always required for file backend per Session class docstring); `end()` only releases the `.LCK` file. Data is durable after `save()` alone. Additional finding: `new_book_with_opening_balances.py` calls `session.save()` immediately after opening a new book, before any mutations, with a comment that skipping this early save caused corruption. Session manager must do the same. |
| KU-7 | Does `open --wait-apps` in the zsh wrapper reliably block until the GnuCash process fully exits, including cleanup? | Premature detach of sparsebundle while GnuCash still holds file handles | Phase 5, GUI wrapper test |
| KU-8 | Does Claude Desktop's `streamable-http` connector accept a plain HTTP (non-TLS) connection to `localhost:8980` from a natively-running Swift proxy? | Must use HTTPS or an alternate registration mechanism | Phase 0, Spike F |
| KU-9 | Does Claude Desktop's `streamable-http` MCP connector correctly bridge to CoWork's VM via the SDK passthrough layer? | CoWork cannot use GnuCash tools despite Claude Desktop connecting successfully | Phase 0, Spike F |
| KU-10 | Does Claude reliably read `gnucash://session-context` at session start via the `server_instructions` reference, or does it skip it? | Tool conventions and resource index not loaded; Claude makes suboptimal tool choices without the context | Phase 1, integration test |
| KU-11 | After Mac sleep/wake, does the pooled container handle held by the Swift proxy become stale (VM suspended/killed)? How does `ContainerAPIClient` signal this? | Proxy forwards request to a dead container; tool call hangs or returns garbage | Phase 5, Swift proxy integration |
| KU-12 | Ubuntu 26.04 LTS (releasing end of April 2026) — does `ppa:gnucash/ppa` publish arm64 packages for 26.04 in time to use it as the container base? What version of GnuCash ships in universe if the PPA is not yet available? | Must stay on 24.04 or ship a stale GnuCash version; Spike C re-validation required if base changes | Phase 0, Spike G |
| KU-13 | Can `pdfplumber` (or `pymupdf`) reliably extract structured fields (vendor, invoice number, line items, totals) from text-layer PDFs as produced by typical architecture/engineering firms and the project bank? If PDFs are scanned, OCR adds a dependency (tesseract) and quality risk. | PDF invoice and statement workflows require Claude vision input (high token cost) or manual data entry; path-based container mount approach fails for scanned docs | Phase 0, Spike H |

---

## Microarchitectural Choices

These decisions are made upfront based on prior design discussion but are
flagged for review after Phase 0 findings.

### MC-1: XML vs SQLite backend
**Decision:** XML backend.
**Rationale:** Built-in timestamped backup files (`.YYYYMMDDHHMMSS.gnucash`) provide
automatic point-in-time recovery without extra tooling. Lock mechanism is a simple
`.LCK` filesystem file, easier to inspect and clear than a `gnclock` SQL table.
GnuCash's own FAQ recommends XML for the serial-access multi-machine use case.
**Review trigger:** If XML write performance becomes a bottleneck under frequent MCP
tool calls (unlikely for this project scale).

### MC-2: Short-lived vs persistent GnuCash sessions in MCP
**Decision:** Short-lived sessions — open, write, save, end — per MCP tool call.
**Rationale:** Releases the `.LCK` file between calls, allowing the macOS GUI to be
opened opportunistically. Avoids in-memory state accumulation. For a project ledger
with infrequent writes (invoice receipt, payment, tranche funding), session startup
overhead (~100–500ms) is acceptable.
**Review trigger:** If session startup overhead becomes perceptible during
interactive use. Fallback: persistent session with explicit `flush()` per write.

### MC-3: Write-ahead log format
**Decision:** Append-only JSONL at `$BOOK_DIR/mcp-wal.jsonl`, with committed
entries tracked by `committed_at` field.
**Rationale:** Survives container crash. Human-readable. Diff-friendly for git.
Entries written before GnuCash session opens; `committed_at` set after
`session.end()` returns. On MCP startup, entries without `committed_at` are replayed.
**Review trigger:** If replay logic becomes complex due to partial transaction state.

### MC-4: MCP transport
**Decision:** Streamable HTTP, not stdio.
**Rationale:** CoWork runs inside its own Apple Virtualization Framework Linux VM
(Ubuntu 22.04, separate from our Apple Container). Claude Desktop's stdio transport
spawns MCP servers as macOS-host child processes — it cannot spawn processes inside
a different VM. The Swift proxy (MC-9) runs as a persistent macOS process and owns
the HTTP listener on `localhost:8980`. Claude Desktop connects via `streamable-http`,
and CoWork receives tools through Claude Desktop's SDK bridge.

`claude_desktop_config.json` entry (managed by Swift proxy's `install` subcommand):
```json
{
  "mcpServers": {
    "gnucash-myproject": {
      "type": "streamable-http",
      "url": "http://localhost:8980/mcp"
    }
  }
}
```

The Swift proxy HTTP server runs on `localhost:8980`. The GnuCash container does
**not** publish a port — the proxy dispatches to containers via `ContainerAPIClient`
and communicates over stdin/stdout (one-shot per request). There is no uvicorn,
no FastMCP HTTP server inside the container.

**Review trigger:** If Apple Container's port publishing does not expose
`localhost:8980` to macOS host (KU-8). In that case the Swift proxy still owns
the HTTP listener — the container switches to stdin/stdout dispatch and the
proxy forwards via `Process` pipes rather than HTTP. See MC-9 for the full
Swift proxy architecture and fallback paths.

### MC-5: Container image base
**Decision:** `ubuntu:24.04` (Noble) with GnuCash and Python bindings installed
from `ppa:gnucash/ppa` via `apt-get install python3-gnucash`.
**Rationale:** The GnuCash packaging team PPA (`ppa:gnucash/ppa`) publishes
`python3-gnucash` for Ubuntu Noble arm64 — the exact platform the Apple Container
runs on. This eliminates the multi-hour build-from-source requirement that was
the original rationale for this decision. The PPA version tracks GnuCash releases
promptly and is maintained by the GnuCash upstream team.

**Version selection:** The PPA currently provides GnuCash **5.14** (`1:5.14-0build1`)
for Noble. The macOS GnuCash GUI is at 5.15 — a one-minor-version gap, the same
situation the original build-from-source plan assumed. Spike C validates whether
5.14 can open files saved by 5.15 without migration. Pin the container to
`python3-gnucash=1:5.14-0build1` for reproducible builds; update when the PPA
publishes 5.15.

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:gnucash/ppa && \
    apt-get update && \
    apt-get install -y python3-gnucash
```

**Dockerfile build time:** minutes, not hours. No cmake, no swig, no source clone.

**Review trigger:** If Spike C finds that 5.14 cannot open 5.15-saved files:
1. Pin macOS GnuCash to 5.14 (download specific .dmg from gnucash.org) — matches
   the container exactly, eliminating the version gap
2. Wait for the PPA to publish 5.15 for Noble, then update the container pin
3. Fall back to build from source at exactly 5.15 (original plan)

### MC-6: Chart of accounts structure
**Decision:** Model each vendor as its own AP account under `Liabilities`.
Trade expense accounts under `Expenses:Construction` are one-per-trade, shared
across all vendors who perform that trade. Professional fee vendors (architects,
engineers) get their own dedicated expense accounts because their contracts are
individually named and scoped.

**Rationale:** The original design pre-mapped Construction expense accounts to
the prior GC's ROM Labor/Subcontracts/Materials structure. That bid was not accepted.
The new GC will deliver their own line-item breakdown in pre-construction, and that
structure — whatever it is — becomes the expense account hierarchy and the GnuCash
budget amounts simultaneously. Using GnuCash's native budget feature means the
budget is live data in the book, not hardcoded Python constants.

**Two vendor types:**

| Type | AP account | Expense account | Example |
|---|---|---|---|
| Trade | `Liabilities:AP — {vendor}` | Existing `Construction:{trade}` shared account | Pacific Crest Electrical → `Construction:Electrical` |
| Professional | `Liabilities:AP — {vendor}` | New `Expenses:{category} — {vendor}` | Acme Architecture → `Architecture — Acme Architecture` |

Trade vendors bill to a shared trade expense account. Multiple vendors can bill to
the same trade account over the project lifetime — vendor replacement mid-trade or
a GC sub passing through an invoice are handled identically. The trade expense
account accumulates total spend for that trade regardless of which vendor performed
the work. `vendor_add` with `trade=` uses an existing account; no new expense
account is created.

Professional fee vendors each get their own expense account because their contracts
are individually named, individually budgeted, and individually tracked for AP aging.

**Permits and government fees:** Permits are prepaid — no AP relationship with the
jurisdiction. Post directly against `Expenses:Permits and Fees` using
`post_transaction`. A permit expediter (a hired consultant) is a professional vendor
with their own AP account. The jurisdiction itself is never a vendor.

**GC pass-through invoices:** When the GC subs out a trade and passes the invoice
through, the GC is still the vendor (`AP — [GC]`) and the expense splits to the
relevant trade account(s). For single-line pass-throughs, `receive_invoice` works.
For multi-line GC invoices spanning several trades, use `post_transaction` with
explicit splits.

**Fixed accounts (known now):**
```
Assets
  Project Checking — First Project Bank
Liabilities
  AP — Acme Architecture
  AP — Peak Structural
  AP — Meridian MEP
  AP — Summit HVAC
  AP — [GC name TBD]
Equity
  Owner Capital — First Project Bank
Income
  Interest Income — Project Account
Expenses
  Architecture — Acme Architecture       ← professional; dedicated per-vendor account
  Structural Engineering — Peak Structural
  MEP Consulting — Meridian MEP
  HVAC Engineering — Summit HVAC
  Permits and Fees                        ← direct payment; no AP vendor
  Construction         ← trade parent; children created from GC budget
  Change Orders        ← ECO tracking (see Phase 4)
```

**`Expenses:Construction` children** are created during pre-construction when
the GC delivers their budget. Each GC line item becomes a sub-account:
```
  Construction:Demo
  Construction:Framing
  Construction:Electrical        ← shared; any electrical vendor bills here
  Construction:Plumbing
  Construction:HVAC
  Construction:Tile
  Construction:Finish Carpentry
  Construction:Painting
  ... (GC-defined)
  Construction:Contractor Fee
  Construction:Allowances    ← if GC uses allowance line items
```

**GnuCash budget amounts** are set on each `Construction:*` account to match
the GC's line-item pricing. `get_budget_vs_actual()` then queries the live
GnuCash budget rather than hardcoded constants.

**Change Orders** sit under `Expenses:Change Orders` as a parallel hierarchy
mirroring the construction accounts:
```
  Change Orders:Demo
  Change Orders:Electrical
  ... (mirrors Construction:* structure)
  Change Orders:New Scope   ← for COs that add scope not in original contract
```

This separation keeps the original contract budget clean while making ECO costs
visible independently and in aggregate.

### MC-7: Snapshot naming convention
**Decision:** `gnucash-mcp-YYYYMMDD-HHMMSS` prefix for MCP-created snapshots.
Prune to keep last 10. GnuCash auto-backups (`.YYYYMMDDHHMMSS.gnucash`) retained
per GnuCash default (30 days).
**Rationale:** Distinguishes MCP snapshots from Time Machine and system snapshots
in `diskutil apfs listSnapshots` output.

---

### MC-8: Tool tiering and resource-based lazy context

**Decision:** Three-tier tool architecture with MCP Resources for deferred context.

**Rationale:** MCP loads all tool schemas into the context window at session start.
With ~21 tools, startup cost is ~4,500–6,000 tokens — manageable but worth
controlling as the project grows. More importantly, book setup and vendor management
tools are used infrequently; their detailed usage docs should not occupy context in
everyday operational sessions.

**Tier 1 — Operational tools** (loaded always, ~16 tools, ~5,500 tokens):
Full descriptions. Used in most sessions. Prefixed by function, not namespace.
```
# Read
get_account_balance, list_accounts, list_transactions, get_transaction,
get_project_summary, get_budget_vs_actual, get_ap_aging, get_audit_log

# Write (core)
fund_project, receive_invoice, pay_invoice, post_transaction, post_interest

# Write (correction)
update_transaction, void_transaction, delete_transaction
```

**Tier 2 — Administrative tools** (loaded always, ~20 tools, ~1,200 tokens):
Minimal one-line descriptions. Detail lives in a resource pointed to by the
description. `book_` prefix for chart-of-accounts operations; `vendor_` for
contractor management; `budget_` for GnuCash budget operations; `eco_` for
engineering change orders.
```
book_add_account, book_get_account_tree, book_verify_structure,
book_set_opening_balance, book_rename_account, book_move_account,
book_delete_account,
vendor_add, vendor_list, vendor_get_details, vendor_rename,
vendor_update, vendor_delete,
budget_create, budget_list, budget_get, budget_set_amount,
budget_update, budget_delete,
eco_create, eco_list, eco_get, eco_approve, eco_void
```

**MCP Resources** (zero startup cost, fetched on demand):
```
gnucash://session-context         — tool groups, conventions, and resource index (read at session start)
gnucash://book-setup-guide        — account_type values, naming conventions
gnucash://vendor-guide            — expense_category options for vendor_add
gnucash://expected-chart          — full expected account tree (used by book_verify_structure)
gnucash://budget-guide            — GnuCash budget workflow; budget_create → budget_set_amount
gnucash://eco-guide               — ECO numbering, direction conventions, approval workflow
gnucash://vendors                 — live vendor list with AP balances (requires container)
```

**`gnucash://session-context` resource** — static MCP resource served by the Swift
proxy (no container required). Returns tool groups, naming conventions, and the
resource index. Referenced in `server_instructions` so Claude reads it at session
start. Entirely static — the proxy injects `GNUCASH_BOOK_PATH` as an environment
variable when spawning the container; the book path is never passed through the MCP
protocol and never appears in Claude's context.

**`server_instructions`** — returned in the Swift proxy's `initialize` response,
directing Claude to read `gnucash://session-context` before calling any tool.
KU-10 tracks whether Claude reliably acts on this. If not, the compound tool
analysis in Phase 9 M9.4 will surface `gnucash://session-context` reads as
the dominant session-start pattern, confirming or refuting compliance.

**Token accounting (steady-state, `full` profile):**
- Tier 1 + Tier 2 tool schemas at startup: ~8,000 tokens (~36 tools)
- `gnucash://session-context` read + response: ~300 tokens
- Total before first real question: ~8,300 tokens
- On-demand resource fetch (e.g. `gnucash://vendor-guide`): ~200–400 tokens if needed

Use `gnucash-mcp start --profile operational` to reduce to ~4,600 tokens for
routine ledger sessions. See MC-10 for the full profile selection system.

**Review trigger:** If total tool count exceeds 30, evaluate the builder-pattern
progressive disclosure path in MC-9 (Phase 3 proxy): start in setup-only mode
exposing book_* tools, promote to full operational catalog after
`book_verify_structure` passes. This defers until Claude Desktop implements
`tools/listChanged` handling.

---

### MC-9: macOS lifecycle layer and MCP protocol ownership

**Decision:** Swift binary (`gnucash-mcp`) owns the MCP protocol layer, the HTTP
server, the sparsebundle mount lifecycle, and the container pool. The Python
container is a one-shot stdin→stdout dispatcher with no HTTP server.

**Rationale:** Moving the MCP protocol layer into Swift produces a clean split:
the proxy handles everything macOS-native (volume mounts, container lifecycle,
HTTP, tool schemas), while the container handles everything GnuCash-specific
(sessions, WAL, tool implementations). Tool schemas and static resources are
Swift structs compiled into the binary — `tools/list` and `resources/read` for
static resources require no container at all, keeping cold-start latency out of
the discovery path. The architecture mirrors `buck2-macos-local-reapi` directly:
the Swift layer receives protocol requests and dispatches containers via
`ContainerAPIClient`.

**Responsibility split:**

| MCP message | Handler | Container needed? |
|---|---|---|
| `initialize` | Swift proxy | No |
| `notifications/initialized` | Swift proxy | No |
| `tools/list` | Swift proxy (compiled catalog) | No |
| `resources/list` | Swift proxy (static + templates) | No |
| `resources/read` — static | Swift proxy (string constants) | No |
| `resources/read` — dynamic (`gnucash://vendors`) | Container via pool | Yes |
| `tools/call` — any | Container via pool | Yes |

**Swift proxy owns:**
- MCP HTTP server on `localhost:8980` (NIO-based, persistent, ~5MB)
- `initialize` / `tools/list` / `resources/list` responses (static, compiled)
- Static resource content (`gnucash://session-context`, `gnucash://book-setup-guide`,
  `gnucash://vendor-guide`, `gnucash://expected-chart`)
- `server_instructions` field content
- Sparsebundle mount lifecycle (`hdiutil` via `Process`)
- Container pool management (size 1, 5s TTL)
- Per-request container dispatch for tool calls and dynamic resources
- SIGTERM / SIGINT handling → drain pool → detach sparsebundle → exit
- Pre-session APFS snapshot (via `Process` / `tmutil`)

**Python container owns:**
- GnuCash session lifecycle (open, write, save, end — MC-2)
- All tool call implementations (Tier 1 + Tier 2)
- WAL read/write (MC-3)
- Dynamic resource queries (`gnucash://vendors`)
- Single-request stdin→stdout JSON-RPC protocol:
  ```python
  # gnucash_mcp/__main__.py
  import json, sys
  from gnucash_mcp.dispatch import dispatch

  request = json.loads(sys.stdin.read())
  response = dispatch(request)
  json.dump(response, sys.stdout)
  ```

**Container pool — size 1, TTL-based (Phase 1 proxy):**

```
Tool call arrives
  └── pool entry exists and not expired?
        ├── YES → forward to warm container, reset TTL
        └── NO  → start new container via ContainerAPIClient
                  forward request
                  store handle in pool with timestamp

Reap loop (runs every 1s):
  └── pool entry older than 5s? → ContainerAPIClient.stop() → pool = nil
```

Pool reap releases the `.LCK` file and frees the VM between tool calls,
allowing opportunistic `gnucash-browse` sessions without stopping the proxy.

**Sleep/wake handling (KU-11):**

When macOS wakes from sleep, the pooled container handle may be stale (the VM
was suspended or killed). The proxy validates liveness before forwarding:

```swift
func forwardToContainer(_ request: JSONRPCRequest) async throws -> JSONRPCResponse {
    if let entry = pool {
        guard await entry.container.isAlive() else {
            pool = nil           // invalidate stale handle
            return try await startFreshContainer(request)
        }
        entry.resetTTL()
        return try await entry.container.send(request)
    }
    return try await startFreshContainer(request)
}
```

**Proxy process lifecycle:**

The proxy is a persistent daemon. It does NOT exit on container TTL expiration.
It waits for OS signals only:

```
SIGTERM  → gnucash-mcp-stop sends this via launchctl / kill
SIGINT   → Ctrl-C during development
```

Claude Desktop does not send a shutdown message when conversations end, when the
user opens a new chat, or when Claude Desktop quits. All of these look like
silence to the proxy. The proxy ignores silence and keeps listening.

**Package structure (mirrors buck2-macos-local-reapi):**

```swift
// Package.swift
dependencies: [
    .package(url: "https://github.com/apple/container.git", from: "0.10.0"),
    .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.5.0"),
    .package(url: "https://github.com/apple/swift-nio.git", from: "2.0.0"),
    // NIO used for HTTP server; no gRPC needed (plain HTTP, not gRPC)
],
targets: [
    .executableTarget(
        name: "gnucash-mcp",
        dependencies: [
            .product(name: "ContainerAPIClient", package: "container"),
            .product(name: "ContainerResource",  package: "container"),
            .product(name: "ArgumentParser",     package: "swift-argument-parser"),
            .product(name: "NIOCore",            package: "swift-nio"),
            .product(name: "NIOHTTP1",           package: "swift-nio"),
        ]
    ),
]
```

**Subcommand CLI (swift-argument-parser):**

```
gnucash-mcp start     — attach sparsebundle, start HTTP server, write PID file
gnucash-mcp stop      — send SIGTERM to running proxy, wait for clean exit
gnucash-mcp status    — check proxy running + pool state + last tool call
gnucash-mcp install   — write claude_desktop_config.json entry + launchd plist
gnucash-mcp snapshot  — trigger manual APFS snapshot without starting a session
```

**Phased development plan for the Swift proxy:**

*Phase 1 proxy (ships with Phase 5 of the main plan):*
- HTTP server on `localhost:8980`
- Static tool catalog (all 21 tools compiled in)
- Static resources (`gnucash://book-setup-guide`, `gnucash://vendor-guide`,
  `gnucash://expected-chart`)
- Per-request container dispatch, stdin/stdout protocol
- Pool size 1, TTL 5s
- Sparsebundle mount/unmount
- SIGTERM/SIGINT → graceful shutdown
- `start` / `stop` / `status` subcommands
- Pre-session snapshot

*Phase 2 proxy (optional, after Phase 7 of the main plan):*
- Session-aware pool: issue `Mcp-Session-Id`, map sessions to container handles
- Container kept warm for the duration of a Claude Desktop conversation
- Pool drains on session termination (clean) or TTL (dirty disconnect)
- `install` subcommand writes launchd plist for login-item behavior

*Phase 3 proxy (deferred until Claude Desktop supports `tools/listChanged`):*
- Builder-pattern progressive disclosure:
  - On first connection: advertise only setup tools (`book_*`)
  - After `book_verify_structure` returns `ok: true`: emit `tools/listChanged`,
    update catalog to full operational set
  - Saves ~3,200 tokens per setup session by deferring Tier 1 schemas
- Dynamic resource `gnucash://vendors` promoted to first-class resource template
- `tools/listChanged` declared in `initialize` capabilities from day one;
  notification silently ignored by Claude Desktop until it adds support

**Review trigger:** If the Python one-shot dispatcher proves too slow for
multi-step CoWork tasks (>10 sequential tool calls with cold-start overhead),
promote the pool TTL or implement Phase 2 proxy session-aware pool earlier.

---

### MC-10: Tool profile selection via proxy CLI

**Decision:** The `gnucash-mcp start` subcommand accepts an optional `--profile`
flag that restricts which tools are advertised in `tools/list`. The full tool
catalog is compiled into the Swift binary regardless; the profile merely filters
what is returned to Claude Desktop.

**Rationale:** Different sessions need different tool sets. Advertising all 25+
tools during a quick balance check wastes ~4,500 tokens of context that Claude
will never use. During initial book setup, advertising all Tier 1 operational
tools is noise. A profile flag lets you match the advertised catalog to the
task at hand — reducing startup token cost and reducing the chance that Claude
picks the wrong tool from a crowded list.

This is the context-saving feature observed in ninetails-io's design where
tool lists can be configured externally, but implemented cleanly as a
proxy CLI argument rather than a separate config file — keeping the catalog
source of truth in Swift while making it runtime-selectable.

**Profiles:**

| Profile | Tools advertised | Tokens (approx) | When to use |
|---|---|---|---|
| `full` (default) | All 36 tools | ~8,300 | General use, agentic CoWork tasks |
| `operational` | Tier 1 only (16 tools) | ~4,300 | Daily ledger work; no setup needed |
| `readonly` | Read-only tools only (6 tools) | ~1,500 | Querying balances and reports |
| `setup` | `book_*` + `vendor_*` + `budget_*` + `eco_*` | ~2,800 | Pre-construction: enter GC budget, set up accounts |
| `construction` | Tier 1 + `eco_*` | ~5,500 | Active construction; track COs daily |
| `reconcile` | Reconciliation + reporting tools | ~2,000 | Month-end bank reconciliation |

**Implementation:** The profile is stored in the Swift proxy's runtime state
after `start`. Tool call dispatch is unaffected — all tools remain callable
regardless of profile; the restriction is advertising only. A tool call for an
un-advertised tool is still forwarded to the container and handled normally,
since Claude might have the tool name from a previous session's context.

```swift
// gnucash-mcp start --profile construction
struct StartCommand: ParsableCommand {
    @Option(name: .long, help: "Tool profile to advertise")
    var profile: ToolProfile = .full

    func run() throws {
        let proxy = GnuCashMCPProxy(profile: profile)
        try proxy.start()
    }
}

enum ToolProfile: String, ExpressibleByArgument {
    case full, operational, readonly, setup, construction, reconcile
}

// In MCPHandler.swift
func handleToolsList() -> [MCPTool] {
    let all = ToolCatalog.tools
    switch proxy.profile {
    case .full:         return all
    case .operational:  return all.filter { ToolCatalog.tier1.contains($0.name) }
    case .readonly:     return all.filter { ToolCatalog.readOnly.contains($0.name) }
    case .setup:        return all.filter { ToolCatalog.setup.contains($0.name) }
    case .construction: return all.filter { ToolCatalog.construction.contains($0.name) }
    case .reconcile:    return all.filter { ToolCatalog.reconcile.contains($0.name) }
    }
}
```

**`gnucash-mcp status`** reports the active profile alongside pool state:
```
$ gnucash-mcp status
proxy:   running (pid 12345)
profile: construction (21 tools advertised of 36 total)
pool:    warm (last call 2s ago)
volume:  /Volumes/GnuCash-Project (mounted rw)
```

**Token accounting by profile (steady-state):**

| Profile | Startup tokens | Savings vs full |
|---|---|---|
| `full` | ~8,300 | — |
| `operational` | ~4,300 | ~4,000 |
| `readonly` | ~1,800 | ~6,500 |
| `setup` | ~3,100 | ~5,200 |
| `construction` | ~5,800 | ~2,500 |
| `reconcile` | ~2,200 | ~6,100 |

**`launchd` plist uses `full` profile by default.** Override by editing the
plist args or running `gnucash-mcp stop && gnucash-mcp start --profile operational`
for focused sessions.

**Review trigger:** If the profile list grows unwieldy, consider a `--tools`
flag accepting a comma-separated list of tool names for ad-hoc filtering.
This is a purely additive Swift proxy change — Python container unchanged.

---

