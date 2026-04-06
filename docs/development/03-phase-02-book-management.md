# Phase 2 — Book Management and Vendor Tools

**Goal:** Claude can set up and maintain the chart of accounts and add new
vendors/subcontractors as they are hired. These tools are used infrequently
(once at setup, then as new subs are brought on) but must be reliable.
Resource-based lazy context pattern validated in practice.

**Prerequisites:** Phase 1 complete. MC-8 tool architecture confirmed working.

### M2.1 — Book setup tools

**Deliverables (`src/tools/book.py`):**

```python
@app.tool()
def book_add_account(
    name: str,
    parent_path: str,
    account_type: str,   # ASSET|LIABILITY|EQUITY|INCOME|EXPENSE
    commodity: str = "USD",
) -> dict:
    """Add account to chart of accounts. Read gnucash://book-setup-guide
    for account_type values and naming conventions first."""

@app.tool()
def book_get_account_tree(parent_path: str = "") -> list[dict]:
    """Return account tree as nested list. Read gnucash://expected-chart
    to compare against expected structure."""

@app.tool()
def book_verify_structure() -> dict:
    """Compare live chart of accounts against gnucash://expected-chart.
    Returns {missing: [...], unexpected: [...], ok: bool}."""

@app.tool()
def book_set_opening_balance(
    account_path: str,
    amount: str,
    date: str,
) -> dict:
    """Post an opening balance transaction for an account.
    Read gnucash://book-setup-guide before calling."""

@app.tool()
def book_rename_account(
    account_path: str,
    new_name: str,
) -> dict:
    """Rename an account leaf (not full path). Does not affect existing
    transactions — GnuCash tracks accounts by GUID, not name."""

@app.tool()
def book_move_account(
    account_path: str,
    new_parent_path: str,
) -> dict:
    """Move an account to a new parent in the hierarchy. Use when
    restructuring the chart of accounts. Existing transactions unaffected."""

@app.tool()
def book_delete_account(
    account_path: str,
    require_zero_balance: bool = True,
) -> dict:
    """Delete an account. Fails if account has transactions unless
    require_zero_balance=False is explicitly passed. Use with caution:
    deletion is permanent and cannot be undone via MCP."""
```

**Tests:**
```
T2.1.1  book_add_account creates account at correct path in hierarchy
T2.1.2  book_add_account with non-existent parent_path raises AccountNotFoundError
T2.1.3  book_add_account with invalid account_type raises ValueError
T2.1.4  book_add_account is idempotent: running with same args twice does not duplicate
T2.1.5  book_get_account_tree("Liabilities") returns all AP accounts
T2.1.6  book_verify_structure returns ok:true on a correctly-initialized book
T2.1.7  book_verify_structure returns missing accounts after one is removed (test fixture)
T2.1.8  book_set_opening_balance creates a balanced transaction with equity offset
T2.1.9  book_rename_account updates account name; existing transactions still resolve
T2.1.10 book_move_account moves account to new parent; full path reflects new location
T2.1.11 book_delete_account fails on account with transactions when require_zero_balance=True
T2.1.12 book_delete_account succeeds on empty account; account absent from tree after
T2.1.13 Resource gnucash://book-setup-guide is non-empty and contains "account_type"
T2.1.14 Claude fetches gnucash://book-setup-guide before calling book_add_account
         (manual — observe in CoWork/Desktop tool log; record in TEST_RESULTS.md)
```

---

### M2.2 — Vendor management tools

**Deliverables (`src/tools/vendor.py`):**

```python
@app.tool()
def vendor_add(
    name: str,
    trade: str | None = None,
    expense_category: str | None = None,
) -> dict:
    """Add a new vendor. Exactly one of `trade` or `expense_category` must be provided.

    trade: full account path of an existing trade expense account. The vendor's
    invoices will be coded to this shared account. No new expense account is created.
    Use for construction subcontractors where the trade account already exists.
    Example: vendor_add('Pacific Crest Electrical', trade='Construction:Electrical')

    expense_category: creates a new dedicated expense account for this vendor.
    Use for professional fee vendors with individually-named contracts.
    Example: vendor_add('Acme Architecture', expense_category='Architecture')

    Read gnucash://vendor-guide for valid trade paths and expense_category values."""

@app.tool()
def vendor_list() -> list[dict]:
    """List all vendors with type (trade|professional), AP account path,
    expense account or trade path, current balance, and total paid."""

@app.tool()
def vendor_get_details(name: str) -> dict:
    """Return vendor type, AP account path, expense account or trade path,
    current balance, and transaction history for a named vendor."""

@app.tool()
def vendor_rename(old_name: str, new_name: str) -> dict:
    """Rename a vendor. For professional vendors, updates both AP and expense
    account names atomically. For trade vendors, updates AP account name only
    (the shared trade expense account is unaffected).
    Does not affect existing transactions (accounts tracked by GUID)."""

@app.tool()
def vendor_update(
    name: str,
    trade: str | None = None,
    expense_category: str | None = None,
) -> dict:
    """Change the expense coding for a vendor. Exactly one of `trade` or
    `expense_category` must be provided.

    For professional vendors: moves their dedicated expense account to a new
    category. Does NOT restate historical transactions — existing splits stay
    on the old account path; only future invoices use the new path.

    For trade vendors: reassigns to a different trade expense account. The old
    trade account is unaffected. Useful when a vendor's scope changed mid-project.

    Read gnucash://vendor-guide for valid values."""

@app.tool()
def vendor_delete(
    name: str,
    confirm: bool = False,
) -> dict:
    """Delete a vendor. Requires confirm=True.
    For professional vendors: removes both AP and dedicated expense accounts.
    For trade vendors: removes only the AP account (shared trade account unaffected).
    Fails if the AP account has any transactions — use vendor_get_details to check
    first. For vendors with history, leave in place: zero-balance AP accounts are
    invisible in AP aging reports."""
```

**Account creation by vendor type:**

| Scenario | Accounts created | Accounts reused |
|---|---|---|
| Trade vendor (`trade=`) | `Liabilities:AP — {name}` | Existing `Expenses:{trade}` |
| Professional vendor (`expense_category=`) | `Liabilities:AP — {name}`, `Expenses:{category} — {name}` | — |

**Valid `expense_category` values** (in `gnucash://vendor-guide`):

| expense_category | Expense account created |
|---|---|
| `Architecture` | `Expenses:Architecture — {name}` |
| `Structural` | `Expenses:Structural Engineering — {name}` |
| `MEP` | `Expenses:MEP Consulting — {name}` |
| `HVAC` | `Expenses:HVAC Engineering — {name}` |

**Valid `trade` paths** are any existing `Construction:*` child account. The
`gnucash://vendor-guide` resource lists the current trade accounts by querying
the live book. Passing a non-existent path raises `AccountNotFoundError`.

**Design note on `vendor_update`:** For professional vendors, moving their expense
account changes where *future* invoices are coded but does not restate *historical*
transactions. This is correct accounting behaviour. If historical restatement is
needed, void and repost the relevant transactions.

**Design note on `vendor_delete`:** The failure guard on existing AP transactions
is a hard guard — not overridable even with `confirm=True`. A vendor paid once has
AP history relevant to year-end reporting. The recommended path for inactive vendors
is to leave their AP account in place.

**Tests:**
```
T2.2.1  vendor_add("Pacific Crest Electrical", trade="Construction:Electrical") creates
        only Liabilities:AP — Pacific Crest Electrical; no new expense account created
T2.2.2  vendor_add("Acme Architecture", expense_category="Architecture") creates:
        Liabilities:AP — Acme Architecture
        Expenses:Architecture — Acme Architecture
T2.2.3  vendor_add with both trade and expense_category raises ValueError
T2.2.4  vendor_add with neither trade nor expense_category raises ValueError
T2.2.5  vendor_add with trade pointing to non-existent account raises AccountNotFoundError
T2.2.6  vendor_add is idempotent: adding same vendor twice does not duplicate accounts
T2.2.7  vendor_list includes newly added vendor with type, correct path, $0.00 balance
T2.2.8  vendor_list shows trade vendor with trade path, professional with expense path
T2.2.9  After receive_invoice for new vendor, vendor_list shows correct AP balance
T2.2.10 vendor_rename on professional vendor updates both AP and expense account names
T2.2.11 vendor_rename on trade vendor updates only AP account name; trade account unchanged
T2.2.12 Existing transactions for renamed vendor remain valid (account GUID unchanged)
T2.2.13 vendor_get_details returns type, correct paths, and $0 balance for new vendor
T2.2.14 vendor_update on professional vendor moves expense account to new category path
T2.2.15 vendor_update on professional vendor: transactions before update still on old path;
        new invoice uses new path (no historical restatement)
T2.2.16 vendor_update on trade vendor reassigns to different trade account
T2.2.17 vendor_update with invalid expense_category raises ValueError
T2.2.18 vendor_update with non-existent trade path raises AccountNotFoundError
T2.2.19 vendor_delete without confirm=True raises RequiresConfirmationError
T2.2.20 vendor_delete on trade vendor with confirm=True removes only AP account;
        trade expense account still present with its balance intact
T2.2.21 vendor_delete on professional vendor with confirm=True removes both AP and
        expense accounts
T2.2.22 vendor_delete on vendor with AP transaction history raises VendorHasHistoryError
        even with confirm=True
T2.2.23 Resource gnucash://vendor-guide lists current trade accounts from live book
T2.2.24 Resource gnucash://vendors returns updated list after vendor_add (live query)
T2.2.25 End-to-end trade: add trade vendor → receive invoice to trade account →
        pay invoice → AP clears to $0; trade account shows spend
T2.2.26 End-to-end replacement: add trade vendor A → invoice → pay → add trade vendor B
        (same trade) → invoice → pay; Construction:Electrical shows combined spend
```

---

### M2.3 — Resource completeness and lazy-load validation

**Deliverables:**
- All static resources populated with production content (not placeholder text)
- `gnucash://expected-chart` reflects full MC-6 account structure as a JSON dict
- `gnucash://budget-guide` and `gnucash://eco-guide` added in Phase 4 (M4.3)
- Manual test of the lazy-load pattern: confirm resources are NOT loaded at
  session start, ARE loaded when Claude decides to use an administrative tool

**Tests:**
```
T2.3.1  gnucash://resources returns dict with URIs for all static resources
         (book-setup-guide, vendor-guide, expected-chart, budget-guide, eco-guide)
T2.3.2  gnucash://expected-chart contains all accounts from MC-6 (automated check
         against the same constant used by book_verify_structure)
T2.3.3  Token audit (manual): start fresh Claude session, observe tool call log.
         Resources should NOT appear in context at start.
         Call vendor_add → gnucash://vendor-guide SHOULD appear in context.
         Document token counts in TEST_RESULTS.md.
T2.3.4  book_verify_structure on a correctly-initialized book returns ok:true
         (uses gnucash://expected-chart internally, not via Claude context)
```

---

### Phase 2 exit criteria

- `vendor_add` validated end-to-end: add sub → invoice → pay → AP clears
- `vendor_update` tested: expense category move verified; historical transactions unaffected
- `vendor_delete` friction test: fails without `confirm=True`; fails on vendor with history
- `book_verify_structure` passes cleanly on the production book
- Account CRUD (`book_rename_account`, `book_move_account`, `book_delete_account`)
  tested against fixture book
- Lazy-load pattern confirmed: resource tokens visible in Claude session only
  when an administrative tool is actively being used (T2.3.3 documented)
- All new vendor and book tools visible in Claude Desktop and CoWork tool list

---

