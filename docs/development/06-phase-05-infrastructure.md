# Phase 5 — Infrastructure: Sparsebundle, Wrappers, and Snapshots

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

### M5.4 — Pre-session backup (cp -c clone-copy)

**Background (Spike E result):** `tmutil localsnapshot` creates snapshots on the
sparsebundle volume but `diskutil apfs listSnapshots` cannot enumerate them on
non-boot volumes — they are not mountable or restorable. Use `cp -c` APFS
clone-copy instead: completes in ~51ms, produces a fully independent `.gnucash`
file that can be opened directly in GnuCash for recovery.

**Deliverables:**
- `Backup.swift` in the Swift proxy — `BackupManager` struct:
  - `createBackup(bookURL: URL) throws -> URL` — `cp -c` clone with timestamp suffix
  - `pruneBackups(bookURL: URL, keepCount: Int) throws` — deletes oldest `.pre-*.gnucash` files
- Pre-session backup integrated into Swift proxy `start` subcommand (MC-9):
  runs `createBackup` before first container dispatch of the session

**Naming:** `{book}.pre-YYYYMMDD-HHMMSS.gnucash` alongside the live book file.

**Tests:**
```
T5.4.1  createBackup produces a .pre-YYYYMMDD-HHMMSS.gnucash file alongside book
T5.4.2  backup file content matches book at time of copy (hash comparison)
T5.4.3  createBackup completes in < 500ms on a book file of any size (APFS CoW)
T5.4.4  pruneBackups(keepCount: 3) leaves exactly 3 .pre-*.gnucash files;
        the live book and other files are unaffected
T5.4.5  Restore drill (manual, document in TEST_RESULTS.md):
        Post a bad transaction → proxy creates backup → post another transaction →
        open backup file directly in GnuCash → verify bad transaction absent
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

