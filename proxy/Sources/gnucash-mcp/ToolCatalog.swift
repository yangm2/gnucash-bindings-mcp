import Foundation

struct MCPTool: Sendable {
    let name: String
    let description: String
    let inputSchema: JSONSchema
}

extension MCPTool: Encodable {
    private enum CodingKeys: String, CodingKey { case name, description, inputSchema }
    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(name, forKey: .name)
        try c.encode(description, forKey: .description)
        try c.encode(inputSchema, forKey: .inputSchema)
    }
}

enum ToolCatalog {
    // ── tier membership sets ──────────────────────────────────────────────────

    static let tier1: Set<String> = [
        "receive_invoice", "pay_invoice", "fund_project", "post_interest",
        "post_transaction", "get_account_balance", "list_accounts",
        "list_transactions", "get_transaction", "get_project_summary",
        "get_budget_vs_actual", "get_ap_aging", "get_audit_log"
    ]
    static let tier1Crud: Set<String> = [
        "update_transaction", "void_transaction", "delete_transaction"
    ]
    static let tier2: Set<String> = [
        "book_add_account", "book_get_account_tree", "book_verify_structure",
        "book_set_opening_balance", "book_rename_account", "book_move_account",
        "book_delete_account",
        "vendor_add", "vendor_list", "vendor_get_details", "vendor_rename",
        "vendor_update", "vendor_delete",
        "budget_create", "budget_list", "budget_get", "budget_set_amount",
        "budget_update", "budget_delete",
        "eco_create", "eco_list", "eco_get", "eco_approve", "eco_void"
    ]
    static let readOnly: Set<String> = [
        "get_account_balance", "list_accounts", "list_transactions",
        "get_transaction", "get_project_summary", "get_audit_log"
    ]
    static let setup: Set<String> = [
        "book_add_account", "book_get_account_tree", "book_verify_structure",
        "book_set_opening_balance", "book_rename_account", "book_move_account",
        "book_delete_account",
        "vendor_add", "vendor_list", "vendor_get_details", "vendor_rename",
        "vendor_update", "vendor_delete",
        "budget_create", "budget_list", "budget_get", "budget_set_amount",
        "budget_update", "budget_delete",
        "eco_create", "eco_list", "eco_get"
    ]
    static let construction: Set<String> =
        tier1
            .union(tier1Crud)
            .union(["eco_create", "eco_list", "eco_get", "eco_approve", "eco_void"])
    static let operational: Set<String> = tier1.union(tier1Crud)
    static let reconcile: Set<String> = [
        "list_transactions", "get_transaction", "get_account_balance",
        "get_audit_log", "void_transaction", "update_transaction"
    ]

    // ── tool definitions ──────────────────────────────────────────────────────

    static let tools: [MCPTool] = [
        // ── Tier 1 — write ────────────────────────────────────────────────────

        MCPTool(
            name: "receive_invoice",
            description: "DR expense_account, CR AP-vendor. Read gnucash://vendor-guide first if vendor is new.",
            inputSchema: .object(
                [
                    "date": .string(description: "YYYY-MM-DD"),
                    "vendor": .string(description: "Exact name e.g. 'Acme Architecture'"),
                    "invoice_ref": .string(description: "e.g. 'AAI-102'"),
                    "amount": .string(description: "Decimal e.g. '25000.00'"),
                    "expense_account": .string(
                        description:
                        "Full path e.g. 'Expenses:Architecture — Acme Architecture'",
                    )
                ],
                required: ["date", "vendor", "invoice_ref", "amount", "expense_account"],
            ),
        ),

        MCPTool(
            name: "pay_invoice",
            description: "DR AP-vendor, CR Project Checking. Settles an outstanding payable.",
            inputSchema: .object(
                [
                    "date": .string(description: "YYYY-MM-DD"),
                    "vendor": .string(description: "Exact vendor name"),
                    "invoice_ref": .string(description: "Invoice reference being paid"),
                    "amount": .string(description: "Decimal amount e.g. '25000.00'")
                ],
                required: ["date", "vendor", "invoice_ref", "amount"],
            ),
        ),

        MCPTool(
            name: "fund_project",
            description: "DR Project Checking, CR Owner Capital. Records owner funding.",
            inputSchema: .object(
                [
                    "date": .string(description: "YYYY-MM-DD"),
                    "amount": .string(description: "Decimal amount e.g. '50000.00'"),
                    "memo": .string(description: "Optional memo e.g. 'Initial funding'")
                ],
                required: ["date", "amount"],
            ),
        ),

        MCPTool(
            name: "post_interest",
            description: "DR Project Checking, CR Interest Income. Records monthly interest.",
            inputSchema: .object(
                [
                    "month": .string(description: "YYYY-MM or YYYY-MM-DD"),
                    "amount": .string(description: "Decimal amount e.g. '42.17'")
                ],
                required: ["month", "amount"],
            ),
        ),

        MCPTool(
            name: "post_transaction",
            description:
            "Post an arbitrary balanced transaction. Splits must sum to zero. Use for transactions not covered by other tools.",
            inputSchema: .object(
                [
                    "date": .string(description: "YYYY-MM-DD"),
                    "description": .string(description: "Human-readable description"),
                    "splits": .array(
                        items: .object(
                            [
                                "account_path": .string(
                                    description: "Full colon-separated account path",
                                ),
                                "amount": .string(
                                    description: "Decimal; positive=DR, negative=CR",
                                ),
                                "memo": .string(description: "Optional split memo")
                            ],
                            required: ["account_path", "amount"],
                        ),
                        description: "Array of split objects; amounts must sum to zero",
                    )
                ],
                required: ["date", "description", "splits"],
            ),
        ),

        // ── Tier 1 — read ─────────────────────────────────────────────────────

        MCPTool(
            name: "get_account_balance",
            description: "Return current balance for a single account.",
            inputSchema: .object(
                ["account_path": .string(description: "Full colon-separated path")],
                required: ["account_path"],
            ),
        ),

        MCPTool(
            name: "list_accounts",
            description:
            "List direct children of parent_path. Omit parent_path for top-level accounts.",
            inputSchema: .object(
                ["parent_path": .string(description: "e.g. 'Liabilities' or 'Expenses:Construction'")],
                required: [],
            ),
        ),

        MCPTool(
            name: "list_transactions",
            description: "List most recent transactions for an account, newest first.",
            inputSchema: .object(
                [
                    "account_path": .string(description: "Full account path"),
                    "limit": .integer(description: "Max results, default 20")
                ],
                required: ["account_path"],
            ),
        ),

        MCPTool(
            name: "get_transaction",
            description: "Fetch full detail for a single transaction by GUID.",
            inputSchema: .object(
                ["tx_id": .string(description: "Transaction GUID from list_transactions")],
                required: ["tx_id"],
            ),
        ),

        MCPTool(
            name: "get_project_summary",
            description:
            "Return summary balances: checking, owner capital, interest, total expenses, total AP, and pending ECO exposure.",
            inputSchema: .empty,
        ),

        MCPTool(
            name: "get_budget_vs_actual",
            description:
            "Return budget vs actual comparison across all budgeted accounts. Returns error if no budget exists.",
            inputSchema: .object(
                [
                    "include_ecos": .bool(
                        description:
                        "If true (default), split out original_contract vs approved ECO adjustments",
                    )
                ],
                required: [],
            ),
        ),

        MCPTool(
            name: "get_ap_aging",
            description:
            "List all outstanding AP balances by vendor. Shows who owes what and how long it has been outstanding.",
            inputSchema: .empty,
        ),

        MCPTool(
            name: "get_audit_log",
            description: "Return recent WAL entries (MCP-originated transactions), newest first.",
            inputSchema: .object(
                [
                    "limit": .integer(description: "Max entries, default 20"),
                    "tool_filter": .string(description: "If set, only entries from this tool"),
                    "since_date": .string(
                        description: "If set (YYYY-MM-DD), only entries logged after this date",
                    )
                ],
                required: [],
            ),
        ),

        // ── Tier 1 CRUD ───────────────────────────────────────────────────────

        MCPTool(
            name: "update_transaction",
            description:
            "Update metadata (date, description, notes) on an existing transaction. Does not change splits or amounts.",
            inputSchema: .object(
                [
                    "transaction_guid": .string(description: "From get_transaction or list_transactions"),
                    "date": .string(description: "New date YYYY-MM-DD (optional)"),
                    "description": .string(description: "New description (optional)"),
                    "notes": .string(description: "New notes (optional)")
                ],
                required: ["transaction_guid"],
            ),
        ),

        MCPTool(
            name: "void_transaction",
            description:
            "Zero out a transaction while preserving audit trail. Preferred over delete_transaction.",
            inputSchema: .object(
                [
                    "transaction_guid": .string(description: "From list_transactions or get_transaction"),
                    "reason": .string(description: "Reason for void e.g. 'Wrong amount, see TXN-xyz'")
                ],
                required: ["transaction_guid", "reason"],
            ),
        ),

        MCPTool(
            name: "delete_transaction",
            description:
            "Permanently delete transaction. Pass confirm=true explicitly. Use void_transaction instead for audit trail.",
            inputSchema: .object(
                [
                    "transaction_guid": .string(description: "GUID of transaction to delete"),
                    "confirm": .bool(description: "Must be true to proceed")
                ],
                required: ["transaction_guid", "confirm"],
            ),
        ),

        // ── Tier 2 — book management ──────────────────────────────────────────

        MCPTool(
            name: "book_add_account",
            description: "Add account to chart of accounts. Read gnucash://book-setup-guide first.",
            inputSchema: .object(
                [
                    "name": .string(description: "Leaf account name e.g. 'Landscaping'"),
                    "parent_path": .string(
                        description: "Parent path e.g. 'Expenses:Construction'",
                    ),
                    "account_type": .enum(
                        [
                            "ASSET", "BANK", "CASH", "CREDIT", "EQUITY",
                            "EXPENSE", "INCOME", "LIABILITY", "PAYABLE", "RECEIVABLE"
                        ],
                    ),
                    "commodity": .string(description: "Currency code, default 'USD'")
                ],
                required: ["name", "parent_path", "account_type"],
            ),
        ),

        MCPTool(
            name: "book_get_account_tree",
            description:
            "Return direct children of parent_path. Pass empty string for top-level accounts.",
            inputSchema: .object(
                ["parent_path": .string(description: "Account path or '' for root")],
                required: [],
            ),
        ),

        MCPTool(
            name: "book_verify_structure",
            description:
            "Compare live chart of accounts against expected MC-6 structure. Returns missing and unexpected accounts.",
            inputSchema: .empty,
        ),

        MCPTool(
            name: "book_set_opening_balance",
            description: "Post opening balance transaction, crediting Equity:Opening Balances.",
            inputSchema: .object(
                [
                    "account_path": .string(description: "Account to set opening balance for"),
                    "amount": .string(description: "Opening balance amount"),
                    "date": .string(description: "YYYY-MM-DD")
                ],
                required: ["account_path", "amount", "date"],
            ),
        ),

        MCPTool(
            name: "book_rename_account",
            description:
            "Rename an account leaf. Existing transactions are unaffected (tracked by GUID).",
            inputSchema: .object(
                [
                    "account_path": .string(description: "Full current path"),
                    "new_name": .string(description: "New leaf name")
                ],
                required: ["account_path", "new_name"],
            ),
        ),

        MCPTool(
            name: "book_move_account",
            description:
            "Move an account to a new parent. Existing transactions are unaffected.",
            inputSchema: .object(
                [
                    "account_path": .string(description: "Full current path"),
                    "new_parent_path": .string(description: "Full path of new parent")
                ],
                required: ["account_path", "new_parent_path"],
            ),
        ),

        MCPTool(
            name: "book_delete_account",
            description:
            "Delete an account. Fails by default if account has any transaction history.",
            inputSchema: .object(
                [
                    "account_path": .string(description: "Full account path to delete"),
                    "require_zero_balance": .bool(
                        description: "Default true; set false to override balance check",
                    )
                ],
                required: ["account_path"],
            ),
        ),

        // ── Tier 2 — vendor management ────────────────────────────────────────

        MCPTool(
            name: "vendor_add",
            description:
            "Add a new vendor. Read gnucash://vendor-guide first. Exactly one of trade or expense_category required.",
            inputSchema: .object(
                [
                    "name": .string(description: "Vendor display name"),
                    "trade": .string(
                        description:
                        "Trade expense account path e.g. 'Expenses:Construction:Electrical'",
                    ),
                    "expense_category": .enum(
                        ["Architecture", "Structural", "MEP", "HVAC"],
                        description: "For professional vendors",
                    )
                ],
                required: ["name"],
            ),
        ),

        MCPTool(
            name: "vendor_list",
            description:
            "List all vendors with type, expense account paths, and current AP balance.",
            inputSchema: .empty,
        ),

        MCPTool(
            name: "vendor_get_details",
            description: "Return full details and transaction history for a named vendor.",
            inputSchema: .object(
                ["name": .string(description: "Vendor name")],
                required: ["name"],
            ),
        ),

        MCPTool(
            name: "vendor_rename",
            description:
            "Rename a vendor. For professional vendors, renames both AP and expense accounts atomically.",
            inputSchema: .object(
                [
                    "old_name": .string(description: "Current vendor name"),
                    "new_name": .string(description: "New vendor name")
                ],
                required: ["old_name", "new_name"],
            ),
        ),

        MCPTool(
            name: "vendor_update",
            description:
            "Change expense coding for a vendor. Exactly one of trade or expense_category required.",
            inputSchema: .object(
                [
                    "name": .string(description: "Vendor name"),
                    "trade": .string(description: "New trade account path"),
                    "expense_category": .enum(
                        ["Architecture", "Structural", "MEP", "HVAC"],
                    )
                ],
                required: ["name"],
            ),
        ),

        MCPTool(
            name: "vendor_delete",
            description:
            "Delete a vendor. Requires confirm=true. Fails if AP account has any transactions.",
            inputSchema: .object(
                [
                    "name": .string(description: "Vendor name"),
                    "confirm": .bool(description: "Must be true to proceed")
                ],
                required: ["name", "confirm"],
            ),
        ),

        // ── Tier 2 — budget management ────────────────────────────────────────

        MCPTool(
            name: "budget_create",
            description: "Create a new budget.",
            inputSchema: .object(
                [
                    "name": .string(description: "Budget name e.g. 'Project Budget 2025'"),
                    "period_start": .string(description: "YYYY-MM-DD"),
                    "num_periods": .integer(description: "Number of periods, default 1")
                ],
                required: ["name", "period_start"],
            ),
        ),

        MCPTool(
            name: "budget_list",
            description: "List all budgets.",
            inputSchema: .empty,
        ),

        MCPTool(
            name: "budget_get",
            description:
            "Return budget detail with budgeted/committed/paid/variance for each account.",
            inputSchema: .object(
                ["budget_name": .string(description: "Budget name")],
                required: ["budget_name"],
            ),
        ),

        MCPTool(
            name: "budget_set_amount",
            description:
            "Set budget amount for account_path. Creates the GnuCash account if missing.",
            inputSchema: .object(
                [
                    "budget_name": .string(description: "Budget name"),
                    "account_path": .string(
                        description: "Full account path e.g. 'Expenses:Construction:Electrical'",
                    ),
                    "amount": .string(description: "Budget amount e.g. '150000.00'")
                ],
                required: ["budget_name", "account_path", "amount"],
            ),
        ),

        MCPTool(
            name: "budget_update",
            description: "Update budget metadata (currently: rename).",
            inputSchema: .object(
                [
                    "budget_name": .string(description: "Current budget name"),
                    "new_name": .string(description: "New budget name (optional)")
                ],
                required: ["budget_name"],
            ),
        ),

        MCPTool(
            name: "budget_delete",
            description: "Delete a budget. Requires confirm=true.",
            inputSchema: .object(
                [
                    "budget_name": .string(description: "Budget name to delete"),
                    "confirm": .bool(description: "Must be true to proceed")
                ],
                required: ["budget_name", "confirm"],
            ),
        ),

        // ── Tier 2 — ECO management ───────────────────────────────────────────

        MCPTool(
            name: "eco_create",
            description:
            "Create a new Engineering Change Order in pending state. No transaction posted until eco_approve.",
            inputSchema: .object(
                [
                    "number": .string(description: "ECO number e.g. 'ECO-001'"),
                    "description": .string(description: "What the change order covers"),
                    "direction": .enum(
                        ["additive", "deductive"],
                        description: "additive=cost increase, deductive=cost decrease",
                    ),
                    "amount": .string(description: "Change amount e.g. '12500.00'"),
                    "budget_account": .string(
                        description:
                        "Affected Construction account e.g. 'Expenses:Construction:Framing'",
                    ),
                    "notes": .string(description: "Optional notes")
                ],
                required: ["number", "description", "direction", "amount", "budget_account"],
            ),
        ),

        MCPTool(
            name: "eco_list",
            description: "List ECOs, optionally filtered by status.",
            inputSchema: .object(
                [
                    "status": .enum(
                        ["pending", "approved", "void"],
                        description: "Filter by status (optional)",
                    )
                ],
                required: [],
            ),
        ),

        MCPTool(
            name: "eco_get",
            description: "Return full ECO detail including transaction GUID if approved.",
            inputSchema: .object(
                ["number": .string(description: "ECO number")],
                required: ["number"],
            ),
        ),

        MCPTool(
            name: "eco_approve",
            description:
            "Approve ECO: posts Change Orders transaction and adjusts budget amount.",
            inputSchema: .object(
                [
                    "number": .string(description: "ECO number to approve"),
                    "date": .string(description: "Approval date YYYY-MM-DD")
                ],
                required: ["number", "date"],
            ),
        ),

        MCPTool(
            name: "eco_void",
            description:
            "Void an ECO. If approved, voids the GnuCash transaction and restores budget.",
            inputSchema: .object(
                [
                    "number": .string(description: "ECO number to void"),
                    "reason": .string(description: "Reason for voiding")
                ],
                required: ["number", "reason"],
            ),
        )
    ]
}
