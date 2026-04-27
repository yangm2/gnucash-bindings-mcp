from gnucash_mcp.tools import book, read, vendor, write
import json

HANDLERS = {
    # Tier 1 — read
    "get_account_balance": read.get_account_balance,
    "list_accounts": read.list_accounts,
    "list_transactions": read.list_transactions,
    "get_transaction": read.get_transaction,
    "get_project_summary": read.get_project_summary,
    "get_audit_log": read.get_audit_log,  # reads WAL, no GnuCash session
    "__unlock_ledger__": read.unlock_ledger,
    "gnucash://vendors": read.vendors_resource,  # dynamic resource
    "gnucash://book-setup-guide": book.book_setup_guide_resource,
    "gnucash://expected-chart": book.expected_chart_resource,
    # Tier 2 — book management
    "book_add_account": book.book_add_account,
    "book_get_account_tree": book.book_get_account_tree,
    "book_verify_structure": book.book_verify_structure,
    "book_set_opening_balance": book.book_set_opening_balance,
    "book_rename_account": book.book_rename_account,
    "book_move_account": book.book_move_account,
    "book_delete_account": book.book_delete_account,
    # Tier 2 — vendor management
    "vendor_add": vendor.vendor_add,
    "vendor_list": vendor.vendor_list,
    "vendor_get_details": vendor.vendor_get_details,
    "vendor_rename": vendor.vendor_rename,
    "vendor_update": vendor.vendor_update,
    "vendor_delete": vendor.vendor_delete,
    "gnucash://vendor-guide": vendor.vendor_guide_resource,
    # Tier 1 — write
    "post_transaction": write.post_transaction,
    "fund_project": write.fund_project,
    "receive_invoice": write.receive_invoice,
    "pay_invoice": write.pay_invoice,
    "post_interest": write.post_interest,
}


def success_response(req_id, result):
    return {"id": req_id, "result": result}


def error_response(req_id, code, message):
    return {"id": req_id, "error": {"code": code, "message": message}}


def dispatch(request: dict) -> dict:
    method = request.get("method")
    req_id = request.get("id")

    if method == "tools/call":
        name = request.get("params", {}).get("name")
        args = request.get("params", {}).get("arguments", {})
        handler = HANDLERS.get(name)
        if not handler:
            return error_response(req_id, -32601, f"Unknown tool: {name}")
        try:
            result = handler(**args)
            return success_response(req_id, result)
        except Exception as exc:
            return error_response(req_id, -32603, str(exc))

    if method == "resources/read":
        uri = request.get("params", {}).get("uri")
        handler = HANDLERS.get(uri)
        if not handler:
            return error_response(req_id, -32601, f"Unknown resource: {uri}")
        result = handler()
        return success_response(req_id, {"contents": [{"uri": uri, "text": json.dumps(result)}]})

    return error_response(req_id, -32601, f"Unsupported method in container: {method}")
