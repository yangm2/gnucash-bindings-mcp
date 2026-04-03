# Appendix B — File Layout

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

