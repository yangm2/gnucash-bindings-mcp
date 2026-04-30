# GnuCash Vendor Guide

## vendor_add

Add a new vendor/subcontractor. Exactly one of `trade` or `expense_category` required.

### Trade vendors (construction subcontractors)

Pass the full path of an existing trade expense account.
Creates only `Liabilities:AP — {name}`; the trade expense account is shared.

  vendor_add("Pacific Crest Electrical", trade="Expenses:Construction:Electrical")

Use list_accounts("Expenses:Construction") to see current trade accounts.

### Professional vendors (architects, engineers)

Pass one of the valid `expense_category` values.
Creates both `Liabilities:AP — {name}` and a dedicated expense account.

  vendor_add("Hillside Architecture", expense_category="Architecture")

Valid expense_category values:
  Architecture  → Expenses:Architecture — {name}
  Structural    → Expenses:Structural Engineering — {name}
  MEP           → Expenses:MEP Consulting — {name}
  HVAC          → Expenses:HVAC Engineering — {name}

## vendor_rename

Rename a vendor. For professional vendors, renames both AP and expense accounts atomically.
Existing transactions are unaffected (accounts tracked by GUID, not name).

## vendor_update

Change expense coding for a vendor.
For professional vendors: creates a new expense account; old account preserved for history.
For trade vendors: reassigns to a different trade account path.

## vendor_delete

Delete a vendor. Requires confirm=True.
Fails if the AP account has any transaction history — leave those vendors in place.
