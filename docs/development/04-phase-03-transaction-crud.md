# Phase 3 — Transaction CRUD and Audit Log

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

