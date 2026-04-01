from gnucash_mcp.tools import read, write
import json

HANDLERS = {
    # Tier 1 — read
    "get_account_balance":  read.get_account_balance,
    "list_accounts":        read.list_accounts,
    "list_transactions":    read.list_transactions,
    "get_transaction":      read.get_transaction,
    "get_project_summary":  read.get_project_summary,
    "get_audit_log":        read.get_audit_log,     # reads WAL, no GnuCash session
    "__unlock_ledger__":    read.unlock_ledger,
    "gnucash://vendors":    read.vendors_resource,  # dynamic resource
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
        except Exception as e:
            return error_response(req_id, -32603, str(e))

    if method == "resources/read":
        uri = request.get("params", {}).get("uri")
        handler = HANDLERS.get(uri)
        if not handler:
            return error_response(req_id, -32601, f"Unknown resource: {uri}")
        result = handler()
        return success_response(req_id, {"contents": [{"uri": uri, "text": json.dumps(result)}]})

    return error_response(req_id, -32601, f"Unsupported method in container: {method}")
