# Appendix D — Prior Art: ninetails-io/gnucash-mcp

A general-purpose GnuCash MCP server exists at
[github.com/ninetails-io/gnucash-mcp](https://github.com/ninetails-io/gnucash-mcp).
This appendix documents the relationship so architectural choices here are
deliberate, not accidental divergence.

## Fundamental differences

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
official bindings are just an `apt-get install` away — the installation
convenience gap that historically favoured piecash no longer exists.

**On XML vs SQLite:** XML auto-generates `.YYYYMMDDHHMMSS.gnucash` backups on every
save, is human-readable, can be diffed, and is the format macOS GnuCash 5.15 uses
natively. Converting to SQLite solely to satisfy piecash would lose these properties.

## Features shared with ninetails-io

The following capabilities exist in ninetails-io and are also present in this
project's plan — cross-referenced here for traceability:

- **Full transaction CRUD** — `update_transaction`, `void_transaction`,
  `delete_transaction`, `get_transaction` (Phase 3, M3.1)
- **Audit log as MCP tool** — `get_audit_log` exposing change history to Claude
  (Phase 3, M3.2)
- **Account CRUD** — `book_rename_account`, `book_move_account`,
  `book_delete_account` (Phase 2, M2.1)
- **GnuCash native budgets** — `budget_*` tools (Phase 4, M4.1) use GnuCash's
  native `GncBudget` objects, queried live by `get_budget_vs_actual`
- **Externally configurable tool catalog** — ninetails-io exposes a config file
  to trim the advertised tool list; this project achieves the same effect via
  MC-10 profile selection as a proxy CLI flag

## Features from ninetails-io not adopted

- **Scheduled transactions**: not applicable to a construction project with
  irregular billing cadence
- **Investment lots**: out of scope
- **Multi-currency**: out of scope

## Features unique to this project

- **Write-ahead log with crash replay**: uncommitted entries replayed on startup
  (MC-3, M1.3)
- **APFS snapshots**: point-in-time recovery before each write session
  (Spike E, M5.4)
- **Kernel-enforced read-only GUI**: sparsebundle `-readonly` mount prevents
  concurrent write corruption at the kernel level (Spike D, M5.3)
- **Construction-specific tools**: `get_budget_vs_actual`, `get_ap_aging`,
  `get_tranche_summary`, `project_runway_days` (Phase 6)
- **Engineering Change Order (ECO) tools**: `eco_*` tools track first-class
  change orders that adjust both budget and expense accounts (Phase 4, M4.2)
- **Vendor management as atomic unit**: `vendor_add`/`vendor_rename`/`vendor_update`/
  `vendor_delete` manage the AP + expense account pair together, with guards on
  deletion and explicit non-restatement semantics on category changes (Phase 2, M2.2)
- **Swift proxy architecture**: static tool catalog (no container for `tools/list`),
  per-request container pool, launchd integration, CoWork support via SDK bridge
  (MC-9, M5.2)
- **TOML-driven external budgets**: professional fee contracts and auxiliary
  budget items live in a per-book TOML file loaded by the Swift proxy (M6.1)
