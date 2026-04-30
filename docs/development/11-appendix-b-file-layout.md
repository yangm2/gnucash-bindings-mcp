# Appendix B — File Layout

```
gnucash-bindings-mcp/
├── .mise.toml                 ← root task orchestrator (mise build, mise run, etc.)
├── .gitignore
├── .test-data/                ← ephemeral; gitignored; GnuCash book + WAL used during dev
├── DEVELOPMENT.md             ← index; full docs in docs/development/
├── TEST_RESULTS.md            ← manual test log
│
├── docs/
│   └── development/
│       ├── 00-overview.md
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
├── spikes/                    ← Phase 0 artifacts (historical reference, not built in CI)
│   ├── docker/
│   │   ├── Dockerfile.spike-a ← GnuCash bindings validation
│   │   ├── Dockerfile.spike-g ← Ubuntu 26.04 base evaluation
│   │   └── Dockerfile.spike-h ← PDF extraction
│   ├── scripts/
│   │   ├── spike-a.py         ← GnuCash API + lock detection
│   │   ├── spike-b.sh         ← VirtioFS read/write
│   │   ├── spike-c.py         ← schema compatibility
│   │   ├── spike-d.sh         ← read-only mount enforcement
│   │   ├── spike-e.sh         ← APFS cp -c backup timing
│   │   └── spike-h.py         ← PDF extraction (pdfplumber)
│   └── spike-f/               ← Spike F: Swift MCP stdio proxy (intact SwiftPM package)
│       ├── Package.swift
│       ├── Package.resolved
│       ├── Sources/spike-f/main.swift
│       ├── Dockerfile.echo
│       └── run.sh
│
├── bin/                       ← macOS host scripts (not built into container)
│   ├── create-book-volume.zsh ← one-time sparsebundle setup (M5.1)
│   ├── gnucash-browse         ← read-only GUI wrapper (M5.3)
│   └── verify-backup.zsh      ← backup verification (M8.3)
│
├── proxy/                     ← Swift MCP proxy (Phase 5, M5.2)
│   ├── Package.swift          ← SwiftPM manifest (stub until M5.2)
│   ├── Package.resolved
│   ├── Sources/
│   │   └── gnucash-mcp/
│   │       ├── main.swift            ← @main, ArgumentParser entrypoint
│   │       ├── CLI.swift             ← start/stop/status/install/snapshot subcommands
│   │       ├── MCPStdioTransport.swift ← reads stdin, writes stdout (stdio MCP transport, MC-4)
│   │       ├── MCPHandler.swift      ← routes initialize/tools/resources
│   │       ├── ToolCatalog.swift     ← compiled tool schemas, Tier 1 + Tier 2
│   │       ├── StaticResources.swift ← session-context, book-setup-guide, etc.
│   │       ├── ContainerPool.swift   ← size-1 TTL pool; sleep/wake recovery
│   │       ├── ContainerDispatch.swift ← stdin/stdout round-trip to worker
│   │       ├── VolumeMount.swift     ← hdiutil attach/detach
│   │       ├── Backup.swift          ← FileManager.copyItem pre-session APFS clone-copy
│   │       ├── Metrics.swift         ← CallRecord + SessionSummary (M9.1)
│   │       ├── MetricsCommand.swift  ← gnucash-mcp metrics subcommand
│   │       └── JSONRPCTypes.swift    ← Codable MCP message types
│   └── Tests/
│       └── gnucash-mcpTests/
│           ├── ToolCatalogTests.swift
│           ├── ContainerPoolTests.swift
│           └── JSONRPCTests.swift
│
└── worker/                    ← Python container (self-contained build context)
    ├── Dockerfile             ← multi-stage: base / prod / dev
    │                             build: container build -t gnucash-mcp:latest worker/
    ├── pyproject.toml         ← Python package metadata + dev deps (ruff, ty, pytest)
    │
    ├── gnucash_mcp/           ← Python package (copied into container by Dockerfile)
    │   ├── __init__.py
    │   ├── __main__.py        ← one-shot stdin→stdout dispatcher entry point (M1.5)
    │   ├── dispatch.py        ← routes JSON-RPC method+name to handler (M1.5)
    │   ├── session.py         ← GnuCash session manager; get_account; gnc_decimal (M1.4)
    │   ├── wal.py             ← write-ahead log; append/mark_committed/replay (M1.3)
    │   ├── instrumentation.py ← timing context manager; dispatch-timing.jsonl (M9.2)
    │   └── tools/
    │       ├── __init__.py
    │       ├── read.py        ← Tier 1 read tools (M1.5)
    │       ├── write.py       ← Tier 1 write tools (M1.6)
    │       ├── book.py        ← Tier 2 book_* tools (M2.1)
    │       ├── vendor.py      ← Tier 2 vendor_* tools (M2.2)
    │       ├── budget.py      ← Tier 2 budget_* tools (M4.1)
    │       ├── eco.py         ← Tier 2 eco_* tools (M4.2)
    │       └── project.py     ← project-specific tools (Phase 6)
    │
    ├── scripts/               ← Python scripts (copied into container by Dockerfile)
    │   ├── init_book.py           ← chart of accounts initialization (M1.2)
    │   └── analyze-sessions.py    ← hybrid readiness report from metrics.jsonl (M9.4)
    │
    └── tests/                 ← pytest suite (runs inside container via mise test)
        ├── conftest.py
        ├── test_wal.py            ← T1.3.x
        ├── test_session.py        ← T1.4.x
        ├── test_read_tools.py     ← T1.5.x
        ├── test_write_tools.py    ← T1.6.x
        ├── test_book_tools.py     ← T2.1.x
        ├── test_vendor_tools.py   ← T2.2.x
        ├── test_crud_tools.py     ← T3.1.x
        ├── test_audit_log.py      ← T3.2.x
        ├── test_budget_tools.py   ← T4.1.x
        ├── test_eco_tools.py      ← T4.2.x
        └── test_project_tools.py  ← T6.x
```

Inside the sparsebundle (at `/Volumes/GnuCash-Project/` when mounted):
```
project.gnucash
project.gnucash.20250401120000.gnucash   (GnuCash auto-backup)
project.gnucash.20250401120000.log
project.gnucash.pre-20250401-120000.gnucash  (APFS clone-copy pre-session backup, M5.4)
project.wal.jsonl                            (write-ahead log)
dispatch-timing.jsonl                        (per-call timing, Phase 9)
```

In `~/.local/share/gnucash-mcp/` (macOS host, outside sparsebundle):
```
proxy.log           (proxy-level narrative log, M8.1)
metrics.jsonl       (per-call records: latency, cold-start, response size, M9.1)
sessions.jsonl      (per-session summaries + hybrid_candidate flag, M9.3)
HYBRID_READINESS.md (analysis report from analyze-sessions.py, M9.4)
```
