# Phase 6 — Project-Specific MCP Tools

**Goal:** Project-specific tools: budget tracking, AP aging,
interest income, and tranche management. Claude can answer project finance questions
directly from the ledger.

**Prerequisites:** Phase 5 complete.

### M6.1 — External budgets & professional fees (TOML-driven)

TL;DR — Professional-fee contract values and auxiliary external budget items
(hourly overtime rates, material overage allowances, contingency percentages)
live in a per-book TOML that the Swift proxy loads at startup and exposes to MCP
clients. GnuCash remains authoritative for transactions and native budgets; TOML
supplements reporting only.

Schema (suggested file: `gnucash-mcp-budgets.toml`)
- `meta`: title, version, currency, effective_date
- `professional_fees`: list of { account, contract_type (fixed|range), contract_total?, contract_low?, contract_high?, notes }
- `external_budgets`: list of { account, amount, notes }
- `rates`: { overtime_multiplier, material: { overage_pct } }
- `proxy`: { expose_resource, validate_on_start, hot_reload_sighup }

Example snippet
```toml
[meta]
title = "Example construction project budgets"
version = "1.0"
currency = "USD"
effective_date = "2026-04-01"

[[professional_fees]]
account = "Expenses:Architecture — Acme Architecture"
contract_type = "fixed"
contract_total = 42000.00
notes = "AAI #101 + #102 per REV2"

[[external_budgets]]
account = "Expenses:Construction:Allowances"
amount = 15000.00
notes = "GC allowances not represented in native budget"

[rates]
overtime_multiplier = 1.5

[rates.material]
overage_pct = 0.10

[proxy]
expose_resource = "gnucash://budget-extensions"
validate_on_start = true
hot_reload_sighup = true
```

Runtime merge rules
- Query native GnuCash budgets first for `get_budget_vs_actual()`.
- If a native budget is missing for an account, fall back to `external_budgets`.
- `professional_fees` entries in TOML are authoritative contract constants used
  by `get_project_summary()`.
- `rates` are advisory inputs used by proxy-level calculations (runway, overage)
  and are not written back to the book.

Operational behavior
- Location: default `$BOOK_DIR/gnucash-mcp-budgets.toml`; override via
  `GNUCASH_MCP_CONFIG` or `--config` CLI flag. Precedence: CLI > env > per-book
  file > built-in defaults.
- On startup: Swift proxy loads and validates TOML (fatal if `validate_on_start=true`
  and file malformed). Proxy publishes combined view at `gnucash://budget-extensions`
  and makes the TOML available to containers at `/run/mcp/budgets.toml` (read-only)
  plus env `GNUCASH_MCP_BUDGETS`.
- Hot-reload: SIGHUP triggers re-validate + re-publish; invalid updates are
  rejected and logged while the previous config remains active.
- Audit: responses that use external values annotate `source` and `effective_date`.

Verification (tests)
1. Unit: TOML parser validates required fields and numeric types.
2. Integration: proxy started with sample TOML exposes `gnucash://budget-extensions`
   including `professional_fees`, `external_budgets`, and `rates`.
3. Functional: `get_project_summary()` includes `professional_fees` totals combined
   with live GnuCash construction budget; test both presence and absence of native
   budget entries.
4. Edge: invalid updated TOML + SIGHUP leaves proxy using previous config and logs an error.

Decision / assumptions
- Professional fees are kept in TOML because they are fixed contract figures and
  not expected to be edited in GnuCash.
- External budget items and rates are advisory and live in TOML so the Swift proxy
  can calculate aggregated views without writing to the book.
- GnuCash remains the single source for transactional truth after startup.

---

### M6.2 — AP aging

**Deliverables:**
- `get_ap_aging() -> dict`
  - Per vendor: `vendor`, `invoice_ref`, `invoice_date`, `due_date`,
    `amount`, `days_outstanding`, `past_due`
  - Only includes vendors with non-zero AP balance

**Tests:**
```
T6.2.1  Vendor with paid invoice shows $0 balance and does not appear in output
T6.2.2  Vendor with open invoice shows correct amount and days_outstanding
T6.2.3  Invoice past due_date has past_due: true
T6.2.4  get_ap_aging() returns empty dict when all AP cleared
T6.2.5  days_outstanding calculated from today's date, not a hardcoded value
```

---

### M6.3 — Interest income

**Deliverables:**
- `post_interest(month: str, amount: str) -> dict`
  - Posts: debit Project Checking, credit Interest Income — Project Account
  - `month` format: `YYYY-MM`
- `estimate_monthly_interest(apy: float = 0.03) -> dict`
  - Returns estimated monthly interest on current Project Checking balance
  - Returns `{"estimated": "270.00", "balance": "107978.00", "apy": 0.03}`

**Tests:**
```
T6.3.1  post_interest("2025-01", "270.00") creates balanced transaction
T6.3.2  Interest Income account balance increases by posted amount
T6.3.3  estimate_monthly_interest(0.03) with $107,978 balance returns ~$270
T6.3.4  post_interest with negative amount raises ValueError (not posted)
T6.3.5  post_interest with invalid month format raises ValueError
```

---

### M6.4 — Tranche tracking and runway

**Deliverables:**
- `get_tranche_summary() -> dict`
  - All `fund_project` transactions: date, amount, running total
- `project_runway_days() -> int | None`
  - Estimate: cash balance ÷ (total spend ÷ days since first transaction)
  - Returns `None` if no spend activity yet

**Tests:**
```
T6.4.1  get_tranche_summary() lists each fund_project transaction with correct amounts
T6.4.2  Running total in get_tranche_summary() matches
        get_account_balance("Assets:Project Checking — First Project Bank")
T6.4.3  project_runway_days() returns a positive integer after some spend activity
T6.4.4  project_runway_days() with zero spend returns None (not ZeroDivisionError)
T6.4.5  project_runway_days() changes correctly after posting a new payment
```

---

### Phase 6 exit criteria

Claude can answer all of the following from the live ledger, without manual
calculation:

- "How much have I spent on architecture vs the signed contract?"
- "What invoices are currently unpaid and how long outstanding?"
- "What is my remaining budget for electrical, compared to the GC's contract?"
- "How many months of runway do I have at current spend rate?"
- "How much interest have I earned on the project account this year?"
- "What change orders are pending and what is my total ECO exposure?"
- "What is my revised contract total including approved change orders?"

All answers cross-checked against project documents in this Claude project.
Construction budget answers require Phase 4 complete (GC budget entered).

---

