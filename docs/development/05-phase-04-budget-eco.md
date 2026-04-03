# Phase 4 — Budget and ECO Tools

## Phase 4 — Budget and ECO Tools

**Goal:** Replace the hardcoded ROM constants approach with live GnuCash native
budgets. The GC's pre-construction pricing enters the book as a real GnuCash
budget object; `get_budget_vs_actual()` queries it rather than Python constants.
Engineering Change Orders (ECOs) are tracked as first-class ledger objects
that adjust both the budget and the expense accounts.

**Prerequisites:** Phase 2 complete (account/vendor CRUD needed to set up
Construction expense accounts before budget amounts can be entered).

### M4.1 — Budget CRUD tools

**Background:** GnuCash budgets are stored as `GncBudget` objects in the book.
Each budget has a name, a recurrence rule (period type × multiplier × start date),
and a number of periods. Budget amounts are per-account per-period values.

For a construction project the recommended structure is:
- **One period** covering the full construction contract duration
- Budget amounts set on each `Expenses:Construction:*` account matching the GC's
  line items
- A second budget period (or separate budget) can be added for the draw schedule
  once the GC provides one

**Deliverables (`src/tools/budget.py`):**

```python
@app.tool()
def budget_create(
    name: str,
    description: str = "",
    num_periods: int = 1,
    period_start: str,        # YYYY-MM-DD
    period_months: int = 12,  # months per period; 0 = entire project as one period
) -> dict:
    """Create a new GnuCash budget. Call once when GC delivers pre-construction
    pricing. Use num_periods=1, period_months=0 for a single total-project budget.
    Read gnucash://budget-guide before calling."""

@app.tool()
def budget_list() -> list[dict]:
    """List all budgets in the book: name, description, num_periods, start date."""

@app.tool()
def budget_get(name: str) -> dict:
    """Return full budget: all accounts with budgeted amounts per period,
    actual committed/paid amounts, and variance. Reads live ledger transactions."""

@app.tool()
def budget_set_amount(
    budget_name: str,
    account_path: str,
    amount: str,
    period: int = 0,
) -> dict:
    """Set budget amount for an account in a period (0-indexed).
    Call for each line item in the GC's budget spreadsheet.
    Creates the account if it does not exist.
    Read gnucash://budget-guide for the workflow."""

@app.tool()
def budget_update(
    name: str,
    new_name: str | None = None,
    new_description: str | None = None,
) -> dict:
    """Update budget name or description. Does not change amounts or periods.
    To revise amounts, call budget_set_amount on each changed line."""

@app.tool()
def budget_delete(
    name: str,
    confirm: bool = False,
) -> dict:
    """Delete a budget. Requires confirm=True. Does not affect transactions.
    Use when replacing with a revised GC budget after value engineering."""
```

**Key implementation note — `budget_set_amount` creates accounts:**
When entering a GC budget for the first time, many `Expenses:Construction:*`
accounts won't exist yet. `budget_set_amount` calls `book_add_account` internally
if the account path doesn't exist, using `EXPENSE` type and `USD` commodity.
This means the workflow to enter a GC budget is simply:

```
budget_create("GC Pre-Construction", period_start="2025-09-01", num_periods=1)
budget_set_amount("GC Pre-Construction", "Expenses:Construction:Demo", "8600.00")
budget_set_amount("GC Pre-Construction", "Expenses:Construction:Framing", "32000.00")
budget_set_amount("GC Pre-Construction", "Expenses:Construction:Electrical", "45000.00")
... (one call per GC line item)
```

**`budget_get` output structure:**
```json
{
  "name": "GC Pre-Construction",
  "total_budgeted": "462000.00",
  "total_committed": "127450.00",
  "total_paid": "89200.00",
  "total_variance": "334550.00",
  "accounts": [
    {
      "account": "Expenses:Construction:Electrical",
      "period": 0,
      "budgeted": "45000.00",
      "committed": "22500.00",
      "paid": "22500.00",
      "variance": "22500.00",
      "pct_committed": 50.0
    }
  ]
}
```

**Note:** `committed` = sum of AP invoices posted to the account (regardless of
payment status). `paid` = sum of payments from Project Checking. `variance` =
`budgeted - committed` (positive = under budget). This matches standard
construction project accounting practice.

**Tests:**
```
T4.1.1  budget_create creates GncBudget object in book with correct num_periods
T4.1.2  budget_list returns newly created budget
T4.1.3  budget_set_amount sets amount on existing account
T4.1.4  budget_set_amount creates account and sets amount when account doesn't exist
T4.1.5  budget_get returns all accounts with correct budgeted amounts
T4.1.6  budget_get shows committed = 0, paid = 0, variance = budget before any invoices
T4.1.7  After receive_invoice to a budgeted account: budget_get shows correct committed
T4.1.8  After pay_invoice: budget_get shows correct paid; committed unchanged
T4.1.9  budget_update renames budget; amounts unchanged
T4.1.10 budget_delete without confirm=True raises RequiresConfirmationError
T4.1.11 budget_delete with confirm=True removes budget; transactions unaffected
T4.1.12 Full workflow: create budget → set 5 line items → receive 2 invoices →
         budget_get shows correct committed/paid/variance for each line
```

---

### M4.2 — Engineering Change Order (ECO) tools

**Background:** An ECO (Engineering Change Order, also called CO — Change Order)
is a formal modification to the GC's contracted scope and/or price. Each ECO has:
- A number and description
- A direction: **additive** (owner-requested scope addition) or **deductive**
  (scope reduction, credit back to owner)
- A status: **pending** (submitted, awaiting approval), **approved** (signed),
  **void** (rejected or cancelled)
- A cost impact: amount and which budget line(s) it affects
- An optional schedule impact (days added or removed)

ECOs are tracked in the book using two mechanisms:
1. **KVP slots** on a dedicated `Liabilities:Change Orders Pending` account
   (or as book-level metadata) to store the ECO registry
2. **Expense transactions** posted to `Expenses:Change Orders:*` accounts when
   approved, so the impact appears in the ledger

This keeps the original contract budget clean while making ECO costs visible
independently. `get_budget_vs_actual()` can then report separately on:
- Original contract spend vs original budget
- ECO spend vs approved ECO total
- Combined total vs combined budget

**Deliverables (`src/tools/eco.py`):**

```python
@app.tool()
def eco_create(
    number: str,             # e.g. "CO-001"
    description: str,
    direction: str,          # "additive" | "deductive"
    amount: str,             # decimal, always positive
    budget_account: str,     # which Construction account this affects
    schedule_days: int = 0,  # schedule impact; 0 = no schedule impact
    notes: str = "",
) -> dict:
    """Create a new pending ECO. Does not affect account balances until approved.
    Read gnucash://eco-guide for direction conventions and numbering."""

@app.tool()
def eco_list(
    status: str | None = None,  # "pending" | "approved" | "void" | None = all
) -> list[dict]:
    """List ECOs with number, description, direction, amount, status.
    status=None returns all. Use status='pending' to review open items."""

@app.tool()
def eco_get(number: str) -> dict:
    """Return full ECO detail: all fields plus any transactions posted on approval."""

@app.tool()
def eco_approve(
    number: str,
    date: str,           # YYYY-MM-DD — date GC/owner signed
    invoice_ref: str = "",  # GC invoice reference if CO is billed separately
) -> dict:
    """Approve a pending ECO. Posts a transaction to Expenses:Change Orders:*
    (additive) or reversal transaction (deductive). Updates ECO status to approved.
    Increases or decreases the budget on the affected account by the ECO amount."""

@app.tool()
def eco_void(
    number: str,
    reason: str,
) -> dict:
    """Void a pending or approved ECO. If approved, reverses the posted transaction.
    Records the void reason. Does not delete — maintains audit trail."""
```

**Account structure for ECOs:**
```
Expenses:Change Orders          ← parent, mirrors Construction hierarchy
  Change Orders:Demo
  Change Orders:Electrical
  Change Orders:Plumbing
  ... (one per construction line that has a CO)
  Change Orders:New Scope       ← for COs adding scope not in original contract
```

**`eco_approve` accounting entries:**

Additive CO (owner pays more):
```
DR Expenses:Change Orders:Electrical    $5,000
  CR Liabilities:AP — [GC name]         $5,000
```
The budget on `Expenses:Construction:Electrical` is increased by $5,000.

Deductive CO (credit back to owner):
```
DR Liabilities:AP — [GC name]          $2,000
  CR Expenses:Change Orders:Electrical  $2,000
```
The budget on `Expenses:Construction:Electrical` is decreased by $2,000.

**ECO storage:** ECO metadata (number, description, status, direction, notes)
is stored as book KVP slots under a `mcp/ecos/{number}` key path. The approved
transaction GUID is stored alongside so `eco_get` can retrieve full detail.
This is a lightweight alternative to creating a separate GnuCash table, and
the KVP data persists in the XML book file.

**Tests:**
```
T4.2.1  eco_create stores ECO with status=pending; no transactions posted
T4.2.2  eco_list returns newly created ECO with correct fields
T4.2.3  eco_list(status="pending") excludes approved and voided ECOs
T4.2.4  eco_get returns full ECO detail including notes
T4.2.5  eco_approve(additive) posts DR Change Orders / CR AP transaction
T4.2.6  eco_approve(additive) increases budget on affected account
T4.2.7  eco_approve(deductive) posts DR AP / CR Change Orders reversal
T4.2.8  eco_approve(deductive) decreases budget on affected account
T4.2.9  eco_void(pending) changes status; no transaction posted
T4.2.10 eco_void(approved) reverses posted transaction; budget reverted
T4.2.11 eco_void records reason in KVP; ECO visible in eco_list with void status
T4.2.12 eco_list shows correct total approved ECO value and pending ECO exposure
T4.2.13 Full workflow: CO-001 additive $5K electrical → approve → budget_get shows
         original $45K + $5K ECO split correctly; variance updated
```

---

### M4.3 — Updated budget_vs_actual and project_summary

**Deliverables:**

`get_budget_vs_actual()` is updated to query the live GnuCash budget instead of
hardcoded constants. If no budget exists in the book, returns a clear error
message directing the user to run `budget_create` + `budget_set_amount`.

```python
@app.tool()
def get_budget_vs_actual(
    budget_name: str | None = None,  # None = use first/only budget in book
    include_ecos: bool = True,        # include approved ECO amounts separately
) -> dict:
    """Compare live budget vs actual spend.
    Returns original contract budget, ECO adjustments, revised budget,
    committed, paid, and variance per account and in total."""
```

Output when `include_ecos=True`:
```json
{
  "budget_name": "GC Pre-Construction",
  "as_of": "2025-11-15",
  "summary": {
    "original_contract": "462000.00",
    "approved_ecos": "8500.00",
    "revised_budget": "470500.00",
    "committed": "127450.00",
    "paid": "89200.00",
    "remaining": "342550.00",
    "pct_committed": 27.1
  },
  "by_account": [ ... ]
}
```

`get_project_summary()` is updated to include a `budget_status` field:
```json
{
  "funded": "...",
  "spent": "...",
  "open_ap": "...",
  "cash_balance": "...",
  "interest_earned": "...",
  "budget_status": {
    "original_contract": "462000.00",
    "approved_ecos": "8500.00",
    "committed_pct": 27.1,
    "pending_eco_exposure": "12000.00"
  }
}
```

**Tests:**
```
T4.3.1  get_budget_vs_actual with no budget in book returns clear error message
T4.3.2  get_budget_vs_actual returns correct variance after entering GC budget
T4.3.3  get_budget_vs_actual(include_ecos=True) shows ECO adjustments separately
T4.3.4  get_budget_vs_actual(include_ecos=False) shows only original contract budget
T4.3.5  get_project_summary includes budget_status with correct pending_eco_exposure
T4.3.6  Professional fees (Architecture, Structural, MEP) appear in budget_vs_actual
         only if a budget amount has been set on those accounts
```

---

### Phase 4 exit criteria

- Full GC budget entry workflow validated: create budget → set all line items →
  `budget_get` matches GC spreadsheet totals
- ECO round-trip tested: create → approve (additive) → `budget_get` shows revised
  budget; `eco_list` shows approved CO
- `get_budget_vs_actual()` no longer references hardcoded constants from `src/budget.py`
  (that file is deleted or reduced to utility functions only)
- `get_project_summary()` includes `budget_status` with ECO exposure
- New resource `gnucash://budget-guide` and `gnucash://eco-guide` populated with
  workflow documentation and served statically from Swift proxy

---

