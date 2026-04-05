# GnuCash MCP Server — Development Docs

Full documentation is split into focused files under [docs/development/](docs/development/).

## Overview & Architecture

- [00-overview.md](docs/development/00-overview.md) — Stack summary, Known Unknowns (KU-1–KU-12), and all Microarchitectural Choices (MC-1–MC-10)

## Phase 0 — Foundations

- [01-phase-00-spikes.md](docs/development/01-phase-00-spikes.md) — Spikes A–G and Phase 0 exit criteria

## Implementation Phases

- [02-phase-01-core-ledger.md](docs/development/02-phase-01-core-ledger.md) — Phase 1: Core Ledger and MCP Skeleton (M1.1–M1.6)
- [03-phase-02-book-management.md](docs/development/03-phase-02-book-management.md) — Phase 2: Book Management and Vendor Tools (M2.1–M2.3)
- [04-phase-03-transaction-crud.md](docs/development/04-phase-03-transaction-crud.md) — Phase 3: Transaction CRUD and Audit Log (M3.1–M3.2)
- [05-phase-04-budget-eco.md](docs/development/05-phase-04-budget-eco.md) — Phase 4: Budget and ECO Tools (M4.1–M4.3)
- [06-phase-05-infrastructure.md](docs/development/06-phase-05-infrastructure.md) — Phase 5: Sparsebundle, Wrappers, and Snapshots (M5.1–M5.4)
- [07-phase-06-project-tools.md](docs/development/07-phase-06-project-tools.md) — Phase 6: Project-Specific MCP Tools (M6.1–M6.4)
- [08-phase-07-reconciliation.md](docs/development/08-phase-07-reconciliation.md) — Phase 7: Reconciliation and Reporting (M7.1–M7.3)
- [09-phase-08-hardening.md](docs/development/09-phase-08-hardening.md) — Phase 8: Hardening and Claude Desktop Integration (M8.1–M8.5)

## Appendices

- [10-appendix-a-testing.md](docs/development/10-appendix-a-testing.md) — Test execution: naming, fixtures, unit vs integration, smoke test curl commands
- [11-appendix-b-file-layout.md](docs/development/11-appendix-b-file-layout.md) — Repository and sparsebundle file layout
- [12-appendix-c-dependencies.md](docs/development/12-appendix-c-dependencies.md) — Pinned dependency versions (Swift, Python, GnuCash)
- [13-appendix-d-prior-art.md](docs/development/13-appendix-d-prior-art.md) — Comparison with ninetails-io/gnucash-mcp
- [14-appendix-e-model-options.md](docs/development/14-appendix-e-model-options.md) — Model options (Claude, gpt-oss:20b/deepagents, AFM) and hybrid coordinator architecture
