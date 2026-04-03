# Appendix D — Prior Art: ninetails-io/gnucash-mcp

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

