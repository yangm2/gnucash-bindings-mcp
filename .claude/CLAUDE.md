# GnuCash MCP — Claude Code Instructions

## Settings file split

Project settings live in two files:

- `.claude/settings.json` — committed; portable permissions and plugin config
- `.claude/settings.local.json` — gitignored; machine-specific paths (`additionalDirectories`, path-containing `allow` rules)

When adding a new permission that contains an absolute path, put it in `settings.local.json`, not `settings.json`.

---

## Project overview

A GnuCash-backed MCP server for a construction project ledger. Claude is the
primary read-write interface; the macOS GnuCash GUI is read-only.

**Stack:**

| Layer | Tech |
|---|---|
| Ledger | GnuCash 5.x XML backend, `.sparsebundle` on APFS |
| MCP proxy | Swift binary (`gnucash-mcp`), owns MCP protocol + container lifecycle |
| Transport | stdio — Swift binary registered as `command` in `claude_desktop_config.json` |
| Container | Ubuntu 26.04, `python3-gnucash` (GnuCash 5.14) from universe |
| Python worker | One-shot stdin→stdout JSON-RPC dispatcher; no HTTP server |
| WAL | Append-only JSONL (`mcp-wal.jsonl`) for crash recovery |
| Backup | `FileManager.copyItem` APFS clone-copy (~51ms) before each write session |

**Two components under active development:**

1. `worker/` — Python package (`gnucash_mcp`); runs inside the Ubuntu container
2. `proxy/` — Swift binary (`gnucash-mcp`); runs natively on macOS (Phase 5+)

---

## Development workflow

All tasks run via `mise`. The container tool is Apple's `container` (not Docker).

```
mise build        # prod image: gnucash-mcp:latest
mise build-dev    # dev image: gnucash-mcp:dev (includes uv/ruff/pyright)
mise test         # pytest in dev container (depends build-dev)
mise lint         # ruff check + pyright in dev container
mise fmt          # ruff format in dev container
mise run          # one-shot dispatch, stdin→stdout, .test-data mounted
mise shell        # interactive shell, prod container
mise shell-dev    # interactive shell, dev container, source rw-mounted
mise init-book    # initialize GnuCash book in .test-data/
mise clean        # rm ephemeral test data
```

Test data lives in `.test-data/` (gitignored). Initialize with `mise init-book`
before running tests. Tests are always run inside the container — never natively.

---

## Python worker (`worker/`)

**Entry point:** `worker/gnucash_mcp/__main__.py` — reads one JSON-RPC request
from stdin, dispatches, writes one response to stdout, exits.

**Key modules:**
- `dispatch.py` — routes `tools/call` and `resources/read` to handlers
- `session.py` — GnuCash session lifecycle; `book_session()` context manager
- `tools/read.py` — all read tool implementations
- `tools/write.py` — all write tool implementations
- `wal.py` — write-ahead log; entries written before session opens, `committed_at` set after `session.end()`

**Session rules (MC-2):**
- Sessions are short-lived: open → write → `session.save()` → `session.end()` per tool call
- `session.save()` flushes to disk; `session.end()` releases the `.LCK` file
- Always call `session.save()` immediately after opening a new book (before mutations)

**WAL rules (MC-3):**
- Write WAL entry before opening GnuCash session
- Set `committed_at` only after `session.end()` returns
- On startup, replay entries missing `committed_at`

---

## Architecture constraints

- The container has no HTTP server. Do not add uvicorn, FastMCP, or any HTTP layer.
- Tool schemas live in the Swift proxy (compiled in), not in Python.
- The Python dispatcher only needs to implement the tool logic — argument parsing
  is done by the MCP layer before reaching Python.
- `GNUCASH_BOOK_PATH` is injected as an env var by the Swift proxy; it never
  appears in MCP protocol messages or Claude's context.

---

## Chart of accounts (MC-6)

- Each vendor has their own AP account: `Liabilities:AP — {vendor}`
- Trade vendors (electrical, framing, etc.) share a single expense account per trade
- Professional vendors (architects, engineers) get dedicated expense accounts
- Permits are direct payments to `Expenses:Permits and Fees`; jurisdictions are never vendors
- `Expenses:Construction:*` children are created from the GC's budget line items
- `Expenses:Change Orders:*` mirrors Construction structure for ECO tracking

Key design docs: `docs/development/00-overview.md` (MC-6 section)

---

## Known active constraints

- GnuCash Python bindings (`python3-gnucash`) are only available inside the
  Ubuntu container — never run GnuCash binding code natively on macOS.
- GnuCash XML backend creates `.YYYYMMDDHHMMSS.gnucash` backup on each save;
  two saves in the same second will silently no-op. `session.py` handles this
  with `_purge_same_second_backup()`.
- Tests use fixed historical dates, not dynamic offsets from today.
