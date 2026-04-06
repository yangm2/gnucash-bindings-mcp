# Appendix B — File Layout

```
gnucash-mcp/
├── DEVELOPMENT.md             ← index; full docs in docs/development/
├── SPIKE_RESULTS.md           ← Phase 0 outcomes (fill in as spikes run)
├── TEST_RESULTS.md            ← manual test log
├── README.md                  ← setup and daily-use guide (Phase 5+)
│
├── docs/
│   └── development/           ← split development docs
│       ├── 00-overview.md     ← stack summary, KU table, MC-1 – MC-10
│       ├── 01-phase-00-spikes.md
│       ├── 02-phase-01-core-ledger.md
│       ├── 03-phase-02-book-management.md
│       ├── 04-phase-03-transaction-crud.md
│       ├── 05-phase-04-budget-eco.md
│       ├── 06-phase-05-infrastructure.md
│       ├── 07-phase-06-project-tools.md
│       ├── 08-phase-07-reconciliation.md
│       ├── 09-phase-08-hardening.md
│       ├── 10-appendix-a-testing.md
│       ├── 11-appendix-b-file-layout.md  ← this file
│       ├── 12-appendix-c-dependencies.md
│       ├── 13-appendix-d-prior-art.md
│       ├── 14-appendix-e-model-options.md
│       └── 15-phase-09-instrumentation.md
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
│       ├── StaticResources.swift ← session-context, book-setup-guide, vendor-guide,
│       │                           expected-chart, budget-guide, eco-guide (no container)
│       ├── ContainerPool.swift ← size-1 TTL pool; sleep/wake recovery (KU-11)
│       ├── ContainerDispatch.swift ← ContainerAPIClient stdin/stdout round-trip
│       ├── VolumeMount.swift  ← hdiutil attach/detach via Process
│       ├── Backup.swift       ← cp -c pre-session clone-copy backup (Spike E: tmutil not viable)
│       ├── Metrics.swift      ← CallRecord + SessionSummary; writes metrics.jsonl (M9.1)
│       ├── MetricsCommand.swift ← gnucash-mcp metrics subcommand + --since/--json flags
│       └── JSONRPCTypes.swift ← Codable MCP message types
│
├── Tests/
│   └── gnucash-mcpTests/      ← Swift unit tests for proxy logic
│       ├── ToolCatalogTests.swift
│       ├── ContainerPoolTests.swift
│       └── JSONRPCTests.swift
│
├── Docker/
│   └── Dockerfile             ← Ubuntu 26.04 + python3-gnucash from universe (no PPA)
│
├── pyproject.toml             ← uv-managed Python project (container image contents)
├── src/
│   ├── __main__.py            ← one-shot stdin→stdout dispatcher entry point (M1.5)
│   ├── dispatch.py            ← routes JSON-RPC method+name to handler (M1.5)
│   ├── session.py             ← GnuCash session manager (MC-2)
│   ├── wal.py                 ← write-ahead log (MC-3)
│   ├── instrumentation.py     ← timing context manager; writes dispatch-timing.jsonl (M9.2)
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
│   ├── session_context.json   ← gnucash://session-context (tool groups, conventions, resource index)
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
│   ├── analyze-sessions.py    ← hybrid readiness report from metrics.jsonl (M9.4)
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
mcp.log                                    (tool call narrative log, Phase 8)
dispatch-timing.jsonl                      (per-phase timing breakdown, Phase 9)
```

In `~/.local/share/gnucash-mcp/` (macOS host, outside sparsebundle):
```
proxy.log           (proxy-level narrative log, M8.1)
metrics.jsonl       (per-call records: latency, cold-start, response size, M9.1)
sessions.jsonl      (per-session summaries + hybrid_candidate flag, M9.3)
HYBRID_READINESS.md (analysis report from analyze-sessions.py, M9.4)
```
