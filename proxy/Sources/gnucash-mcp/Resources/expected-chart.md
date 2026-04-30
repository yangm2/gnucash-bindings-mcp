# Expected Chart of Accounts (MC-6)

## Top-level accounts

- Assets
  - Project Checking  (BANK)
- Liabilities
  - AP — {vendor}     (PAYABLE, one per vendor)
  - AP — Change Orders (PAYABLE, for ECO approvals)
- Equity
  - Owner Capital     (EQUITY)
  - Opening Balances  (EQUITY, created on first book_set_opening_balance)
- Income
  - Interest Income   (INCOME)
- Expenses
  - Construction      (EXPENSE, parent)
    - {trade}         (EXPENSE, one per trade budget line)
  - Change Orders     (EXPENSE, parent — mirrors Construction structure)
    - {trade}         (EXPENSE, created by eco_approve)
  - Architecture — {vendor}          (EXPENSE, per professional vendor)
  - Structural Engineering — {vendor} (EXPENSE, per professional vendor)
  - MEP Consulting — {vendor}        (EXPENSE, per professional vendor)
  - HVAC Engineering — {vendor}      (EXPENSE, per professional vendor)
  - Permits and Fees  (EXPENSE, direct — no vendor)

## Rules

- Permits are direct payments; jurisdictions are never vendors.
- Each vendor has exactly one AP account: Liabilities:AP — {vendor name}.
- Trade vendors share a single expense account per trade (Expenses:Construction:{trade}).
- Professional vendors each get a dedicated expense account.
- Construction budget line items create the Expenses:Construction children.
- Expenses:Change Orders mirrors Construction structure for ECO tracking.

Run book_verify_structure to compare the live book against this expected structure.
