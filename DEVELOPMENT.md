# DEVELOPMENT.md
# GnuCash MCP Server — Construction Project Ledger

## Overview

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

## Prior Art: ninetails-io/gnucash-mcp

A general-purpose GnuCash MCP server exists at
[github.com/ninetails-io/gnucash-mcp](https://github.com/ninetails-io/gnucash-mcp).
This section documents the comparison so architectural choices here are deliberate,
not accidental divergence.

### Fundamental differences

| Dimension | ninetails-io/gnucash-mcp | This project |
|---|---|---|
| GnuCash interface | piecash (third-party, pip-installable) | Official Python bindings (`python3-gnucash` from PPA) |
| Backend format | **SQLite only** — requires format conversion | **XML** — native macOS GnuCash format |
| Transport | stdio (Claude Desktop spawns process) | Streamable HTTP (Swift proxy daemon) |
| Platform | macOS + Windows | macOS 26 only |
| Scope | General personal finance | Construction project ledger |
| Write safety | Audit log (append-only record) | WAL + crash replay + APFS snapshots |
| GUI co-existence | No enforcement; concurrent access risks SQLite corruption | sparsebundle read-only mount enforced at kernel level |
| Token management | All tools always advertised | 3-tier with resource lazy-loading; MC-10 profile selection |

**On piecash vs official bindings:** piecash reverse-engineers GnuCash's SQLite
schema and bypasses GnuCash's C engine entirely. For reads this is harmless. For
writes it may not enforce GnuCash's internal invariants (commodity matching, cached
balance updates). The official bindings call into GnuCash's C engine and get all
invariant checks. For a construction ledger with AP aging and bank reconciliation,
correctness guarantees matter more than installation convenience. The GnuCash PPA
(`ppa:gnucash/ppa`) publishes `python3-gnucash` for Ubuntu Noble arm64, so the
official bindings are now just an `apt-get install` away — the installation
convenience gap that favoured piecash no longer exists.

**On XML vs SQLite:** XML auto-generates `.YYYYMMDDHHMMSS.gnucash` backups on every
save, is human-readable, can be diffed, and is the format macOS GnuCash 5.15 uses
natively. Converting to SQLite solely to satisfy piecash would lose these properties.

### What ninetails-io has that this project plans to add

- **Full transaction CRUD**: `update_transaction`, `delete_transaction`,
  `void_transaction`, `unvoid_transaction` — added to Phase 3 below
- **Audit log as MCP tool**: `get_audit_log` exposing change history to Claude —
  added to Phase 7 below
- **Account CRUD**: `update_account`, `move_account`, `delete_account` — added
  to Phase 2 below (via `book_*` tools)

### What ninetails-io has that this project deliberately excludes

- **GnuCash native budgets**: ninetails-io exposes GnuCash's budget feature;
  this project now uses it too via the `budget_*` tools in Phase 4 — the original
  hardcoded ROM constants approach has been replaced with live GnuCash budgets
  that the GC can update as pricing evolves through pre-construction
- **Scheduled transactions**: not applicable to a construction project with
  irregular billing cadence
- **Investment lots**: out of scope
- **Multi-currency**: out of scope

### What this project has that ninetails-io doesn't

- **Write-ahead log with crash replay**: uncommitted entries replayed on startup
- **APFS snapshots**: point-in-time recovery before each write session
- **Kernel-enforced read-only GUI**: sparsebundle `-readonly` mount
- **Project-specific tools**: `get_budget_vs_actual`, `get_ap_aging`,
  `get_tranche_summary`, `project_runway_days`
- **Vendor management as atomic unit**: `vendor_add`/`vendor_rename`/`vendor_update`/
  `vendor_delete` manage the AP+expense account pair together, with guards on
  deletion and explicit non-restatement semantics on category changes
- **Swift proxy architecture**: static tool catalog (no container for `tools/list`),
  per-request container pool, launchd integration, CoWork support via SDK bridge
- **Tool profile selection** (MC-10): `--profile` flag prunes advertised tool catalog
  to reduce context overhead for focused sessions

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
| KU-10 | Does `__unlock_ledger__` tool reliably cause Claude to treat it as a mandatory initialization step, or does it get skipped? | Context about tool groups and conventions not loaded; Claude makes incorrect tool choices | Phase 1, integration test |
| KU-11 | After Mac sleep/wake, does the pooled container handle held by the Swift proxy become stale (VM suspended/killed)? How does `ContainerAPIClient` signal this? | Proxy forwards request to a dead container; tool call hangs or returns garbage | Phase 5, Swift proxy integration |
| KU-12 | Ubuntu 26.04 LTS (releasing end of April 2026) — does `ppa:gnucash/ppa` publish arm64 packages for 26.04 in time to use it as the container base? What version of GnuCash ships in universe if the PPA is not yet available? | Must stay on 24.04 or ship a stale GnuCash version; Spike C re-validation required if base changes | Phase 0, Spike G |

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
Expense accounts under `Expenses:Construction` are populated when the GC
delivers their pre-construction budget — not predetermined. Professional
fees (Architecture, Structural, MEP) retain their own fixed expense accounts
because those contracts are already signed with known scopes.

**Rationale:** The original design pre-mapped Construction expense accounts to
the prior GC's ROM Labor/Subcontracts/Materials structure. That bid was not accepted.
The new GC will deliver their own line-item breakdown in pre-construction, and that
structure — whatever it is — becomes the expense account hierarchy and the GnuCash
budget amounts simultaneously. Using GnuCash's native budget feature means the
budget is live data in the book, not hardcoded Python constants.

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
  Architecture — Acme Architecture
  Structural Engineering — Peak Structural
  MEP Consulting — Meridian MEP
  HVAC Engineering — Summit HVAC
  Permits and Fees
  Construction         ← placeholder parent; children created from GC budget
  Change Orders        ← ECO tracking (see Phase 4)
```

**`Expenses:Construction` children** are created during pre-construction when
the GC delivers their budget. Each GC line item becomes a sub-account:
```
  Construction:Demo
  Construction:Framing
  Construction:Electrical
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
eco_create, eco_list, eco_get, eco_approve, eco_void,
__unlock_ledger__
```

**MCP Resources** (zero startup cost, fetched on demand):
```
gnucash://resources               — index of all resources and when to use them
gnucash://book-setup-guide        — account_type values, naming conventions
gnucash://vendor-guide            — expense_category options for vendor_add
gnucash://expected-chart          — full expected account tree (used by book_verify_structure)
gnucash://budget-guide            — GnuCash budget workflow; budget_create → budget_set_amount
gnucash://eco-guide               — ECO numbering, direction conventions, approval workflow
gnucash://vendors                 — live vendor list with AP balances (requires container)
```

**`__unlock_ledger__` tool** — called at session start to return operational context
(current balances, open AP count, and a reference to `gnucash://resources`).
Semantically named to encourage Claude to treat it as a mandatory initialization
step rather than optional discovery. Returns a compact JSON payload; does not itself
consume resources or open a GnuCash session.

**`server_instructions`** — returned in the Swift proxy's `initialize` response,
describing tool groups and the resource index. Acknowledged that Claude Desktop
sometimes ignores this field; `__unlock_ledger__` is the reliable backup mechanism.

**Token accounting (steady-state, `full` profile):**
- Tier 1 + Tier 2 tool schemas at startup: ~8,000 tokens (~36 tools)
- `__unlock_ledger__` call + response: ~300 tokens
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
- Static resource content (`gnucash://book-setup-guide`, `gnucash://vendor-guide`,
  `gnucash://expected-chart`)
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
  - On first connection: advertise only setup tools (`book_*`, `__unlock_ledger__`)
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
| `setup` | `book_*` + `vendor_*` + `budget_*` + `eco_*` + `__unlock_ledger__` | ~2,800 | Pre-construction: enter GC budget, set up accounts |
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

## Phase 0 — Foundations and Spike Resolution

**Goal:** Validate all known unknowns. Nothing in Phase 0 is production code.
All spikes are throwaway scripts. Phase 0 gates all subsequent phases.

**Duration estimate:** 1–2 days of hands-on work.

### Spike A — Python bindings via PPA in Ubuntu 24 Apple Container

**Question:** Does `python3-gnucash` from `ppa:gnucash/ppa` install and work
correctly inside an Ubuntu Noble Apple Container on Apple Silicon?

```dockerfile
# Dockerfile.spike-a
FROM ubuntu:24.04
RUN apt-get update && \
    apt-get install -y software-properties-common gnupg && \
    add-apt-repository ppa:gnucash/ppa && \
    apt-get update && \
    apt-get install -y python3-gnucash
```

```python
# spike-a.py — run inside container
from gnucash import Session, GnuCashBackendException, SessionOpenMode, ERR_BACKEND_LOCKED
import tempfile, os

# Test 1: module imports
import gnucash
print(f"GnuCash version: {gnucash.gnucash_core_c.gnc_version()}")

# Test 2: create a new book using modern SessionOpenMode API
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test.gnucash")
    # SESSION_NEW_STORE replaces deprecated is_new=True
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as session:
        book = session.book
        root = book.get_root_account()
        print(f"Root account: {root}")
        # context manager calls session.save() then session.end() on exit
    print("PASS: session create/save/end via context manager")

# Test 3: early-save pattern for new books
# new_book_with_opening_balances.py (official example) saves immediately after
# opening a new book, before any mutations, to avoid subtle corruption bugs.
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_early_save.gnucash")
    session = Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE)
    session.save()   # early save — must happen before any mutations
    book = session.book
    # ... mutations would go here ...
    session.save()
    session.end()
    print("PASS: early-save pattern")

# Test 4: reopen existing book
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_reopen.gnucash")
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s1:
        s1.book  # create it
    # SESSION_NORMAL_OPEN replaces deprecated is_new=False
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN) as s2:
        book2 = s2.book
        print(f"Reopened root: {book2.get_root_account()}")
    print("PASS: reopen")

# Test 5: lock detection
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_lock.gnucash")
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s1:
        try:
            s2 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
            print("FAIL: expected ERR_BACKEND_LOCKED")
        except GnuCashBackendException as e:
            assert ERR_BACKEND_LOCKED in e.errors
            print("PASS: lock detection via GnuCashBackendException")
```

**Pass criteria:**
- `add-apt-repository ppa:gnucash/ppa` succeeds in container (network + GPG key)
- `apt-get install python3-gnucash` installs without errors
- `import gnucash` succeeds without error
- `Session(path, SessionOpenMode.SESSION_NEW_STORE)` creates a valid new book
- `book.get_root_account()` returns an Account object
- Early-save pattern (save before mutations) completes without error
- Session save/end/reopen cycle completes without error
- Lock detection raises `GnuCashBackendException` with `ERR_BACKEND_LOCKED`
- Record installed GnuCash version in `SPIKE_RESULTS.md` for Spike C planning

**Fail path:** If PPA installation fails in container:
1. Install from Noble universe directly (no PPA): `apt-get install python3-gnucash`
   gives GnuCash 5.5 — functional but further behind macOS 5.15; Spike C becomes
   more important
2. Fall back to build from source at 5.14 or 5.15 (~30 min build, original plan)

---

### Spike B — VirtioFS sparsebundle volume sharing

**Question:** Does the Linux container see the sparsebundle mount point with correct
read-write semantics via Apple Container's VirtioFS volume mount?

```zsh
# On macOS host:
hdiutil create -size 50m -type SPARSEBUNDLE -fs APFS \
  -volname "GnuCash-Spike" ~/spike-test.sparsebundle
hdiutil attach -readwrite -mountpoint /Volumes/GnuCash-Spike \
  -nobrowse ~/spike-test.sparsebundle
echo "hello from host" > /Volumes/GnuCash-Spike/test.txt

# Run container with volume mount:
container run --rm \
  --volume /Volumes/GnuCash-Spike:/data \
  ubuntu:24.04 \
  bash -c "cat /data/test.txt && echo 'written from container' >> /data/test.txt"

# Verify on host:
cat /Volumes/GnuCash-Spike/test.txt
# Expected: both lines present
```

**Pass criteria:**
- Host-written file readable in container
- Container-written content visible on host after container exits
- File ownership and permissions are sane (no UID mismatch blocking writes)
- No VirtioFS errors in container dmesg

**Fail path:** In order:
1. Copy-in / copy-out: container receives a file copy on start, writes back on exit
2. SSHFS from container back to macOS host via `Remote Login`
3. Reconsider SQLite backend with explicit lock management over a network path

---

### Spike C — Cross-version schema compatibility (5.14 container via PPA, 5.15 macOS)

**Question:** Can GnuCash 5.14 (`python3-gnucash=1:5.14-0build1` from PPA) in the
container open an XML file last saved by GnuCash 5.15 on macOS without attempting
migration or refusing to open? This is a one-minor-version gap — the same gap the
original build-from-source plan assumed, now via apt instead of cmake.

```python
# spike-c.py — run inside the container against a file saved by macOS 5.15
from gnucash import Session, SessionOpenMode

# The file must be created by opening a new book in macOS GnuCash 5.15
# and doing File > Save, then copying to /data/ via VirtioFS (Spike B)
# SESSION_NORMAL_OPEN replaces deprecated is_new=False
with Session("xml:///data/spike-cross-version.gnucash",
             SessionOpenMode.SESSION_NORMAL_OPEN) as session:
    book = session.book
    root = book.get_root_account()
    print("Accounts:", [a.GetName() for a in root.get_children()])
    # no session.save() — read-only probe; end() via context manager
print("PASS: opened cleanly, no migration")
```

**Pass criteria:**
- No migration prompt, warning, or error from 5.14 opening a 5.15-saved file
- Account tree readable
- No writes made to the file during open + read + end

**Fail path:**
1. The GnuCash XML schema has been stable across 5.x minor releases; a migration
   prompt is unexpected but possible if 5.15 introduced schema changes. Check the
   GnuCash 5.15 release notes for any XML format changes.
2. Pin macOS GnuCash to 5.14 (download specific .dmg from gnucash.org) — eliminates
   the gap entirely
3. Wait for PPA to publish 5.15 for Noble, update container pin

---

### Spike D — Read-only mount enforcement

**Question:** Does macOS GnuCash 5.15, when opened against a `-readonly` hdiutil
mount, truly fail to write, or does it find a writable path around the mount flag?

```zsh
# Attach read-only
hdiutil attach -readonly -mountpoint /Volumes/GnuCash-RO \
  ~/spike-test.sparsebundle

BEFORE=$(md5 -q /Volumes/GnuCash-RO/test.gnucash 2>/dev/null || echo "absent")

# Open GnuCash, attempt Cmd-S, quit
/Applications/Gnucash.app/Contents/MacOS/Gnucash /Volumes/GnuCash-RO/test.gnucash
# Manual step: try File > Save, then quit

AFTER=$(md5 -q /Volumes/GnuCash-RO/test.gnucash 2>/dev/null || echo "absent")
ls -la /Volumes/GnuCash-RO/

[[ "$BEFORE" == "$AFTER" ]] && echo "PASS: unchanged" || echo "FAIL: modified"
```

**Pass criteria:**
- `Cmd-S` in GnuCash either fails silently or shows an error dialog
- No `.LCK`, `.LNK`, or `.YYYYMMDDHHMMSS.gnucash` backup files created
- File hash unchanged after GnuCash quits
- No `.LCK` left after GnuCash quits (read-only opens should not lock)

**Fail path:** If GnuCash writes through a read-only mount:
1. macOS sandbox profile (`sandbox-exec`) to restrict GnuCash file writes
2. Dedicated low-privilege macOS user account for GUI-only access

---

### Spike E — APFS snapshots on sparsebundle volume

**Question:** Does `tmutil localsnapshot` work against a mounted sparsebundle
volume as a named path argument, or only against the boot volume (`/`)?

```zsh
MOUNT=/Volumes/GnuCash-Spike
hdiutil attach -readwrite -mountpoint "$MOUNT" -nobrowse ~/spike-test.sparsebundle

echo "before snapshot" > "$MOUNT/canary.txt"
tmutil localsnapshot "$MOUNT"

DEV=$(diskutil info "$MOUNT" | awk '/Device Node/ { print $NF }')
diskutil apfs listSnapshots "$DEV"

# Modify after snapshot
echo "after snapshot" > "$MOUNT/canary.txt"

# Mount snapshot and verify canary contains pre-modification content
SNAP=$(diskutil apfs listSnapshots "$DEV" | awk '/Name:/ { print $NF }' | tail -1)
TMP=$(mktemp -d)
mount_apfs -s "$SNAP" -o rdonly "$DEV" "$TMP"
cat "$TMP/canary.txt"   # should show "before snapshot"
umount "$TMP"
```

**Pass criteria:**
- `tmutil localsnapshot "$MOUNT"` exits 0
- Snapshot visible in `diskutil apfs listSnapshots` output
- Snapshot mounts successfully at a temp path
- Canary file in snapshot contains pre-modification content

**Fail path:** If `tmutil` only works on the boot volume:
1. Use `cp -c` (APFS clone-copy) for cheap pre-session backups:
   `cp -c "$BOOK" "${BOOK}.pre-$(date +%Y%m%d-%H%M%S).gnucash"`
   This is near-instant on APFS (copy-on-write) and gives equivalent point-in-time
   recovery for a single file
2. Accept GnuCash's own `.YYYYMMDDHHMMSS.gnucash` auto-backups as sufficient

---

### Spike F — Swift proxy HTTP transport and CoWork bridge (resolves KU-8, KU-9)

**Question:** Does a Swift NIO HTTP server running on the macOS host, forwarding
requests to an Apple Container via `ContainerAPIClient` stdin/stdout, appear as
a working MCP server in Claude Desktop and CoWork?

This spike validates two things independently:

**F1 — Transport reachability:** Is `localhost:8980` reachable by Claude Desktop?
(Since the Swift proxy runs natively on macOS, not inside a container, there is
no port-publishing concern — but we confirm Claude Desktop's `streamable-http`
connector type accepts it.)

**F2 — Container dispatch:** Can `ContainerAPIClient` start a container, write
a JSON-RPC request to its stdin, read the response from stdout, and stop the
container — reliably, in under 1 second?

```swift
// spike-f/Sources/spike-f/main.swift — minimal Swift MCP proxy
// Uses NIO for HTTP, ContainerAPIClient for dispatch
// Tool: ping() → {"status": "ok", "transport": "swift-proxy"}

@main struct SpikeF: AsyncParsableCommand {
    func run() async throws {
        let server = MCPHTTPServer(port: 8980) { request in
            if request.method == "tools/call",
               let name = request.params?.name, name == "ping" {
                // Dispatch to container
                let container = try await ContainerAPIClient.shared
                    .run(image: "spike-f:latest",
                         command: ["python3", "-c",
                           "import json,sys; print(json.dumps({'result': {'status':'ok'}}))"],
                         volumes: [])
                return try await container.readStdout()
            }
            return MCPResponse.staticToolsList([pingTool])
        }
        try await server.run()
    }
}
```

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "spike-f": {
      "type": "streamable-http",
      "url": "http://localhost:8980/mcp"
    }
  }
}
```

**Pass criteria:**
- Swift NIO HTTP server starts and responds to `curl POST localhost:8980/mcp`
  with valid MCP `initialize` response
- Claude Desktop shows `spike-f` as connected
- `ping()` tool callable from Claude Desktop chat window
- Container starts, executes command, stdout captured, container stopped —
  all within 1 second total
- CoWork session can call `ping()` (verifies SDK bridge — KU-9)

**Fail path (KU-8 — transport):** If Claude Desktop rejects `localhost:8980`:
- Try `127.0.0.1:8980` explicitly
- Check if `streamable-http` type requires HTTPS (unlikely for localhost)
- Fall back to registering proxy as a stdio server that immediately returns
  the correct `initialize` response, then bridges internally

**Fail path (KU-9 — CoWork):** If Claude Desktop connects but CoWork can't use tools:
- Verify CoWork SDK bridge handles `streamable-http` (not only stdio)
- Document workaround: use Claude.ai web interface for book management tasks

**Fail path (container dispatch):** If `ContainerAPIClient` stdin/stdout
round-trip exceeds 1 second or is unreliable:
- Measure and document actual latency
- Consider pre-warming container (start on proxy launch, not per-request)
  as an alternative to TTL pool

---

### Spike G — Ubuntu 26.04 LTS container base evaluation (resolves KU-12)

**Question:** Is Ubuntu 26.04 LTS (releasing end of April 2026) a viable drop-in
replacement for the Ubuntu 24.04 container base?

Ubuntu 26.04 is the next LTS. The container base is currently pinned to 24.04 because
that is what `ppa:gnucash/ppa` supports for arm64 at design time. This spike evaluates
whether 26.04 is ready to adopt before or during Phase 1.

**G1 — Universe package version:** What version of GnuCash ships in Ubuntu 26.04
universe (without the PPA)?

```bash
# Run against a 26.04 container once released
apt-cache show gnucash | grep Version
```

**G2 — PPA availability:** Has `ppa:gnucash/ppa` published arm64 packages for
Ubuntu 26.04 (codename "oracular" or next LTS)?

```bash
# Check Launchpad PPA build status
curl -s "https://launchpad.net/~gnucash/+archive/ubuntu/ppa/+packages" \
  | grep -i "26\.\|oracular\|next-lts-codename"
```

> **Note:** As of April 2026, no PPAs for 26.04 exist yet. Do not block Phase 1 on
> this spike — run it in parallel once 26.04 is released.

**G3 — Migration smoke test:** If a 26.04 image with a working GnuCash package is
available, re-run Spike A and Spike C tests against it:
- `import gnucash` succeeds inside a 26.04 Apple Container
- Cross-version schema compatibility (container GnuCash version vs macOS 5.15)

**Decision matrix:**

| Scenario | Action |
|---|---|
| PPA publishes for 26.04, version ≥ 5.14 | Update `Dockerfile` to `FROM ubuntu:26.04`, re-run Spike A/C |
| Universe ships GnuCash ≥ 5.14 (PPA not needed) | Drop PPA dependency, update `Dockerfile` |
| Neither available at Phase 1 start | Stay on 24.04; revisit after 26.04 PPA publishes |
| GnuCash version < 5.14 on 26.04 | Stay on 24.04 indefinitely; document in `SPIKE_RESULTS.md` |

**Note:** If the base image changes to 26.04, Spike C must be re-validated against
the new container GnuCash version and the macOS 5.15 book file.

---

### Phase 0 exit criteria

All spikes must produce a written result (PASS or documented FAIL + chosen fallback)
before Phase 1 begins. Record results in `SPIKE_RESULTS.md`.

| Spike | Status | Fallback chosen (if FAIL) |
|---|---|---|
| A — Python bindings | ☐ | |
| B — VirtioFS | ☐ | |
| C — Schema compatibility | ☐ | |
| D — Read-only enforcement | ☐ | |
| E — APFS snapshots | ☐ | |
| F — HTTP transport + CoWork bridge | ☐ | |
| G — Ubuntu 26.04 evaluation | ☐ (non-blocking; run after 26.04 release) | |

---

## Phase 1 — Core Ledger and MCP Skeleton

**Goal:** A working MCP server that can post a double-entry journal entry and read
account balances. End-to-end: Claude calls a tool, a transaction appears in GnuCash.

**Prerequisites:** Phase 0 complete, all spikes resolved.

### M1.1 — Repository and container setup

**Deliverables:**
- `Docker/Dockerfile` — Ubuntu 24.04 + `python3-gnucash` from PPA:

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:gnucash/ppa && \
    apt-get update && \
    apt-get install -y python3-gnucash python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Python project installed into container image
COPY pyproject.toml /src/pyproject.toml
COPY src/ /src/src/
RUN pip3 install --break-system-packages -e /src

ENTRYPOINT ["python3", "-m", "gnucash_mcp"]
```

- `Makefile` with targets: `build`, `shell`, `test`
- `pyproject.toml` for uv-managed Python project

**Tests:**
```
T1.1.1  Container image builds without error (PPA add-apt-repository succeeds)
T1.1.2  `make shell` drops into container with /data mounted
T1.1.3  python3 -c "import gnucash" succeeds inside container
T1.1.4  python3 -c "import gnucash; print(gnucash.gnucash_core_c.gnc_version())"
        prints GnuCash version matching Spike A result
T1.1.5  /data is writable from inside the container (VirtioFS confirmed)
```

---

### M1.2 — Book initialization

**Deliverables:**
- `scripts/init_book.py` — creates a new GnuCash XML book with the full chart of
  accounts defined in MC-6
- Idempotent: running twice does not create duplicate accounts

**Tests:**
```
T1.2.1  init_book.py creates project.gnucash in /data
T1.2.2  All accounts in MC-6 chart present in the created book
T1.2.3  Running init_book.py a second time against an existing book is a no-op
T1.2.4  GnuCash XML is parseable without error by lxml
T1.2.5  macOS GnuCash 5.15 can open the file created by the container version
        (manual verification — record container GnuCash version in TEST_RESULTS.md)
```

---

### M1.3 — Write-ahead log

**Deliverables:**
- `src/wal.py` — WAL writer/reader:
  - `append(entry: dict) -> str` — writes entry, returns generated `id`
  - `mark_committed(entry_id: str)` — sets `committed_at`
  - `pending() -> list[dict]` — entries without `committed_at`
  - `replay() -> list[dict]` — returns `pending()` in `logged_at` order

WAL entry schema:
```json
{
  "id": "uuid4",
  "logged_at": "ISO-8601",
  "type": "fund_project | receive_invoice | pay_invoice | post_transaction | interest",
  "payload": {},
  "committed_at": null
}
```

**Tests:**
```
T1.3.1  append() writes entry to JSONL file, entry appears in pending()
T1.3.2  mark_committed() sets committed_at; entry no longer in pending()
T1.3.3  replay() returns entries in logged_at order
T1.3.4  WAL file survives simulated crash (kill -9 on test process) with pending entry
T1.3.5  Two sequential appends produce two valid JSONL lines (no corruption)
T1.3.6  WAL with mixed committed and pending entries returns only pending from pending()
```

---

### M1.4 — GnuCash session manager

**Deliverables:**
- `src/session.py`:
  - `open_session(path, is_new=False)` — opens GnuCash session with correct
    `SessionOpenMode`; for new books calls `session.save()` immediately after
    opening, before any mutations (see design notes below)
  - `close_session(session)` — `session.save()`, then `session.end()`
  - Context manager (`with book_session(path) as session:`) — calls
    `close_session()` in `__exit__` even on exception
  - `get_account(book, full_name) -> Account` — raises `AccountNotFoundError`
    if missing
  - `gnc_decimal(amount_str) -> GncNumeric` — safe Decimal-to-GncNumeric
    conversion

**Session API notes (from `simple_session.py` and `gnucash_core.py`):**

The deprecated `is_new` / `ignore_lock` boolean arguments are replaced by
`SessionOpenMode` in GnuCash 5.x:

```python
from gnucash import Session, GnuCashBackendException, SessionOpenMode
from gnucash import ERR_BACKEND_LOCKED, ERR_FILEIO_FILE_NOT_FOUND

# Create new book
session = Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE)

# Open existing book
session = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)

# Lock detection — raised when book already open
try:
    session2 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
except GnuCashBackendException as e:
    if ERR_BACKEND_LOCKED in e.errors:
        # book is locked by another process
```

`Session` also supports use as a context manager — `__exit__` calls `save()`
then `end()` automatically. The MCP session manager wraps this to ensure the
WAL `committed_at` timestamp is set before `end()` is called.

**Early-save pattern for new books:**

`new_book_with_opening_balances.py` (official GnuCash example script) contains
this comment at the point where it calls `save()` on a freshly-opened new book,
before making any changes:

> *"we discovered that if we didn't have this save early on, there would be trouble later"*

The session manager must replicate this for all new-book creation:

```python
# src/session.py
from gnucash import Session, GnuCashBackendException, SessionOpenMode
from gnucash import ERR_BACKEND_LOCKED, ERR_FILEIO_FILE_NOT_FOUND
from contextlib import contextmanager
from pathlib import Path

def open_session(path: Path, is_new: bool = False) -> Session:
    """Open a GnuCash XML session. Clears stale .LCK if present."""
    lck = Path(str(path) + ".LCK")
    if lck.exists() and not is_new:
        lck.unlink()   # stale lock from prior crash — safe to clear
    mode = (SessionOpenMode.SESSION_NEW_STORE if is_new
            else SessionOpenMode.SESSION_NORMAL_OPEN)
    session = Session(f"xml://{path}", mode)
    if is_new:
        # Early save required before any mutations on new XML books.
        # Skipping this causes subtle corruption (per GnuCash example scripts).
        session.save()
    return session

def close_session(session: Session) -> None:
    """Save and end a session, releasing the .LCK file."""
    session.save()
    session.end()

@contextmanager
def book_session(path: Path, is_new: bool = False):
    """Context manager: open → yield session → save+end even on exception."""
    session = open_session(path, is_new=is_new)
    try:
        yield session
    finally:
        try:
            close_session(session)
        except Exception:
            # end() can fail if session already ended; suppress
            try:
                session.end()
            except Exception:
                pass
```

**KU-6 status:** Resolved by `Session` class docstring and example scripts.
`save()` durably flushes to disk (always required for file backend). `end()`
only releases the `.LCK`. Data is safe after `save()` even if the process
crashes before `end()`. The WAL `committed_at` timestamp is set after
`save()` completes, before `end()` is called.

**Tests:**
```
T1.4.1  open_session(path, is_new=True) creates .LCK file alongside book
T1.4.2  open_session(path, is_new=True) calls save() before returning
         (early-save: verify .gnucash file exists on disk before any mutations)
T1.4.3  close_session() calls save() then end(); .LCK file absent after
T1.4.4  Stale .LCK file from a prior crash is cleared on open without error
T1.4.5  book_session() context manager calls close_session() even if exception
         raised inside block; .LCK file absent after exception
T1.4.6  Second open on locked book raises GnuCashBackendException with
         ERR_BACKEND_LOCKED (confirms MC-2 lock detection)
T1.4.7  get_account(book, "Expenses:Architecture — Acme Architecture") returns correct account
T1.4.8  get_account(book, "Expenses:Nonexistent") raises AccountNotFoundError
T1.4.9  gnc_decimal("15000.00") round-trips without precision loss
T1.4.10 Kill process after save() but before end(): on restart, book opens
         cleanly (stale .LCK cleared), all data from previous save() present
         (KU-6 crash-durability confirmation — run manually, record in TEST_RESULTS.md)
```

---

### M1.5 — Python dispatcher and tool structure

**Context:** The MCP protocol layer (HTTP server, `tools/list`, static resources)
lives in the Swift proxy (MC-9, M5.2). The Python container receives one
JSON-RPC `tools/call` request on stdin, dispatches to the correct tool function,
writes the response to stdout, and exits. No uvicorn, no FastMCP, no HTTP server.

**Deliverables:**
- `src/__main__.py` — one-shot stdin→stdout dispatcher:

```python
# src/__main__.py
import json, sys
from gnucash_mcp.dispatch import dispatch

def main():
    raw = sys.stdin.buffer.read()
    request = json.loads(raw)
    response = dispatch(request)
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()

if __name__ == "__main__":
    main()
```

- `src/dispatch.py` — routes `tools/call` method+name to the correct handler:

```python
# src/dispatch.py
from gnucash_mcp.tools import read, write

HANDLERS = {
    # Tier 1 — read
    "get_account_balance":  read.get_account_balance,
    "list_accounts":        read.list_accounts,
    "list_transactions":    read.list_transactions,
    "get_transaction":      read.get_transaction,
    "get_project_summary":  read.get_project_summary,
    "get_audit_log":        read.get_audit_log,     # reads WAL, no GnuCash session
    "__unlock_ledger__":    read.unlock_ledger,
    "gnucash://vendors":    read.vendors_resource,  # dynamic resource
    # Tier 1 — write (core) added in M1.6
    # Tier 1 — write (correction) added in Phase 3
    # Tier 2 — book/vendor tools added in Phase 2
}

def dispatch(request: dict) -> dict:
    method = request.get("method")
    req_id = request.get("id")

    if method == "tools/call":
        name = request.get("params", {}).get("name")
        args = request.get("params", {}).get("arguments", {})
        handler = HANDLERS.get(name)
        if not handler:
            return error_response(req_id, -32601, f"Unknown tool: {name}")
        try:
            result = handler(**args)
            return success_response(req_id, result)
        except Exception as e:
            return error_response(req_id, -32603, str(e))

    if method == "resources/read":
        uri = request.get("params", {}).get("uri")
        handler = HANDLERS.get(uri)
        if not handler:
            return error_response(req_id, -32601, f"Unknown resource: {uri}")
        result = handler()
        return success_response(req_id, {"contents": [{"uri": uri, "text": json.dumps(result)}]})

    return error_response(req_id, -32601, f"Unsupported method in container: {method}")
```

**`__unlock_ledger__` tool** — implemented in Python, called by proxy dispatch:
```python
def unlock_ledger() -> dict:
    """CALL FIRST. Returns current book state and tool navigation guide."""
    return {
        "book": str(BOOK_PATH),
        "tool_groups": {
            "operational": [
                "receive_invoice", "pay_invoice", "fund_project",
                "post_interest", "post_transaction",
                "get_account_balance", "list_accounts",
                "list_transactions", "get_transaction",
                "get_project_summary", "get_budget_vs_actual",
                "get_ap_aging", "get_audit_log",
            ],
            "correction": [
                "update_transaction", "void_transaction", "delete_transaction",
            ],
            "book_setup": [
                "book_add_account", "book_get_account_tree",
                "book_verify_structure", "book_set_opening_balance",
                "book_rename_account", "book_move_account", "book_delete_account",
            ],
            "vendors": [
                "vendor_add", "vendor_list", "vendor_get_details",
                "vendor_rename", "vendor_update", "vendor_delete",
            ],
            "budget": [
                "budget_create", "budget_list", "budget_get",
                "budget_set_amount", "budget_update", "budget_delete",
            ],
            "ecos": [
                "eco_create", "eco_list", "eco_get",
                "eco_approve", "eco_void",
            ],
        },
        "resource_index": {
            "gnucash://book-setup-guide":
                "Read before calling any book_* tool",
            "gnucash://vendor-guide":
                "Read before calling vendor_add or vendor_update",
            "gnucash://expected-chart":
                "Full account tree — used by book_verify_structure",
            "gnucash://budget-guide":
                "Read before calling budget_create or budget_set_amount",
            "gnucash://eco-guide":
                "Read before calling eco_create or eco_approve",
            "gnucash://vendors":
                "Live vendor list with current AP balances (requires container)",
        },
        "conventions": {
            "account_path_separator": ":",
            "amount": "decimal string, no currency symbol e.g. '25000.00'",
            "date": "ISO-8601 YYYY-MM-DD",
        }
    }
```

**Note on resources:** Static resources are served directly by the Swift proxy from
compiled-in Swift string constants — the Python container is never invoked for them.
Only `gnucash://vendors` requires the container (live AP balance query).

Static resources served by proxy:
- `gnucash://resources` — index of all resources
- `gnucash://book-setup-guide` — account_type values and naming conventions
- `gnucash://vendor-guide` — expense_category options and vendor workflow
- `gnucash://expected-chart` — full expected account structure
- `gnucash://budget-guide` — GnuCash budget workflow; budget_create → budget_set_amount sequence
- `gnucash://eco-guide` — ECO numbering conventions, direction semantics, approval workflow

Dynamic resources (require container):
- `gnucash://vendors` — live vendor list with AP balances

**Read-only Tier 1 tools (in `src/tools/read.py`):**
- `get_account_balance(account_path: str) -> dict`
- `list_accounts(parent_path: str | None) -> list[dict]`
- `list_transactions(account_path: str, limit: int = 20) -> list[dict]`
- `get_project_summary() -> dict`

**Tests:**
```
T1.5.1  Container starts, receives JSON-RPC tools/call via stdin, returns response
        on stdout, exits — round trip under 500ms
T1.5.2  __unlock_ledger__ returns all three tool group keys without error
T1.5.3  gnucash://vendors dispatch opens read-only GnuCash session and returns list
T1.5.4  get_account_balance returns correct balance after a known funding entry
T1.5.5  list_accounts(None) returns all top-level account names
T1.5.6  list_transactions with limit=5 returns at most 5 entries, newest first
T1.5.7  get_project_summary() all five fields present and non-null
T1.5.8  All read tools open and close a GnuCash session within the single dispatch call
        (no persistent session — MC-2)
T1.5.9  Unknown tool name returns JSON-RPC error -32601, not a Python exception
T1.5.10 Via Swift proxy: Claude Desktop shows gnucash-myproject connected (manual,
        requires M5.2 complete; record in TEST_RESULTS.md)
T1.5.11 Via Swift proxy: Claude calls __unlock_ledger__ at session start (manual;
        resolves KU-10; record in TEST_RESULTS.md)
T1.5.12 Via Swift proxy: CoWork can call get_project_summary() (manual;
        resolves KU-9; record in TEST_RESULTS.md)
```

---

### M1.6 — Core MCP tools (write)

**Deliverables:**
- Write tools in `src/tools/write.py`, registered in `src/dispatch.py`:
  - `post_transaction(date, description, splits: list[dict]) -> dict`
    - splits: `[{account_path, amount, memo}]`, must sum to zero
  - `fund_project(date, amount, memo) -> dict`
    - Debit Project Checking, credit Owner Capital
  - `receive_invoice(date, vendor, invoice_ref, amount, expense_account) -> dict`
    - Debit expense account, credit AP — vendor
  - `pay_invoice(date, vendor, invoice_ref, amount) -> dict`
    - Debit AP — vendor, credit Project Checking
  - `post_interest(month, amount) -> dict`
    - Debit Project Checking, credit Interest Income

Each write tool: appends WAL entry → opens session → posts transaction →
`session.save()` → `session.end()` → marks WAL committed.

**Tests:**
```
T1.6.1  fund_project posts balanced transaction (sum of splits = 0)
T1.6.2  fund_project WAL entry has committed_at after tool returns
T1.6.3  receive_invoice creates correct AP balance for named vendor
T1.6.4  pay_invoice clears AP balance to $0.00 when matching invoice amount
T1.6.5  post_transaction with unbalanced splits raises SplitsImbalanceError (not posted,
        WAL entry not committed)
T1.6.6  Post AAI invoice #101 ($15,000.00) and payment — account balances match
        known values from project documents
T1.6.7  Post PSE invoice PSE-000101 ($2,000.00) — AP and expense balances correct
T1.6.8  Simulate crash: WAL entry appended, session.end() not reached (kill -9).
        On next startup, pending() returns the entry. replay() re-posts it.
        Resulting balance matches expected value.
T1.6.9  Replay of an already-committed WAL entry is a no-op (idempotency guard)
T1.6.10 Post all known invoices from project documents:
        AAI #101 ($15,000.00), AAI #102 ($25,000.00),
        PSE-000101 ($2,000.00), PSE-000102 ($1,200.00),
        MMEP #2001 ($600), #2002 ($600), #2003 ($480), #2004 ($720)
        get_project_summary() totals match manual calculation
```

---

### Phase 1 exit criteria

- All T1.x automated tests passing
- All known invoices from project documents posted via Claude using MCP tools
- `get_project_summary()` returns totals matching manual ledger cross-check
- macOS GnuCash opened against the file (read-only mount), account tree and
  all transactions visible and correct (manual verification)
- No data loss after simulated crash + replay (T1.6.8 confirmed)
- KU-10 resolved: `__unlock_ledger__` behavior documented in TEST_RESULTS.md

---

## Phase 2 — Book Management and Vendor Tools

**Goal:** Claude can set up and maintain the chart of accounts and add new
vendors/subcontractors as they are hired. These tools are used infrequently
(once at setup, then as new subs are brought on) but must be reliable.
Resource-based lazy context pattern validated in practice.

**Prerequisites:** Phase 1 complete. MC-8 tool architecture confirmed working.

### M2.1 — Book setup tools

**Deliverables (`src/tools/book.py`):**

```python
@app.tool()
def book_add_account(
    name: str,
    parent_path: str,
    account_type: str,   # ASSET|LIABILITY|EQUITY|INCOME|EXPENSE
    commodity: str = "USD",
) -> dict:
    """Add account to chart of accounts. Read gnucash://book-setup-guide
    for account_type values and naming conventions first."""

@app.tool()
def book_get_account_tree(parent_path: str = "") -> list[dict]:
    """Return account tree as nested list. Read gnucash://expected-chart
    to compare against expected structure."""

@app.tool()
def book_verify_structure() -> dict:
    """Compare live chart of accounts against gnucash://expected-chart.
    Returns {missing: [...], unexpected: [...], ok: bool}."""

@app.tool()
def book_set_opening_balance(
    account_path: str,
    amount: str,
    date: str,
) -> dict:
    """Post an opening balance transaction for an account.
    Read gnucash://book-setup-guide before calling."""

@app.tool()
def book_rename_account(
    account_path: str,
    new_name: str,
) -> dict:
    """Rename an account leaf (not full path). Does not affect existing
    transactions — GnuCash tracks accounts by GUID, not name."""

@app.tool()
def book_move_account(
    account_path: str,
    new_parent_path: str,
) -> dict:
    """Move an account to a new parent in the hierarchy. Use when
    restructuring the chart of accounts. Existing transactions unaffected."""

@app.tool()
def book_delete_account(
    account_path: str,
    require_zero_balance: bool = True,
) -> dict:
    """Delete an account. Fails if account has transactions unless
    require_zero_balance=False is explicitly passed. Use with caution:
    deletion is permanent and cannot be undone via MCP."""
```

**Tests:**
```
T2.1.1  book_add_account creates account at correct path in hierarchy
T2.1.2  book_add_account with non-existent parent_path raises AccountNotFoundError
T2.1.3  book_add_account with invalid account_type raises ValueError
T2.1.4  book_add_account is idempotent: running with same args twice does not duplicate
T2.1.5  book_get_account_tree("Liabilities") returns all AP accounts
T2.1.6  book_verify_structure returns ok:true on a correctly-initialized book
T2.1.7  book_verify_structure returns missing accounts after one is removed (test fixture)
T2.1.8  book_set_opening_balance creates a balanced transaction with equity offset
T2.1.9  book_rename_account updates account name; existing transactions still resolve
T2.1.10 book_move_account moves account to new parent; full path reflects new location
T2.1.11 book_delete_account fails on account with transactions when require_zero_balance=True
T2.1.12 book_delete_account succeeds on empty account; account absent from tree after
T2.1.13 Resource gnucash://book-setup-guide is non-empty and contains "account_type"
T2.1.14 Claude fetches gnucash://book-setup-guide before calling book_add_account
         (manual — observe in CoWork/Desktop tool log; record in TEST_RESULTS.md)
```

---

### M2.2 — Vendor management tools

**Deliverables (`src/tools/vendor.py`):**

```python
@app.tool()
def vendor_add(
    name: str,
    expense_category: str = "Subcontracts",
) -> dict:
    """Add a new vendor/subcontractor. Creates AP liability account and
    expense account. Read gnucash://vendor-guide for expense_category
    options before calling. Example: vendor_add('Pacific Crest Electrical',
    expense_category='Subcontracts')"""

@app.tool()
def vendor_list() -> list[dict]:
    """List all vendors with AP account path, current balance, and total paid."""

@app.tool()
def vendor_get_details(name: str) -> dict:
    """Return AP account path, expense account path, current balance,
    and transaction history for a named vendor."""

@app.tool()
def vendor_rename(old_name: str, new_name: str) -> dict:
    """Rename a vendor — updates both AP and expense account names atomically.
    Use when vendor name changes or was entered incorrectly.
    Does not affect existing transactions (accounts tracked by GUID)."""

@app.tool()
def vendor_update(
    name: str,
    new_expense_category: str,
) -> dict:
    """Move a vendor's expense account to a different expense category.
    Use when the wrong expense_category was supplied to vendor_add.
    Moves the expense account to the correct parent path.
    Does NOT migrate historical transactions to the new account path —
    existing transactions stay on the old account. Only future invoices
    will use the new path. Read gnucash://vendor-guide for valid categories."""

@app.tool()
def vendor_delete(
    name: str,
    confirm: bool = False,
) -> dict:
    """Delete a vendor — removes both AP and expense accounts.
    Requires confirm=True. Fails if either account has transactions
    (use vendor_get_details to check balance and history first).
    For vendors with history, consider leaving accounts in place —
    zero-balance AP accounts are invisible in normal operation."""
```

`vendor_add` creates two accounts atomically in a single GnuCash session:
- `Liabilities:AP — {name}`
- `Expenses:Construction — {expense_category}:{name}` (for subs)
  or `Expenses:{expense_category} — {name}` (for consultants)

**Design note on `vendor_update`:** Moving a vendor's expense account changes
where *future* invoices are coded, but does not restate *historical* transactions.
This is correct accounting behaviour — you don't reclass past expenses when you
correct a categorisation error going forward. If historical restatement is needed,
it requires voiding and reposting the relevant transactions manually.

**Design note on `vendor_delete`:** The `confirm=True` requirement mirrors
`delete_transaction`. The failure guard on existing transactions is intentional —
a sub who was paid once has AP history that matters for year-end reporting even
if they never work again. The recommended path for inactive vendors is to leave
the accounts in place (a zero-balance AP account costs nothing and is invisible
in AP aging reports).

**Expense category → account path mapping** (in `gnucash://vendor-guide`):

| expense_category | Account created |
|---|---|
| `Subcontracts` | `Expenses:Construction — Subcontracts:{name}` |
| `Materials` | `Expenses:Construction — Materials:{name}` |
| `Architecture` | `Expenses:Architecture — {name}` |
| `Structural` | `Expenses:Structural Engineering — {name}` |
| `MEP` | `Expenses:MEP Consulting — {name}` |
| `HVAC` | `Expenses:HVAC Engineering — {name}` |

**Tests:**
```
T2.2.1  vendor_add("Pacific Crest Electrical", "Subcontracts") creates:
         Liabilities:AP — Pacific Crest Electrical
         Expenses:Construction — Subcontracts:Pacific Crest Electrical
T2.2.2  vendor_add with invalid expense_category raises ValueError
T2.2.3  vendor_add is idempotent: adding same vendor twice does not duplicate accounts
T2.2.4  vendor_list includes newly added vendor with $0.00 balance
T2.2.5  After receive_invoice for new vendor, vendor_list shows correct AP balance
T2.2.6  vendor_rename updates both AP and expense account names atomically
T2.2.7  Existing transactions for renamed vendor remain valid (account GUID unchanged)
T2.2.8  vendor_get_details returns correct paths and $0 balance for new vendor
T2.2.9  vendor_update moves expense account to new category path
T2.2.10 vendor_update: transactions before update still on old path; new invoice
         uses new path (no historical restatement)
T2.2.11 vendor_update with invalid new_expense_category raises ValueError
T2.2.12 vendor_delete without confirm=True raises RequiresConfirmationError
T2.2.13 vendor_delete with confirm=True on zero-balance vendor removes both accounts
T2.2.14 vendor_delete on vendor with transaction history raises VendorHasHistoryError
         even with confirm=True (balance check is a hard guard, not overridable)
T2.2.15 Resource gnucash://vendor-guide is non-empty and contains expense_category table
T2.2.16 Resource gnucash://vendors returns updated list after vendor_add (live query)
T2.2.17 End-to-end: add vendor → receive invoice → pay invoice → AP clears to $0
```

---

### M2.3 — Resource completeness and lazy-load validation

**Deliverables:**
- All static resources populated with production content (not placeholder text)
- `gnucash://expected-chart` reflects full MC-6 account structure as a JSON dict
- `gnucash://budget-guide` and `gnucash://eco-guide` added in Phase 4 (M4.3)
- Manual test of the lazy-load pattern: confirm resources are NOT loaded at
  session start, ARE loaded when Claude decides to use an administrative tool

**Tests:**
```
T2.3.1  gnucash://resources returns dict with URIs for all static resources
         (book-setup-guide, vendor-guide, expected-chart, budget-guide, eco-guide)
T2.3.2  gnucash://expected-chart contains all accounts from MC-6 (automated check
         against the same constant used by book_verify_structure)
T2.3.3  Token audit (manual): start fresh Claude session, observe tool call log.
         Resources should NOT appear in context at start.
         Call vendor_add → gnucash://vendor-guide SHOULD appear in context.
         Document token counts in TEST_RESULTS.md.
T2.3.4  book_verify_structure on a correctly-initialized book returns ok:true
         (uses gnucash://expected-chart internally, not via Claude context)
```

---

### Phase 2 exit criteria

- `vendor_add` validated end-to-end: add sub → invoice → pay → AP clears
- `vendor_update` tested: expense category move verified; historical transactions unaffected
- `vendor_delete` friction test: fails without `confirm=True`; fails on vendor with history
- `book_verify_structure` passes cleanly on the production book
- Account CRUD (`book_rename_account`, `book_move_account`, `book_delete_account`)
  tested against fixture book
- Lazy-load pattern confirmed: resource tokens visible in Claude session only
  when an administrative tool is actively being used (T2.3.3 documented)
- All new vendor and book tools visible in Claude Desktop and CoWork tool list

---

## Phase 3 — Transaction CRUD and Audit Log

**Goal:** Complete the write surface. Correct errors in posted transactions without
manual GnuCash intervention. Expose change history to Claude so it can answer
"what changed and when" questions. Closes the gap with ninetails-io's transaction
CRUD feature set.

**Prerequisites:** Phase 1 and Phase 2 complete.

### M3.1 — Transaction correction tools

**Deliverables (add to `src/tools/write.py`):**

```python
@app.tool()
def update_transaction(
    transaction_guid: str,
    date: str | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> dict:
    """Update metadata on an existing transaction (date, description, notes).
    Does NOT change splits or amounts — use void_transaction + new entry for that.
    transaction_guid from list_transactions output."""

@app.tool()
def void_transaction(
    transaction_guid: str,
    reason: str,
) -> dict:
    """Mark a transaction as void. GnuCash records the void reason and
    zeroes the effect on account balances while preserving the audit trail.
    Preferred over delete for correcting errors in closed periods."""

@app.tool()
def delete_transaction(
    transaction_guid: str,
    confirm: bool = False,
) -> dict:
    """Permanently delete a transaction. Requires confirm=True.
    Use void_transaction instead for audit trail preservation.
    Only use delete for test/duplicate transactions with no accounting significance."""

@app.tool()
def get_transaction(
    transaction_guid: str,
) -> dict:
    """Return full detail of a single transaction including all splits,
    reconciliation state, void status, and notes."""
```

**Design notes:**

`update_transaction` intentionally cannot change splits or amounts. Changing
the financial substance of a posted transaction (amounts, accounts) requires
voiding it and posting a correcting entry — this is standard accounting practice
and prevents silent balance corruption. The GnuCash Python bindings enforce this
at the engine level; `update_transaction` only touches metadata fields that
GnuCash allows modifying on posted transactions.

`void_transaction` is the preferred correction path. GnuCash's void mechanism
zeroes all splits, records the reason, and keeps the transaction visible in the
register with a `[VOID]` prefix. This preserves the audit trail and is the
correct approach for any transaction that appears in a reconciled period.

`delete_transaction` with `confirm=True` is a bypass for removing erroneous
duplicate transactions or test entries that have no accounting significance.
The `confirm` parameter is a deliberate friction point — it must be explicitly
passed as `True`, preventing accidental deletion from a terse tool call.

**Tests:**
```
T3.1.1  update_transaction changes description; balance and splits unchanged
T3.1.2  update_transaction changes date; transaction appears at new date in register
T3.1.3  update_transaction with no fields changed is a no-op (returns unchanged record)
T3.1.4  void_transaction zeroes account balance effect; transaction visible as [VOID]
T3.1.5  void_transaction records reason in transaction notes
T3.1.6  void_transaction on already-voided transaction raises ValueError
T3.1.7  delete_transaction without confirm=True raises RequiresConfirmationError
T3.1.8  delete_transaction with confirm=True removes transaction; balance corrected
T3.1.9  get_transaction returns all splits with account paths and reconcile state
T3.1.10 get_transaction on voided transaction shows void status and reason
T3.1.11 After void_transaction + new correcting entry: net balance matches expected
         (end-to-end: receive wrong invoice amount → void → re-receive correct amount)
```

---

### M3.2 — Audit log tool

**Deliverables (add to `src/tools/read.py`):**

```python
@app.tool()
def get_audit_log(
    limit: int = 20,
    tool_filter: str | None = None,
    since_date: str | None = None,
) -> list[dict]:
    """Return recent entries from the MCP write-ahead log.
    Shows all write operations: tool name, timestamp, arguments,
    committed status, and transaction GUID if applicable.
    Use to answer 'what changed recently' or verify a write completed."""
```

The WAL (`mcp-wal.jsonl`) already records all write operations with full payloads.
This tool simply reads and filters it — no GnuCash session required. The Python
dispatcher handles this as a direct file read, making it fast and safe to call at
any time including when debugging a failed write.

Example output entry:
```json
{
  "id": "a1b2c3d4",
  "logged_at": "2025-04-01T14:32:15Z",
  "type": "receive_invoice",
  "payload": {
    "date": "2025-04-01",
    "vendor": "Pacific Crest Electrical",
    "invoice_ref": "PCE-001",
    "amount": "3450.00",
    "expense_account": "Expenses:Construction — Subcontracts:Pacific Crest Electrical"
  },
  "committed_at": "2025-04-01T14:32:16Z",
  "transaction_guid": "f1e2d3c4b5a6..."
}
```

**Tests:**
```
T3.2.1  get_audit_log returns entries in reverse chronological order
T3.2.2  limit=5 returns at most 5 entries
T3.2.3  tool_filter="receive_invoice" returns only invoice receipt entries
T3.2.4  since_date filters to entries after given date
T3.2.5  Uncommitted WAL entries (pending replay) appear with committed_at: null
T3.2.6  get_audit_log does not open a GnuCash session (pure file read, fast)
T3.2.7  Empty WAL returns empty list (not error)
```

---

### Phase 3 exit criteria

- Correction workflow validated end-to-end: post wrong invoice → void → post
  correct invoice → balances match expected (T3.1.11)
- `get_audit_log` returns readable history of all Phase 1 test transactions
- `delete_transaction` friction test: calling without `confirm=True` raises error
  (Claude must explicitly pass `confirm=True`)
- All 1c tools registered in `dispatch.py` and visible under `full` profile

---

## Phase 4 — Budget and ECO Tools

**Goal:** Replace the hardcoded ROM constants approach with live GnuCash native
budgets. The GC's pre-construction pricing enters the book as a real GnuCash
budget object; `get_budget_vs_actual()` queries it rather than Python constants.
Engineering Change Orders (ECOs) are tracked as first-class ledger objects
that adjust both the budget and the expense accounts.

**Prerequisites:** Phase 2 complete (account/vendor CRUD needed to set up
Construction expense accounts before budget amounts can be entered).

### M4.1 — Budget CRUD tools

**Background:** GnuCash budgets are stored as `GncBudget` objects in the book.
Each budget has a name, a recurrence rule (period type × multiplier × start date),
and a number of periods. Budget amounts are per-account per-period values.

For a construction project the recommended structure is:
- **One period** covering the full construction contract duration
- Budget amounts set on each `Expenses:Construction:*` account matching the GC's
  line items
- A second budget period (or separate budget) can be added for the draw schedule
  once the GC provides one

**Deliverables (`src/tools/budget.py`):**

```python
@app.tool()
def budget_create(
    name: str,
    description: str = "",
    num_periods: int = 1,
    period_start: str,        # YYYY-MM-DD
    period_months: int = 12,  # months per period; 0 = entire project as one period
) -> dict:
    """Create a new GnuCash budget. Call once when GC delivers pre-construction
    pricing. Use num_periods=1, period_months=0 for a single total-project budget.
    Read gnucash://budget-guide before calling."""

@app.tool()
def budget_list() -> list[dict]:
    """List all budgets in the book: name, description, num_periods, start date."""

@app.tool()
def budget_get(name: str) -> dict:
    """Return full budget: all accounts with budgeted amounts per period,
    actual committed/paid amounts, and variance. Reads live ledger transactions."""

@app.tool()
def budget_set_amount(
    budget_name: str,
    account_path: str,
    amount: str,
    period: int = 0,
) -> dict:
    """Set budget amount for an account in a period (0-indexed).
    Call for each line item in the GC's budget spreadsheet.
    Creates the account if it does not exist.
    Read gnucash://budget-guide for the workflow."""

@app.tool()
def budget_update(
    name: str,
    new_name: str | None = None,
    new_description: str | None = None,
) -> dict:
    """Update budget name or description. Does not change amounts or periods.
    To revise amounts, call budget_set_amount on each changed line."""

@app.tool()
def budget_delete(
    name: str,
    confirm: bool = False,
) -> dict:
    """Delete a budget. Requires confirm=True. Does not affect transactions.
    Use when replacing with a revised GC budget after value engineering."""
```

**Key implementation note — `budget_set_amount` creates accounts:**
When entering a GC budget for the first time, many `Expenses:Construction:*`
accounts won't exist yet. `budget_set_amount` calls `book_add_account` internally
if the account path doesn't exist, using `EXPENSE` type and `USD` commodity.
This means the workflow to enter a GC budget is simply:

```
budget_create("GC Pre-Construction", period_start="2025-09-01", num_periods=1)
budget_set_amount("GC Pre-Construction", "Expenses:Construction:Demo", "8600.00")
budget_set_amount("GC Pre-Construction", "Expenses:Construction:Framing", "32000.00")
budget_set_amount("GC Pre-Construction", "Expenses:Construction:Electrical", "45000.00")
... (one call per GC line item)
```

**`budget_get` output structure:**
```json
{
  "name": "GC Pre-Construction",
  "total_budgeted": "462000.00",
  "total_committed": "127450.00",
  "total_paid": "89200.00",
  "total_variance": "334550.00",
  "accounts": [
    {
      "account": "Expenses:Construction:Electrical",
      "period": 0,
      "budgeted": "45000.00",
      "committed": "22500.00",
      "paid": "22500.00",
      "variance": "22500.00",
      "pct_committed": 50.0
    }
  ]
}
```

**Note:** `committed` = sum of AP invoices posted to the account (regardless of
payment status). `paid` = sum of payments from Project Checking. `variance` =
`budgeted - committed` (positive = under budget). This matches standard
construction project accounting practice.

**Tests:**
```
T4.1.1  budget_create creates GncBudget object in book with correct num_periods
T4.1.2  budget_list returns newly created budget
T4.1.3  budget_set_amount sets amount on existing account
T4.1.4  budget_set_amount creates account and sets amount when account doesn't exist
T4.1.5  budget_get returns all accounts with correct budgeted amounts
T4.1.6  budget_get shows committed = 0, paid = 0, variance = budget before any invoices
T4.1.7  After receive_invoice to a budgeted account: budget_get shows correct committed
T4.1.8  After pay_invoice: budget_get shows correct paid; committed unchanged
T4.1.9  budget_update renames budget; amounts unchanged
T4.1.10 budget_delete without confirm=True raises RequiresConfirmationError
T4.1.11 budget_delete with confirm=True removes budget; transactions unaffected
T4.1.12 Full workflow: create budget → set 5 line items → receive 2 invoices →
         budget_get shows correct committed/paid/variance for each line
```

---

### M4.2 — Engineering Change Order (ECO) tools

**Background:** An ECO (Engineering Change Order, also called CO — Change Order)
is a formal modification to the GC's contracted scope and/or price. Each ECO has:
- A number and description
- A direction: **additive** (owner-requested scope addition) or **deductive**
  (scope reduction, credit back to owner)
- A status: **pending** (submitted, awaiting approval), **approved** (signed),
  **void** (rejected or cancelled)
- A cost impact: amount and which budget line(s) it affects
- An optional schedule impact (days added or removed)

ECOs are tracked in the book using two mechanisms:
1. **KVP slots** on a dedicated `Liabilities:Change Orders Pending` account
   (or as book-level metadata) to store the ECO registry
2. **Expense transactions** posted to `Expenses:Change Orders:*` accounts when
   approved, so the impact appears in the ledger

This keeps the original contract budget clean while making ECO costs visible
independently. `get_budget_vs_actual()` can then report separately on:
- Original contract spend vs original budget
- ECO spend vs approved ECO total
- Combined total vs combined budget

**Deliverables (`src/tools/eco.py`):**

```python
@app.tool()
def eco_create(
    number: str,             # e.g. "CO-001"
    description: str,
    direction: str,          # "additive" | "deductive"
    amount: str,             # decimal, always positive
    budget_account: str,     # which Construction account this affects
    schedule_days: int = 0,  # schedule impact; 0 = no schedule impact
    notes: str = "",
) -> dict:
    """Create a new pending ECO. Does not affect account balances until approved.
    Read gnucash://eco-guide for direction conventions and numbering."""

@app.tool()
def eco_list(
    status: str | None = None,  # "pending" | "approved" | "void" | None = all
) -> list[dict]:
    """List ECOs with number, description, direction, amount, status.
    status=None returns all. Use status='pending' to review open items."""

@app.tool()
def eco_get(number: str) -> dict:
    """Return full ECO detail: all fields plus any transactions posted on approval."""

@app.tool()
def eco_approve(
    number: str,
    date: str,           # YYYY-MM-DD — date GC/owner signed
    invoice_ref: str = "",  # GC invoice reference if CO is billed separately
) -> dict:
    """Approve a pending ECO. Posts a transaction to Expenses:Change Orders:*
    (additive) or reversal transaction (deductive). Updates ECO status to approved.
    Increases or decreases the budget on the affected account by the ECO amount."""

@app.tool()
def eco_void(
    number: str,
    reason: str,
) -> dict:
    """Void a pending or approved ECO. If approved, reverses the posted transaction.
    Records the void reason. Does not delete — maintains audit trail."""
```

**Account structure for ECOs:**
```
Expenses:Change Orders          ← parent, mirrors Construction hierarchy
  Change Orders:Demo
  Change Orders:Electrical
  Change Orders:Plumbing
  ... (one per construction line that has a CO)
  Change Orders:New Scope       ← for COs adding scope not in original contract
```

**`eco_approve` accounting entries:**

Additive CO (owner pays more):
```
DR Expenses:Change Orders:Electrical    $5,000
  CR Liabilities:AP — [GC name]         $5,000
```
The budget on `Expenses:Construction:Electrical` is increased by $5,000.

Deductive CO (credit back to owner):
```
DR Liabilities:AP — [GC name]          $2,000
  CR Expenses:Change Orders:Electrical  $2,000
```
The budget on `Expenses:Construction:Electrical` is decreased by $2,000.

**ECO storage:** ECO metadata (number, description, status, direction, notes)
is stored as book KVP slots under a `mcp/ecos/{number}` key path. The approved
transaction GUID is stored alongside so `eco_get` can retrieve full detail.
This is a lightweight alternative to creating a separate GnuCash table, and
the KVP data persists in the XML book file.

**Tests:**
```
T4.2.1  eco_create stores ECO with status=pending; no transactions posted
T4.2.2  eco_list returns newly created ECO with correct fields
T4.2.3  eco_list(status="pending") excludes approved and voided ECOs
T4.2.4  eco_get returns full ECO detail including notes
T4.2.5  eco_approve(additive) posts DR Change Orders / CR AP transaction
T4.2.6  eco_approve(additive) increases budget on affected account
T4.2.7  eco_approve(deductive) posts DR AP / CR Change Orders reversal
T4.2.8  eco_approve(deductive) decreases budget on affected account
T4.2.9  eco_void(pending) changes status; no transaction posted
T4.2.10 eco_void(approved) reverses posted transaction; budget reverted
T4.2.11 eco_void records reason in KVP; ECO visible in eco_list with void status
T4.2.12 eco_list shows correct total approved ECO value and pending ECO exposure
T4.2.13 Full workflow: CO-001 additive $5K electrical → approve → budget_get shows
         original $45K + $5K ECO split correctly; variance updated
```

---

### M4.3 — Updated budget_vs_actual and project_summary

**Deliverables:**

`get_budget_vs_actual()` is updated to query the live GnuCash budget instead of
hardcoded constants. If no budget exists in the book, returns a clear error
message directing the user to run `budget_create` + `budget_set_amount`.

```python
@app.tool()
def get_budget_vs_actual(
    budget_name: str | None = None,  # None = use first/only budget in book
    include_ecos: bool = True,        # include approved ECO amounts separately
) -> dict:
    """Compare live budget vs actual spend.
    Returns original contract budget, ECO adjustments, revised budget,
    committed, paid, and variance per account and in total."""
```

Output when `include_ecos=True`:
```json
{
  "budget_name": "GC Pre-Construction",
  "as_of": "2025-11-15",
  "summary": {
    "original_contract": "462000.00",
    "approved_ecos": "8500.00",
    "revised_budget": "470500.00",
    "committed": "127450.00",
    "paid": "89200.00",
    "remaining": "342550.00",
    "pct_committed": 27.1
  },
  "by_account": [ ... ]
}
```

`get_project_summary()` is updated to include a `budget_status` field:
```json
{
  "funded": "...",
  "spent": "...",
  "open_ap": "...",
  "cash_balance": "...",
  "interest_earned": "...",
  "budget_status": {
    "original_contract": "462000.00",
    "approved_ecos": "8500.00",
    "committed_pct": 27.1,
    "pending_eco_exposure": "12000.00"
  }
}
```

**Tests:**
```
T4.3.1  get_budget_vs_actual with no budget in book returns clear error message
T4.3.2  get_budget_vs_actual returns correct variance after entering GC budget
T4.3.3  get_budget_vs_actual(include_ecos=True) shows ECO adjustments separately
T4.3.4  get_budget_vs_actual(include_ecos=False) shows only original contract budget
T4.3.5  get_project_summary includes budget_status with correct pending_eco_exposure
T4.3.6  Professional fees (Architecture, Structural, MEP) appear in budget_vs_actual
         only if a budget amount has been set on those accounts
```

---

### Phase 4 exit criteria

- Full GC budget entry workflow validated: create budget → set all line items →
  `budget_get` matches GC spreadsheet totals
- ECO round-trip tested: create → approve (additive) → `budget_get` shows revised
  budget; `eco_list` shows approved CO
- `get_budget_vs_actual()` no longer references hardcoded constants from `src/budget.py`
  (that file is deleted or reduced to utility functions only)
- `get_project_summary()` includes `budget_status` with ECO exposure
- New resource `gnucash://budget-guide` and `gnucash://eco-guide` populated with
  workflow documentation and served statically from Swift proxy

---

## Phase 5 — Infrastructure: Sparsebundle, Wrappers, and Snapshots

**Goal:** Harden the operational story. The sparsebundle is the authoritative
storage medium. The zsh wrappers handle the full lifecycle cleanly. Snapshots work.

**Prerequisites:** Phase 1, Phase 2, Phase 3, and Phase 4 complete. Spike E result known.

### M5.1 — Sparsebundle creation and book migration

**Deliverables:**
- `scripts/create-book-volume.zsh` — one-time setup:
  - Creates `~/books/project.sparsebundle` (100MB initial, APFS)
  - Attaches read-write at `/Volumes/GnuCash-Project`
  - Moves Phase 1 `project.gnucash` into the volume
  - Verifies Python bindings can open the file via container `/data` path
- Setup procedure documented in README.md

**Tests:**
```
T5.1.1  Script creates ~/books/project.sparsebundle
T5.1.2  Volume mounts at /Volumes/GnuCash-Project after script runs
T5.1.3  project.gnucash present inside mounted volume
T5.1.4  GnuCash Python bindings open the file via /data/project.gnucash in container
T5.1.5  hdiutil detach /Volumes/GnuCash-Project succeeds cleanly
T5.1.6  Re-running script with volume already present aborts with clear error message
```

---

### M5.2 — Swift proxy Phase 1 (gnucash-mcp binary)

**Deliverables:** `Sources/gnucash-mcp/` — Swift executable implementing MC-9
Phase 1 proxy:

- NIO HTTP server on `localhost:8980`; handles `initialize`, `tools/list`,
  `resources/list`, `resources/read` (static) without starting a container
- Per-request container dispatch via `ContainerAPIClient` stdin/stdout
- Container pool: size 1, 5-second TTL; reap loop checks every 1s
- Sleep/wake recovery: validates container liveness before reuse (KU-11)
- Sparsebundle mount via `Process` (`hdiutil attach -readwrite -nobrowse`)
  on first tool call; unmount on SIGTERM/SIGINT
- Pre-session APFS snapshot before first write in each proxy session
- SIGTERM/SIGINT → drain pool → detach sparsebundle → exit
- Subcommands: `gnucash-mcp start`, `gnucash-mcp stop`, `gnucash-mcp status`

**Static tool catalog in Swift (Tier 1 + Tier 2 — compiled, not runtime):**

```swift
// Sources/gnucash-mcp/ToolCatalog.swift

// Tier 1 — Operational (full descriptions; daily use)
static let tier1: Set<String> = [
    "receive_invoice", "pay_invoice", "fund_project", "post_interest",
    "post_transaction", "get_account_balance", "list_accounts",
    "list_transactions", "get_transaction", "get_project_summary",
    "get_budget_vs_actual", "get_ap_aging", "get_audit_log",
]

// Tier 1 — Transaction correction (full descriptions; occasional use)
static let tier1Crud: Set<String> = [
    "update_transaction", "void_transaction", "delete_transaction",
]

// Tier 2 — Administrative (minimal descriptions + resource pointers)
static let tier2: Set<String> = [
    "book_add_account", "book_get_account_tree", "book_verify_structure",
    "book_set_opening_balance", "book_rename_account", "book_move_account",
    "book_delete_account",
    "vendor_add", "vendor_list", "vendor_get_details", "vendor_rename",
    "vendor_update", "vendor_delete",
    "budget_create", "budget_list", "budget_get", "budget_set_amount",
    "budget_update", "budget_delete",
    "eco_create", "eco_list", "eco_get", "eco_approve", "eco_void",
    "__unlock_ledger__",
]

// Profile subsets (used by MC-10 profile selection)
static let readOnly: Set<String> = [
    "get_account_balance", "list_accounts", "list_transactions",
    "get_transaction", "get_project_summary", "get_audit_log",
]
static let setup: Set<String> = [
    "book_add_account", "book_get_account_tree", "book_verify_structure",
    "book_set_opening_balance", "book_rename_account", "book_move_account",
    "book_delete_account",
    "vendor_add", "vendor_list", "vendor_get_details", "vendor_rename",
    "vendor_update", "vendor_delete",
    "budget_create", "budget_list", "budget_get", "budget_set_amount",
    "budget_update", "budget_delete",
    "eco_create", "eco_list", "eco_get",
    "__unlock_ledger__",
]
static let construction: Set<String> = tier1
    .union(tier1Crud)
    .union(["eco_create", "eco_list", "eco_get", "eco_approve", "eco_void"])
static let operational: Set<String> = tier1.union(tier1Crud)
static let reconcile: Set<String> = [
    "list_transactions", "get_transaction", "get_account_balance",
    "get_audit_log", "void_transaction", "update_transaction",
    // reconciliation tools added in Phase 7
]

static let tools: [MCPTool] = [
    // Tier 1 operational
    MCPTool(name: "receive_invoice",
            description: "DR expense_account, CR AP-vendor. Read gnucash://vendor-guide first if vendor is new.",
            inputSchema: .object([
                "date":            .string("YYYY-MM-DD"),
                "vendor":          .string("Exact name e.g. 'Acme Architecture'"),
                "invoice_ref":     .string("e.g. 'AAI-102'"),
                "amount":          .string("Decimal e.g. '25000.00'"),
                "expense_account": .string("Full path e.g. 'Expenses:Architecture — Acme Architecture'"),
            ], required: ["date","vendor","invoice_ref","amount","expense_account"])),
    // ... other Tier 1 tools

    // Tier 1 CRUD
    MCPTool(name: "void_transaction",
            description: "Zero out a transaction while preserving audit trail. Preferred over delete.",
            inputSchema: .object([
                "transaction_guid": .string("From list_transactions or get_transaction"),
                "reason":           .string("Reason for void e.g. 'Wrong amount, see TXN-xyz'"),
            ], required: ["transaction_guid","reason"])),
    MCPTool(name: "delete_transaction",
            description: "Permanently delete transaction. Pass confirm=true explicitly. Use void_transaction instead for audit trail.",
            inputSchema: .object([
                "transaction_guid": .string(),
                "confirm":          .bool(description: "Must be true to proceed"),
            ], required: ["transaction_guid","confirm"])),
    // ... update_transaction, get_transaction, get_audit_log

    // Tier 2 administrative — minimal descriptions
    MCPTool(name: "book_add_account",
            description: "Add account to chart of accounts. Read gnucash://book-setup-guide first.",
            inputSchema: .object([
                "name":         .string(),
                "parent_path":  .string(),
                "account_type": .enum(["ASSET","LIABILITY","EQUITY","INCOME","EXPENSE"]),
                "commodity":    .string(default: "USD"),
            ], required: ["name","parent_path","account_type"])),
    // ... other Tier 2 tools
]
```

**Container dispatch flow:**

```swift
func dispatch(_ request: JSONRPCRequest) async throws -> JSONRPCResponse {
    // Static responses — no container
    if request.method == "initialize" { return staticInitializeResponse }
    if request.method == "tools/list" { return MCPResponse(tools: ToolCatalog.tools) }
    if request.method == "resources/list" { return staticResourcesList }
    if request.method == "resources/read",
       let uri = request.params?.uri,
       let content = StaticResources.content(for: uri) {
        return MCPResponse(content: content)
    }

    // Dynamic — requires container
    let container = try await pool.acquire()  // start or reuse
    defer { pool.release(container) }         // reset TTL

    let data = try JSONEncoder().encode(request)
    let response = try await container.roundTrip(stdin: data)
    return try JSONDecoder().decode(JSONRPCResponse.self, from: response)
}
```

**Tests:**
```
T5.2.1  gnucash-mcp start attaches sparsebundle and begins listening on :8980
T5.2.2  curl POST localhost:8980/mcp initialize returns valid response, no container started
T5.2.3  curl POST localhost:8980/mcp tools/list returns full catalog, no container started
T5.2.4  curl POST localhost:8980/mcp resources/read gnucash://book-setup-guide returns
        markdown content, no container started
T5.2.5  tools/call receive_invoice starts container, dispatches, returns result
T5.2.6  Second tools/call within 5s reuses warm container (pool hit — verify via timing
        and ContainerAPIClient call count)
T5.2.7  Third tools/call after 6s idle starts fresh container (pool miss after TTL)
T5.2.8  gnucash-mcp status shows correct pool state (warm/cold) and last call time
T5.2.9  gnucash-mcp stop sends SIGTERM → proxy drains pool → detaches sparsebundle
        → exits cleanly within 5 seconds
T5.2.10 kill -9 on proxy → sparsebundle left attached (expected) → gnucash-mcp start
        detects existing mount and re-attaches cleanly or errors clearly
T5.2.11 Simulate sleep/wake: stop container externally while pool holds handle →
        next tool call detects stale handle, starts fresh container, succeeds (KU-11)
T5.2.12 Claude Desktop shows gnucash-myproject as connected after gnucash-mcp start
        (manual; record in TEST_RESULTS.md)
T5.2.13 CoWork session can call get_project_summary() via SDK bridge (manual)
```

---

### M5.3 — GUI wrapper (gnucash-browse)

**Deliverables:**
- `bin/gnucash-browse` zsh script:
  - Guard: abort if `/Volumes/GnuCash-Project` already mounted (MCP running)
  - Guard: abort if GnuCash process already running
  - Attach sparsebundle read-only with `-nobrowse`
  - `trap EXIT INT TERM`: detach on quit
  - Launch GnuCash via direct binary path, pass book file as argument
  - Wait on GnuCash PID (direct `wait $PID`, not `open --wait-apps`)
    — resolves KU-7: test both methods, choose the one that blocks until
    GnuCash fully releases all file handles before detach

**Tests:**
```
T5.3.1  Script aborts if /Volumes/GnuCash-Project already mounted
T5.3.2  Script aborts if GnuCash process already running (pgrep check)
T5.3.3  Volume attached read-only — confirmed by attempting write from shell:
        echo x >> /Volumes/GnuCash-Project/test.txt → "Read-only file system" error
T5.3.4  GnuCash opens book and displays account tree (manual)
T5.3.5  Cmd-S in GnuCash produces no-op or error, no .LCK created (Spike D confirmed)
T5.3.6  Quitting GnuCash triggers detach — mount point gone within 10 seconds
T5.3.7  All Phase 1 transactions visible and correct in GUI (manual cross-check)
T5.3.8  GnuCash force-quit (Activity Monitor) → EXIT trap fires → sparsebundle detached
        (KU-7 confirmation: test `wait $PID` vs `open --wait-apps` for this case)
```

---

### M5.4 — Snapshot management

**Deliverables:**
- `scripts/snapshot.zsh` with functions exported for use in both wrappers:
  - `snapshot_create [volume_mount]`
  - `snapshot_list [volume_mount]`
  - `snapshot_mount <snapshot_name> <volume_device> <mountpoint>`
  - `snapshot_restore_file <snapshot_name> <volume_device> <relative_file_path>`
  - `snapshot_prune <keep_count> <volume_device>`
- Pre-session snapshot integrated into Swift proxy `start` subcommand (MC-9)

**Tests:**
```
T5.4.1  snapshot_create creates snapshot with gnucash-mcp- prefix
T5.4.2  snapshot_list shows the new snapshot in output
T5.4.3  snapshot_mount mounts snapshot at given path, read-only
T5.4.4  File from mounted snapshot matches the file as of snapshot time
T5.4.5  snapshot_restore_file copies file from snapshot alongside live file
        with .restored extension; original file unchanged
T5.4.6  snapshot_prune 3 leaves exactly 3 gnucash-mcp- prefixed snapshots;
        other snapshot types (Time Machine etc.) unaffected
T5.4.7  Restore drill (manual, document in TEST_RESULTS.md):
        Post a bad transaction → take snapshot → post another transaction →
        restore from snapshot → verify bad transaction gone and book intact
```

---

### Phase 5 exit criteria

- Full session lifecycle works end-to-end:
  `gnucash-mcp start` → Claude posts transactions → pool reaps container →
  `gnucash-browse` → read-only GUI → quit → all mounts clean
- No dangling mounts after normal and abnormal exits (T5.2.9–11, T5.3.6–8)
- Snapshot pre-session and file restore tested against real book data
- `README.md` written with: prerequisites, one-time setup, daily-use workflow,
  recovery procedures

---

## Phase 6 — Project-Specific MCP Tools

**Goal:** Project-specific tools: budget tracking, AP aging,
interest income, and tranche management. Claude can answer project finance questions
directly from the ledger.

**Prerequisites:** Phase 5 complete.

### M6.1 — External budgets & professional fees (TOML-driven)

TL;DR — Professional-fee contract values and auxiliary external budget items
(hourly overtime rates, material overage allowances, contingency percentages)
live in a per-book TOML that the Swift proxy loads at startup and exposes to MCP
clients. GnuCash remains authoritative for transactions and native budgets; TOML
supplements reporting only.

Schema (suggested file: `gnucash-mcp-budgets.toml`)
- `meta`: title, version, currency, effective_date
- `professional_fees`: list of { account, contract_type (fixed|range), contract_total?, contract_low?, contract_high?, notes }
- `external_budgets`: list of { account, amount, notes }
- `rates`: { overtime_multiplier, material: { overage_pct } }
- `proxy`: { expose_resource, validate_on_start, hot_reload_sighup }

Example snippet
```toml
[meta]
title = "Example construction project budgets"
version = "1.0"
currency = "USD"
effective_date = "2026-04-01"

[[professional_fees]]
account = "Expenses:Architecture — Acme Architecture"
contract_type = "fixed"
contract_total = 42000.00
notes = "AAI #101 + #102 per REV2"

[[external_budgets]]
account = "Expenses:Construction:Allowances"
amount = 15000.00
notes = "GC allowances not represented in native budget"

[rates]
overtime_multiplier = 1.5

[rates.material]
overage_pct = 0.10

[proxy]
expose_resource = "gnucash://budget-extensions"
validate_on_start = true
hot_reload_sighup = true
```

Runtime merge rules
- Query native GnuCash budgets first for `get_budget_vs_actual()`.
- If a native budget is missing for an account, fall back to `external_budgets`.
- `professional_fees` entries in TOML are authoritative contract constants used
  by `get_project_summary()`.
- `rates` are advisory inputs used by proxy-level calculations (runway, overage)
  and are not written back to the book.

Operational behavior
- Location: default `$BOOK_DIR/gnucash-mcp-budgets.toml`; override via
  `GNUCASH_MCP_CONFIG` or `--config` CLI flag. Precedence: CLI > env > per-book
  file > built-in defaults.
- On startup: Swift proxy loads and validates TOML (fatal if `validate_on_start=true`
  and file malformed). Proxy publishes combined view at `gnucash://budget-extensions`
  and makes the TOML available to containers at `/run/mcp/budgets.toml` (read-only)
  plus env `GNUCASH_MCP_BUDGETS`.
- Hot-reload: SIGHUP triggers re-validate + re-publish; invalid updates are
  rejected and logged while the previous config remains active.
- Audit: responses that use external values annotate `source` and `effective_date`.

Verification (tests)
1. Unit: TOML parser validates required fields and numeric types.
2. Integration: proxy started with sample TOML exposes `gnucash://budget-extensions`
   including `professional_fees`, `external_budgets`, and `rates`.
3. Functional: `get_project_summary()` includes `professional_fees` totals combined
   with live GnuCash construction budget; test both presence and absence of native
   budget entries.
4. Edge: invalid updated TOML + SIGHUP leaves proxy using previous config and logs an error.

Decision / assumptions
- Professional fees are kept in TOML because they are fixed contract figures and
  not expected to be edited in GnuCash.
- External budget items and rates are advisory and live in TOML so the Swift proxy
  can calculate aggregated views without writing to the book.
- GnuCash remains the single source for transactional truth after startup.

---

### M6.2 — AP aging

**Deliverables:**
- `get_ap_aging() -> dict`
  - Per vendor: `vendor`, `invoice_ref`, `invoice_date`, `due_date`,
    `amount`, `days_outstanding`, `past_due`
  - Only includes vendors with non-zero AP balance

**Tests:**
```
T6.2.1  Vendor with paid invoice shows $0 balance and does not appear in output
T6.2.2  Vendor with open invoice shows correct amount and days_outstanding
T6.2.3  Invoice past due_date has past_due: true
T6.2.4  get_ap_aging() returns empty dict when all AP cleared
T6.2.5  days_outstanding calculated from today's date, not a hardcoded value
```

---

### M6.3 — Interest income

**Deliverables:**
- `post_interest(month: str, amount: str) -> dict`
  - Posts: debit Project Checking, credit Interest Income — Project Account
  - `month` format: `YYYY-MM`
- `estimate_monthly_interest(apy: float = 0.03) -> dict`
  - Returns estimated monthly interest on current Project Checking balance
  - Returns `{"estimated": "270.00", "balance": "107978.00", "apy": 0.03}`

**Tests:**
```
T6.3.1  post_interest("2025-01", "270.00") creates balanced transaction
T6.3.2  Interest Income account balance increases by posted amount
T6.3.3  estimate_monthly_interest(0.03) with $107,978 balance returns ~$270
T6.3.4  post_interest with negative amount raises ValueError (not posted)
T6.3.5  post_interest with invalid month format raises ValueError
```

---

### M6.4 — Tranche tracking and runway

**Deliverables:**
- `get_tranche_summary() -> dict`
  - All `fund_project` transactions: date, amount, running total
- `project_runway_days() -> int | None`
  - Estimate: cash balance ÷ (total spend ÷ days since first transaction)
  - Returns `None` if no spend activity yet

**Tests:**
```
T6.4.1  get_tranche_summary() lists each fund_project transaction with correct amounts
T6.4.2  Running total in get_tranche_summary() matches
        get_account_balance("Assets:Project Checking — First Project Bank")
T6.4.3  project_runway_days() returns a positive integer after some spend activity
T6.4.4  project_runway_days() with zero spend returns None (not ZeroDivisionError)
T6.4.5  project_runway_days() changes correctly after posting a new payment
```

---

### Phase 6 exit criteria

Claude can answer all of the following from the live ledger, without manual
calculation:

- "How much have I spent on architecture vs the signed contract?"
- "What invoices are currently unpaid and how long outstanding?"
- "What is my remaining budget for electrical, compared to the GC's contract?"
- "How many months of runway do I have at current spend rate?"
- "How much interest have I earned on the project account this year?"
- "What change orders are pending and what is my total ECO exposure?"
- "What is my revised contract total including approved change orders?"

All answers cross-checked against project documents in this Claude project.
Construction budget answers require Phase 4 complete (GC budget entered).

---

## Phase 7 — Reconciliation and Reporting

**Goal:** Bank reconciliation workflow and exportable reports for tax and
record-keeping purposes.

**Prerequisites:** Phase 6 complete.

### M7.1 — Bank reconciliation

**Deliverables:**
- `reconcile_account(account_path, statement_balance, statement_date) -> dict`
  - Returns: `ledger_balance`, `outstanding_items`, `reconciling_difference`
- `mark_cleared(transaction_id: str) -> dict`
  - Sets the GnuCash reconciliation flag on a transaction split

**Tests:**
```
T7.1.1  reconcile_account returns correct non-zero difference when one check outstanding
T7.1.2  reconcile_account returns difference of $0.00 when fully reconciled
T7.1.3  mark_cleared updates reconciliation flag; transaction appears as cleared in GUI
T7.1.4  Manual reconciliation drill against one actual project checking statement
        (document date, statement balance, result in TEST_RESULTS.md)
```

---

### M7.2 — CSV export

**Deliverables:**
- `export_transactions_csv(account_path, start_date, end_date) -> str`
  - CSV: date, description, debit, credit, balance, memo, reconciled
- `export_journal_csv(start_date, end_date) -> str`
  - Full double-entry journal: date, description, account, debit, credit

**Tests:**
```
T7.2.1  export_transactions_csv produces valid CSV with correct column headers
T7.2.2  Date range filtering excludes transactions outside range
T7.2.3  Debit/credit amounts in CSV match GnuCash register values
T7.2.4  CSV opens without error in Numbers and column types are preserved (manual)
T7.2.5  export_journal_csv debits equal credits across all rows (balanced)
```

---

### M7.3 — Year-end summary

**Deliverables:**
- `get_year_end_summary(year: int) -> dict`
  - `total_spend`, `interest_income` (for 1099-INT reference),
    `tranches_funded`, `ap_balance_year_end`, `net_project_cost`

**Tests:**
```
T7.3.1  get_year_end_summary(2024) returns correct totals for known 2024 transactions
T7.3.2  interest_income matches sum of post_interest entries for the year
T7.3.3  ap_balance_year_end matches known open invoices as of Dec 31
T7.3.4  net_project_cost = total_spend - interest_income (verified manually)
```

---

### Phase 7 exit criteria

- Monthly reconciliation workflow tested against one real bank statement
- 2024 year-end summary produced and validated against project documents
- CSV exports usable in Numbers for ad-hoc analysis

---

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

## Appendix A — Test Execution

Tests are named `T{phase}.{milestone}.{number}`. Within a milestone, run in
order. Milestones within a phase run in order.

**Two test modes:**

*Unit tests* — pytest with GnuCash book fixtures. Run inside the container
against a temp directory. No HTTP server, no Claude Desktop. Cover all T1.x,
T2.x, T6.x, T7.x logic.

*Integration tests* — require the full stack (Swift proxy running, Claude Desktop
connected). These are manual tests recorded in `TEST_RESULTS.md`. Identified in
test lists as `(manual)` or by reference to Claude Desktop / CoWork behavior.

Automated test fixtures:

```python
# tests/conftest.py
import pytest
from pathlib import Path
import gnucash

@pytest.fixture
def fresh_book(tmp_path):
    path = str(tmp_path / "test.gnucash")
    from gnucash_mcp.session import open_session, close_session
    session = open_session(path, is_new=True)  # uses SESSION_NEW_STORE + early save
    book = session.book
    yield book, path
    try:
        close_session(session)
    except Exception:
        pass

@pytest.fixture
def initialized_book(tmp_path):
    """Book with full chart of accounts (MC-6)."""
    path = str(tmp_path / "project-test.gnucash")
    from scripts.init_book import initialize
    from gnucash_mcp.session import open_session, close_session
    initialize(path)
    session = open_session(path, is_new=False)  # uses SESSION_NORMAL_OPEN
    book = session.book
    yield book, path
    try:
        close_session(session)
    except Exception:
        pass

@pytest.fixture
def populated_book(tmp_path):
    """Book with chart of accounts + known historical transactions.
    Provides a stable base for budget vs actual and AP aging tests."""
    path = str(tmp_path / "project-populated.gnucash")
    from scripts.init_book import initialize
    from scripts.load_fixtures import load_known_invoices
    from gnucash_mcp.session import open_session, close_session
    initialize(path)
    load_known_invoices(path)   # AAI-101, AAI-102, PSE-101, PSE-102, MMEP series
    session = open_session(path, is_new=False)
    book = session.book
    yield book, path
    try:
        close_session(session)
    except Exception:
        pass
```

Tests marked `(manual)` require human verification; record outcomes in
`TEST_RESULTS.md` with date, tester, and pass/fail.

Run automated unit suite inside container:
```zsh
cd gnucash-mcp
container run --rm \
  --volume $(pwd):/src \
  --volume /tmp/test-books:/data \
  gnucash-mcp:latest \
  bash -c "cd /src && uv run pytest tests/ -v --ignore=tests/test_integration.py"
```

Run HTTP integration smoke tests (requires Swift proxy running):
```zsh
# Verify proxy responds to initialize without starting a container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}' \
  | python3 -m json.tool | grep '"name"'
# Expected: "gnucash-myproject"

# Verify tools/list returns full catalog without starting a container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | python3 -m json.tool | grep '"name"'
# Expected: list of all 21 tool names

# Verify static resource served without container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"gnucash://book-setup-guide"}}' \
  | python3 -m json.tool | head -5
# Expected: resource content, no container started

# Verify tool call dispatches to container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_project_summary","arguments":{}}}' \
  | python3 -m json.tool
# Expected: project summary JSON, container started and stopped
```

---

## Appendix B — File Layout

```
gnucash-mcp/
├── DEVELOPMENT.md             ← this file
├── SPIKE_RESULTS.md           ← Phase 0 outcomes (fill in as spikes run)
├── TEST_RESULTS.md            ← manual test log
├── README.md                  ← setup and daily-use guide (Phase 5+)
│
├── Package.swift              ← Swift package (gnucash-mcp proxy binary)
├── Package.resolved
├── .swift-version             ← pinned Swift toolchain (Xcode-bundled, macOS 26)
├── .swiftformat
│
├── Sources/
│   └── gnucash-mcp/           ← Swift proxy executable (MC-9)
│       ├── main.swift         ← @main, ArgumentParser entrypoint
│       ├── CLI.swift          ← start/stop/status/install/snapshot subcommands
│       ├── MCPHTTPServer.swift ← NIO HTTP server on localhost:8980
│       ├── MCPHandler.swift   ← routes initialize/tools/resources to catalog or container
│       ├── ToolCatalog.swift  ← compiled tool schemas, Tier 1 + Tier 2 (MC-8, MC-9)
│       ├── StaticResources.swift ← book-setup-guide, vendor-guide, expected-chart,
│       │                           budget-guide, eco-guide (all served without container)
│       ├── ContainerPool.swift ← size-1 TTL pool; sleep/wake recovery (KU-11)
│       ├── ContainerDispatch.swift ← ContainerAPIClient stdin/stdout round-trip
│       ├── VolumeMount.swift  ← hdiutil attach/detach via Process
│       ├── Snapshot.swift     ← tmutil / cp -c pre-session snapshot (Spike E result)
│       └── JSONRPCTypes.swift ← Codable MCP message types
│
├── Tests/
│   └── gnucash-mcpTests/      ← Swift unit tests for proxy logic
│       ├── ToolCatalogTests.swift
│       ├── ContainerPoolTests.swift
│       └── JSONRPCTests.swift
│
├── Docker/
│   └── Dockerfile             ← Ubuntu 24.04 + python3-gnucash from PPA
│
├── pyproject.toml             ← uv-managed Python project (container image contents)
├── src/
│   ├── __main__.py            ← one-shot stdin→stdout dispatcher entry point (M1.5)
│   ├── dispatch.py            ← routes JSON-RPC method+name to handler (M1.5)
│   ├── session.py             ← GnuCash session manager (MC-2)
│   ├── wal.py                 ← write-ahead log (MC-3)
│   ├── budget_constants.py    ← professional fee contract values (example vendors)
│   └── tools/
│       ├── read.py            ← Tier 1 read-only tools (M1.5)
│       ├── write.py           ← Tier 1 write tools (M1.6)
│       ├── book.py            ← Tier 2 book_* tools (M2.1)
│       ├── vendor.py          ← Tier 2 vendor_* tools (M2.2)
│       ├── budget.py          ← Tier 2 budget_* tools — GnuCash native budget (M4.1)
│       ├── eco.py             ← Tier 2 eco_* tools — change order tracking (M4.2)
│       └── project.py         ← project-specific tools (Phase 6)
│
├── resources/                 ← Source content for Swift StaticResources.swift
│   ├── book_setup_guide.md    ← gnucash://book-setup-guide
│   ├── vendor_guide.md        ← gnucash://vendor-guide
│   ├── expected_chart.json    ← gnucash://expected-chart (MC-6 account structure)
│   ├── budget_guide.md        ← gnucash://budget-guide (Phase 4)
│   └── eco_guide.md           ← gnucash://eco-guide (Phase 4)
│
├── tests/                     ← Python pytest suite (runs inside container)
│   ├── conftest.py
│   ├── test_wal.py            ← T1.3.x
│   ├── test_session.py        ← T1.4.x
│   ├── test_read_tools.py     ← T1.5.x (dispatch-level, not HTTP)
│   ├── test_write_tools.py    ← T1.6.x
│   ├── test_book_tools.py     ← T2.1.x
│   ├── test_vendor_tools.py   ← T2.2.x
│   ├── test_crud_tools.py     ← T3.1.x (transaction correction)
│   ├── test_audit_log.py      ← T3.2.x
│   ├── test_budget_tools.py   ← T4.1.x (GnuCash budget CRUD)
│   ├── test_eco_tools.py      ← T4.2.x (ECO CRUD)
│   └── test_project_tools.py  ← T6.x
│
├── scripts/
│   ├── init_book.py           ← chart of accounts initialization (M1.2)
│   ├── create-book-volume.zsh ← sparsebundle one-time setup (M5.1)
│   ├── verify-backup.zsh      ← backup verification (M8.3)
│   └── spike/                 ← Phase 0 throwaway scripts (delete after P0)
│       ├── spike-a-bindings.sh
│       ├── spike-b-virtiofs.zsh
│       ├── spike-c-schema.py
│       ├── spike-d-readonly.zsh
│       ├── spike-e-snapshots.zsh
│       └── spike-f/           ← Spike F: minimal Swift proxy + Python container
│           ├── Sources/spike-f/main.swift
│           ├── Package.swift
│           └── container/server.py
│
└── bin/
    └── gnucash-browse         ← GUI read-only zsh wrapper (M5.3)
                                  (start/stop handled by gnucash-mcp Swift binary)
```

Inside the sparsebundle (at `/Volumes/GnuCash-Project/` when mounted):
```
project.gnucash
project.gnucash.20250401120000.gnucash   (GnuCash auto-backup)
project.gnucash.20250401120000.log
mcp-wal.jsonl                              (write-ahead log)
mcp.log                                    (tool call log, Phase 8)
```

---

## Appendix C — Dependency Versions

### Swift proxy (`Sources/gnucash-mcp/`)

| Component | Version | Source |
|---|---|---|
| macOS | 26 Tahoe | System |
| Swift toolchain | 6.2 (Xcode-bundled) | Xcode 26+ — must NOT use swift.org toolchain |
| `apple/container` | 0.10.0+ | github.com/apple/container |
| `apple/swift-argument-parser` | 1.5.0+ | github.com/apple/swift-argument-parser |
| `apple/swift-nio` | 2.x | github.com/apple/swift-nio |

**Swift toolchain note:** macOS 26 system frameworks (Virtualization.framework,
`ContainerAPIClient`) require the Xcode-bundled Swift 6.2 toolchain. Do not use
the swift.org standalone toolchain — it will fail to link against system frameworks.
This matches the requirement in `buck2-macos-local-reapi`.

### Python container (`Docker/Dockerfile`, `src/`)

| Component | Version | Source |
|---|---|---|
| Ubuntu base | 24.04 LTS (Noble) | Docker Hub `ubuntu:24.04` |
| GnuCash | 5.14 (`1:5.14-0build1`) | `ppa:gnucash/ppa` → `apt-get install python3-gnucash=1:5.14-0build1` |
| Python | 3.12 (Ubuntu default) | System |
| mcp SDK | latest stable at build time | PyPI via uv |

**GnuCash version note:** The PPA currently provides `1:5.14-0build1` for Noble
arm64. Pin this version for reproducible container builds:
```dockerfile
RUN apt-get install -y python3-gnucash=1:5.14-0build1
```
Update the pin when the PPA publishes a new version and Spike C has been re-run.

**Python dependency note:** The Python container does not depend on FastMCP or
uvicorn. The only MCP dependency is the base `mcp` SDK (for JSON-RPC type
definitions if desired, or omit entirely and use plain `json`). Pin the version
used at Phase 1 build time in `pyproject.toml`.

### macOS GUI

| Component | Version | Source |
|---|---|---|
| macOS GnuCash | 5.15 | gnucash.org .dmg |
| Apple Container runtime | 0.4.x+ | github.com/apple/container |

**GnuCash version policy:** When macOS GnuCash updates, check whether the PPA
has a matching version and update the container's pinned apt package. If the
minor version gap exceeds 1 (e.g. macOS at 5.17, container PPA at 5.14), treat
as blocking — rebuild container before next MCP write session.
The schema version guard (M8.2) enforces this automatically.
