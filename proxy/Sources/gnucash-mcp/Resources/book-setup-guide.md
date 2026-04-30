# GnuCash Book Setup Guide

## book_add_account

Add a new account to the chart of accounts.

Parameters:
  name          – leaf account name (e.g. "Landscaping")
  parent_path   – colon-separated path to the parent account (e.g. "Expenses:Construction")
  account_type  – one of: ASSET, BANK, CASH, CREDIT, EQUITY, EXPENSE, INCOME,
                  LIABILITY, PAYABLE, RECEIVABLE
  commodity     – currency code, default "USD"

This call is idempotent: if an account with the same name already exists under
the parent, the existing account is returned unchanged.

Raises:
  AccountNotFoundError  – parent_path does not exist
  ValueError            – account_type is not a recognised value

## book_verify_structure

Compare the live chart of accounts against the expected MC-6 structure.
Returns {"ok": bool, "missing": [...], "unexpected": [...]}.
Run this after bulk account creation to confirm correctness before posting
any transactions.

## Chart of accounts naming conventions (MC-6)

- Trade subcontractor AP:    Liabilities:AP — {vendor name}
- Professional fee AP:       Liabilities:AP — {vendor name}
- Professional fee expense:  Expenses:{category} — {vendor name}
  Valid categories: Architecture, Structural Engineering, MEP Consulting,
                    HVAC Engineering
- Construction trade:        Expenses:Construction:{trade}
- Change orders:             Expenses:Change Orders:{trade}
- Permits:                   Expenses:Permits and Fees (direct, no vendor)
