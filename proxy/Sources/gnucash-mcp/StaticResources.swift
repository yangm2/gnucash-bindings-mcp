import Foundation

struct MCPResource: Encodable {
    let uri: String
    let name: String
    let description: String
    let mimeType: String
}

enum StaticResources {
    static let all: [MCPResource] = [
        MCPResource(
            uri: "gnucash://session-context",
            name: "Session Context",
            description: "How to use this MCP server: tool tiers, workflow, and conventions",
            mimeType: "text/markdown",
        ),
        MCPResource(
            uri: "gnucash://book-setup-guide",
            name: "Book Setup Guide",
            description: "Account creation conventions and chart of accounts rules (MC-6)",
            mimeType: "text/markdown",
        ),
        MCPResource(
            uri: "gnucash://vendor-guide",
            name: "Vendor Guide",
            description: "How to add and manage trade and professional vendors",
            mimeType: "text/markdown",
        ),
        MCPResource(
            uri: "gnucash://expected-chart",
            name: "Expected Chart of Accounts",
            description: "The MC-6 chart structure this book should match",
            mimeType: "text/markdown",
        )
    ]

    static func content(for uri: String) -> String? {
        switch uri {
        case "gnucash://session-context": sessionContext
        case "gnucash://book-setup-guide": bookSetupGuide
        case "gnucash://vendor-guide": vendorGuide
        case "gnucash://expected-chart": expectedChart
        default: nil
        }
    }

    // MARK: - Resource content

    static let sessionContext = """
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
    """

    static let bookSetupGuide = """
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
    """

    static let vendorGuide = """
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
    """

    static let expectedChart = """
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
    """
}
