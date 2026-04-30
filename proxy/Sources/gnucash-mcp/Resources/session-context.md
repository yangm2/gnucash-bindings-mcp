# GnuCash MCP — Session Context

This server provides read-write access to a GnuCash construction project ledger
stored in an APFS sparsebundle. Claude is the primary write interface; the macOS
GnuCash GUI is read-only.

## Tool tiers

**Tier 1 — Operational** (daily use, full descriptions in tools/list):
- Write: receive_invoice, pay_invoice, fund_project, post_interest, post_transaction
- Read: get_account_balance, list_accounts, list_transactions, get_transaction,
  get_project_summary, get_budget_vs_actual, get_ap_aging, get_audit_log

**Tier 1 — Transaction correction** (use void_transaction over delete_transaction):
- update_transaction, void_transaction, delete_transaction

**Tier 2 — Administrative** (read gnucash://book-setup-guide or gnucash://vendor-guide
before using these):
- Book: book_add_account, book_get_account_tree, book_verify_structure,
  book_set_opening_balance, book_rename_account, book_move_account, book_delete_account
- Vendors: vendor_add, vendor_list, vendor_get_details, vendor_rename,
  vendor_update, vendor_delete
- Budgets: budget_create, budget_list, budget_get, budget_set_amount,
  budget_update, budget_delete
- ECOs: eco_create, eco_list, eco_get, eco_approve, eco_void

## Workflow conventions

1. Always read the relevant guide resource before first use of Tier 2 tools.
2. Use void_transaction (not delete_transaction) for accounting corrections.
3. Amounts are decimal strings e.g. "25000.00" — not numbers.
4. Account paths are colon-separated e.g. "Expenses:Construction:Electrical".
5. Vendor names must match exactly across receive_invoice and pay_invoice.

## AP workflow

receive_invoice → creates DR expense / CR AP-vendor
pay_invoice     → creates DR AP-vendor / CR Project Checking

## ECO workflow

eco_create (pending) → eco_approve (posts transaction, adjusts budget) → eco_void (if needed)
