# Phase 7 — Reconciliation and Reporting

**Goal:** Bank reconciliation workflow and exportable reports for tax and
record-keeping purposes.

**Prerequisites:** Phase 6 complete.

### M7.1 — Bank reconciliation

**Deliverables:**
- `reconcile_account(account_path, statement_balance, statement_date) -> dict`
  - Returns: `ledger_balance`, `outstanding_items`, `reconciling_difference`
- `mark_cleared(transaction_id: str) -> dict`
  - Sets the GnuCash reconciliation flag on a transaction split

**Tests:**
```
T7.1.1  reconcile_account returns correct non-zero difference when one check outstanding
T7.1.2  reconcile_account returns difference of $0.00 when fully reconciled
T7.1.3  mark_cleared updates reconciliation flag; transaction appears as cleared in GUI
T7.1.4  Manual reconciliation drill against one actual project checking statement
        (document date, statement balance, result in TEST_RESULTS.md)
```

---

### M7.2 — CSV export

**Deliverables:**
- `export_transactions_csv(account_path, start_date, end_date) -> str`
  - CSV: date, description, debit, credit, balance, memo, reconciled
- `export_journal_csv(start_date, end_date) -> str`
  - Full double-entry journal: date, description, account, debit, credit

**Tests:**
```
T7.2.1  export_transactions_csv produces valid CSV with correct column headers
T7.2.2  Date range filtering excludes transactions outside range
T7.2.3  Debit/credit amounts in CSV match GnuCash register values
T7.2.4  CSV opens without error in Numbers and column types are preserved (manual)
T7.2.5  export_journal_csv debits equal credits across all rows (balanced)
```

---

### M7.3 — Year-end summary

**Deliverables:**
- `get_year_end_summary(year: int) -> dict`
  - `total_spend`, `interest_income` (for 1099-INT reference),
    `tranches_funded`, `ap_balance_year_end`, `net_project_cost`

**Tests:**
```
T7.3.1  get_year_end_summary(2024) returns correct totals for known 2024 transactions
T7.3.2  interest_income matches sum of post_interest entries for the year
T7.3.3  ap_balance_year_end matches known open invoices as of Dec 31
T7.3.4  net_project_cost = total_spend - interest_income (verified manually)
```

---

### Phase 7 exit criteria

- Monthly reconciliation workflow tested against one real bank statement
- 2024 year-end summary produced and validated against project documents
- CSV exports usable in Numbers for ad-hoc analysis

---

