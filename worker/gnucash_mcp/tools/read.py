"""Read tools — Tier 1 read-only MCP tools (M1.5).

All tools open a GnuCash session read-only, query data, and return dicts/lists
suitable for JSON serialization.  Book path from GNUCASH_BOOK_PATH env var.
"""

import gnucash.gnucash_core_c as gc

from gnucash_mcp.session import (
    account_balance_float,
    AccountNotFoundError,
    book_path,
    book_session,
    get_account,
    get_txn_isodate,
)
from gnucash_mcp import wal


def _subtree_balance_float(acc) -> float:
    """Recursively sum balance of acc and all its descendants as a float."""
    total = acc.GetBalance().to_double()
    for child in acc.get_children():
        total += _subtree_balance_float(child)
    return total


def _balance_str(gnc_numeric) -> str:
    """Convert GncNumeric to a human-readable decimal string."""
    try:
        return f"{gnc_numeric.to_double():.2f}"
    except Exception:
        return str(gnc_numeric)


def _acc_to_dict(acc) -> dict:
    acct_type = acc.GetType()
    type_str = gc.xaccAccountGetTypeStr(acct_type)
    return {
        "name": acc.name,
        "type": type_str,
        "balance": _balance_str(acc.GetBalance()),
    }


def _account_full_path(acc) -> str:
    """Return the colon-separated full path for an account, e.g. 'Expenses:Architecture — Acme'."""
    parts = []
    current = acc
    while current is not None:
        parent = current.get_parent()
        if parent is None:
            break  # current is the hidden root
        parts.append(current.name)
        current = parent
    parts.reverse()
    return ":".join(parts)


def _split_to_dict(split) -> dict:
    return {
        "account": _account_full_path(split.GetAccount()),
        "amount": _balance_str(split.GetAmount()),
        "memo": split.GetMemo(),
        "reconcile_state": split.GetReconcile(),
    }


_MCP_PREFIX = "mcp-wal-id:"


def _mcp_slots(txn) -> dict | None:
    """Parse MCP provenance stored in the notes field as 'mcp-wal-id:{id}|mcp-tool:{tool}'."""
    notes = txn.GetNotes() or ""
    if not notes.startswith(_MCP_PREFIX):
        return None
    try:
        parts: dict[str, str] = {}
        for item in notes.split("|"):
            if ":" in item:
                k, v = item.split(":", 1)
                parts[k] = v
        wal_id = parts.get("mcp-wal-id")
        tool = parts.get("mcp-tool")
        if wal_id or tool:
            return {"wal_id": wal_id, "tool": tool}
    except Exception:
        pass
    return None


def _user_notes(txn) -> str:
    """Return user-visible notes, stripping any MCP provenance prefix."""
    raw = txn.GetNotes() or ""
    return "" if raw.startswith(_MCP_PREFIX) else raw


def _txn_to_dict(txn) -> dict:
    is_void = bool(txn.GetVoidStatus())
    return {
        "guid": txn.GetGUID().to_string(),
        "date": get_txn_isodate(txn) if txn.GetDate() else None,
        "description": txn.GetDescription(),
        "notes": _user_notes(txn),
        "is_void": is_void,
        "void_reason": txn.GetVoidReason() if is_void else None,
        "splits": [_split_to_dict(s) for s in txn.GetSplitList()],
        "mcp": _mcp_slots(txn),
    }


def get_account_balance(account_path: str) -> dict:
    """Return current balance for a colon-separated account path."""
    with book_session(book_path()) as session:
        try:
            acc = get_account(session.book, account_path)
        except AccountNotFoundError as exc:
            return {"error": str(exc)}
        balance = acc.GetBalance()
        return {
            "account": account_path,
            "balance": _balance_str(balance),
            "currency": acc.GetCommodity().get_mnemonic() if acc.GetCommodity() else "USD",
        }


def list_accounts(parent_path: str | None = None) -> list:
    """List accounts. If parent_path given, list children of that account; else top-level."""
    with book_session(book_path()) as session:
        book = session.book
        if parent_path:
            try:
                parent = get_account(book, parent_path)
            except AccountNotFoundError as exc:
                return [{"error": str(exc)}]
            accounts = list(parent.get_children())
        else:
            accounts = list(book.get_root_account().get_children())

        return [_acc_to_dict(acc) for acc in accounts]


def list_transactions(account_path: str, limit: int = 20) -> list:
    """List most recent transactions for an account, newest first."""
    with book_session(book_path()) as session:
        try:
            acc = get_account(session.book, account_path)
        except AccountNotFoundError as exc:
            return [{"error": str(exc)}]

        splits = list(acc.GetSplitList())
        splits.sort(key=lambda s: s.GetParent().GetDate(), reverse=True)
        splits = splits[:limit]

        result = []
        for split in splits:
            txn = split.GetParent()
            result.append(
                {
                    "guid": txn.GetGUID().to_string(),
                    "date": get_txn_isodate(txn) if txn.GetDate() else None,
                    "description": txn.GetDescription(),
                    "amount": _balance_str(split.GetAmount()),
                    "memo": split.GetMemo(),
                }
            )
        return result


def _find_txn_by_guid(book, guid_str: str):
    """Walk all accounts recursively to find a transaction by GUID string."""

    def _walk(acc):
        for split in acc.GetSplitList():
            txn = split.GetParent()
            if txn.GetGUID().to_string() == guid_str:
                return txn
        for child in acc.get_children():
            result = _walk(child)
            if result is not None:
                return result
        return None

    return _walk(book.get_root_account())


def get_transaction(tx_id: str) -> dict:
    """Fetch a single transaction by GUID."""
    with book_session(book_path()) as session:
        try:
            txn = _find_txn_by_guid(session.book, tx_id)
            if txn is None:
                return {"error": f"Transaction {tx_id!r} not found"}
            return _txn_to_dict(txn)
        except Exception as exc:
            return {"error": str(exc)}


def get_project_summary() -> dict:
    """Return summary balances for the main project accounts."""
    from gnucash_mcp.tools.eco import _load_ecos

    with book_session(book_path()) as session:
        book = session.book

        def bal(path, total=False):
            try:
                acc = get_account(book, path)
                if total:
                    return f"{_subtree_balance_float(acc):.2f}"
                return _balance_str(acc.GetBalance())
            except AccountNotFoundError:
                return None

        summary: dict[str, object] = {
            "checking_balance": bal("Assets:Project Checking"),
            "owner_capital": bal("Equity:Owner Capital"),
            "interest_income": bal("Income:Interest Income"),
            "total_expenses": bal("Expenses", total=True),
            "total_ap": bal("Liabilities", total=True),
        }

    ecos = _load_ecos()
    pending_exposure = sum(float(e["amount"]) for e in ecos if e["status"] == "pending")
    summary["budget_status"] = {"pending_eco_exposure": f"{pending_exposure:.2f}"}
    return summary


def get_budget_vs_actual(include_ecos: bool = True) -> dict:
    """Return budget vs actual comparison across all budgeted accounts.

    If include_ecos=True, splits out original_contract vs approved ECO adjustments.
    Returns {"error": ...} if no budget exists.
    """
    from decimal import Decimal
    from gnucash_mcp.tools.budget import _load_budgets, _compute_actuals
    from gnucash_mcp.tools.eco import _load_ecos

    budgets = _load_budgets()
    if not budgets:
        return {"error": "No budget found in book"}
    budget = budgets[0]

    ecos = _load_ecos()
    approved_ecos: dict[str, Decimal] = {}
    for eco in ecos:
        if eco["status"] == "approved":
            acct = eco["budget_account"]
            delta = Decimal(eco["amount"])
            if eco["direction"] == "additive":
                approved_ecos[acct] = approved_ecos.get(acct, Decimal(0)) + delta
            else:
                approved_ecos[acct] = approved_ecos.get(acct, Decimal(0)) - delta

    with book_session(book_path()) as session:
        book = session.book
        by_account: list[dict] = []
        originals: list[Decimal] = []
        for acct_path, budgeted_str in budget.get("accounts", {}).items():
            revised = Decimal(budgeted_str)
            eco_adj = approved_ecos.get(acct_path, Decimal(0))
            original = revised - eco_adj
            originals.append(original)
            committed, paid = _compute_actuals(book, acct_path)
            entry: dict = {
                "account": acct_path,
                "budgeted": f"{revised:.2f}",
                "committed": f"{committed:.2f}",
                "paid": f"{paid:.2f}",
                "variance": f"{revised - Decimal(str(committed)):.2f}",
            }
            if include_ecos:
                entry["original"] = f"{original:.2f}"
                entry["eco_adjustment"] = f"{eco_adj:.2f}"
            by_account.append(entry)

    total_revised = sum(Decimal(a["budgeted"]) for a in by_account)
    total_committed = sum(Decimal(a["committed"]) for a in by_account)
    total_original = sum(originals)
    total_eco_adj = sum(approved_ecos.values())

    summary: dict = {
        "original_contract": f"{total_original:.2f}",
        "committed": f"{total_committed:.2f}",
        "remaining": f"{total_revised - total_committed:.2f}",
    }
    if include_ecos:
        summary["approved_ecos"] = f"{total_eco_adj:.2f}"
        summary["revised_budget"] = f"{total_revised:.2f}"

    return {"summary": summary, "by_account": by_account}


def get_audit_log(
    limit: int = 20,
    tool_filter: str | None = None,
    since_date: str | None = None,
) -> list:
    """Return recent WAL entries, newest first.

    limit: max entries to return
    tool_filter: if set, only entries with matching type field
    since_date: if set (YYYY-MM-DD), only entries logged after that date
    """
    entries = wal.all_entries()
    entries.reverse()

    if tool_filter is not None:
        entries = [e for e in entries if e["type"] == tool_filter]

    if since_date is not None:
        entries = [e for e in entries if e["logged_at"][:10] > since_date]

    return entries[:limit]


def unlock_ledger() -> dict:
    """Internal tool: returns session context resource content."""
    return {
        "book": str(book_path()),
        "tool_groups": {
            "operational": [
                "receive_invoice",
                "pay_invoice",
                "fund_project",
                "post_interest",
                "post_transaction",
                "get_account_balance",
                "list_accounts",
                "list_transactions",
                "get_transaction",
                "get_project_summary",
                "get_audit_log",
            ],
        },
    }


def vendors_resource() -> list:
    """Return list of vendors (AP accounts) with current balances."""
    with book_session(book_path()) as session:
        book = session.book
        try:
            liabilities = get_account(book, "Liabilities")
        except AccountNotFoundError:
            return []

        vendors = []
        for acc in liabilities.get_children():
            if acc.name.startswith("AP — "):
                vendors.append(
                    {
                        "name": acc.name[len("AP — ") :],
                        "account": acc.name,
                        "balance": f"{account_balance_float(acc, negate=True):.2f}",
                    }
                )
        return vendors
