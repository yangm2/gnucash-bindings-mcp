# Phase 1 — Core Ledger and MCP Skeleton

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

