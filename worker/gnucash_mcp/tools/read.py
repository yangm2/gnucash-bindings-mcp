"""Read tools — Tier 1 read-only MCP tools (M1.5).

All tools open a GnuCash session read-only, query data, and return dicts/lists
suitable for JSON serialization.  Book path from GNUCASH_BOOK_PATH env var.
"""

import os
from pathlib import Path

from gnucash_mcp.session import book_session, get_account, AccountNotFoundError
from gnucash_mcp import wal


def _book_path() -> Path:
    p = os.environ.get("GNUCASH_BOOK_PATH", "/data/project.gnucash")
    return Path(p)


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
    """Serialize an Account to a minimal dict."""
    import gnucash.gnucash_core_c as gc
    acct_type = acc.GetType()
    type_str = gc.xaccAccountGetTypeStr(acct_type)
    return {
        "name": acc.name,
        "type": type_str,
        "balance": _balance_str(acc.GetBalance()),
    }


def _split_to_dict(split) -> dict:
    return {
        "account": split.GetAccount().GetFullName(),
        "amount": _balance_str(split.GetAmount()),
        "memo": split.GetMemo(),
    }


def _txn_to_dict(txn) -> dict:
    splits = [_split_to_dict(s) for s in txn.GetSplitList()]
    return {
        "guid": str(txn.GetGUID()),
        "date": txn.GetDate().strftime("%Y-%m-%d") if txn.GetDate() else None,
        "description": txn.GetDescription(),
        "splits": splits,
        "mcp_wal_id": txn.GetSlot("mcp-wal-id") if hasattr(txn, "GetSlot") else None,
        "mcp_tool": txn.GetSlot("mcp-tool") if hasattr(txn, "GetSlot") else None,
    }


def get_account_balance(account_path: str) -> dict:
    """Return current balance for a colon-separated account path."""
    with book_session(_book_path()) as session:
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


def list_accounts(parent_path: str = None) -> list:
    """List accounts. If parent_path given, list children of that account; else top-level."""
    with book_session(_book_path()) as session:
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
    with book_session(_book_path()) as session:
        try:
            acc = get_account(session.book, account_path)
        except AccountNotFoundError as exc:
            return [{"error": str(exc)}]

        splits = list(acc.GetSplitList())
        # Sort by transaction date descending
        splits.sort(key=lambda s: s.GetParent().GetDate(), reverse=True)
        splits = splits[:limit]

        result = []
        for split in splits:
            txn = split.GetParent()
            result.append({
                "guid": str(txn.GetGUID()),
                "date": txn.GetDate().strftime("%Y-%m-%d") if txn.GetDate() else None,
                "description": txn.GetDescription(),
                "amount": _balance_str(split.GetAmount()),
                "memo": split.GetMemo(),
            })
        return result


def get_transaction(tx_id: str) -> dict:
    """Fetch a single transaction by GUID."""
    with book_session(_book_path()) as session:
        from gnucash import GUID
        try:
            guid = GUID()
            guid.string_set(tx_id)
            txn = guid.TransactionLookup(session.book)
            if txn is None:
                return {"error": f"Transaction {tx_id!r} not found"}
            return _txn_to_dict(txn)
        except Exception as exc:
            return {"error": str(exc)}


def get_project_summary() -> dict:
    """Return summary balances for the main project accounts."""
    with book_session(_book_path()) as session:
        book = session.book

        def bal(path, total=False):
            try:
                acc = get_account(book, path)
                if total:
                    return f"{_subtree_balance_float(acc):.2f}"
                return _balance_str(acc.GetBalance())
            except AccountNotFoundError:
                return None

        return {
            "checking_balance": bal("Assets:Project Checking"),
            "owner_capital": bal("Equity:Owner Capital"),
            "interest_income": bal("Income:Interest Income"),
            "total_expenses": bal("Expenses", total=True),
            "total_ap": bal("Liabilities", total=True),
        }


def _account_exists(book, path: str) -> bool:
    try:
        get_account(book, path)
        return True
    except AccountNotFoundError:
        return False


def get_audit_log() -> list:
    """Return all WAL entries (newest first)."""
    entries = wal.all_entries()
    entries.reverse()
    return entries


def unlock_ledger() -> dict:
    """Internal tool: returns session context resource content."""
    return {
        "book": str(_book_path()),
        "tool_groups": {
            "operational": [
                "receive_invoice", "pay_invoice", "fund_project",
                "post_interest", "post_transaction",
                "get_account_balance", "list_accounts",
                "list_transactions", "get_transaction",
                "get_project_summary", "get_audit_log",
            ],
        },
    }


def vendors_resource() -> list:
    """Return list of vendors (AP accounts) with current balances."""
    with book_session(_book_path()) as session:
        book = session.book
        try:
            liabilities = get_account(book, "Liabilities")
        except AccountNotFoundError:
            return []

        vendors = []
        for acc in liabilities.get_children():
            if acc.name.startswith("AP — "):
                vendors.append({
                    "name": acc.name[5:],  # strip "AP — " prefix
                    "account": acc.name,
                    "balance": _balance_str(acc.GetBalance()),
                })
        return vendors
