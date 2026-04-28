"""Write tools — Tier 1 write MCP tools (M1.6).

Each write tool uses one of two private helpers:

  _wal_post(tool, payload, date, description, splits) -> dict
    For tools that post a new balanced transaction. Handles WAL append,
    book session, _post_transaction, and WAL commit as a single unit.

  _wal_session(tool, payload, transaction_guid) -> contextmanager[Session]
    For tools that modify an existing transaction. Handles WAL append and
    WAL commit around a book session; guid is the input transaction's guid.

Book path from GNUCASH_BOOK_PATH env var.
"""

from contextlib import contextmanager
from decimal import Decimal

from gnucash import Split

from gnucash_mcp.session import (
    book_path,
    book_session,
    edit_transaction,
    new_transaction,
    get_account,
    get_usd,
    gnc_decimal,
    set_txn_isodate,
)
from gnucash_mcp import wal


class SplitsImbalanceError(Exception):
    pass


class RequiresConfirmationError(Exception):
    pass


def _post_transaction(
    book, date_str: str, description: str, splits: list, wal_entry: dict, tool_name: str
):
    with new_transaction(book) as txn:
        set_txn_isodate(txn, date_str)
        txn.SetDescription(description)
        txn.SetCurrency(get_usd(book))

        for spec in splits:
            acc = get_account(book, spec["account_path"])
            split = Split(book)
            split.SetParent(txn)
            split.SetAccount(acc)
            amount = gnc_decimal(spec["amount"])
            split.SetAmount(amount)
            split.SetValue(amount)
            if spec.get("memo"):
                split.SetMemo(spec["memo"])

        txn.SetNotes(f"mcp-wal-id:{wal_entry['id']}|mcp-tool:{tool_name}")

    return txn, txn.GetGUID().to_string()


def _wal_post(tool: str, payload: dict, date: str, description: str, splits: list) -> dict:
    """WAL append → book session → post balanced transaction → WAL commit."""
    entry = wal.append(tool, payload)
    with book_session(book_path()) as session:
        _, guid = _post_transaction(session.book, date, description, splits, entry, tool)
    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


@contextmanager
def _wal_session(tool: str, payload: dict, transaction_guid: str):
    """WAL append → book session → WAL commit. For modifying an existing transaction."""
    entry = wal.append(tool, payload)
    with book_session(book_path()) as session:
        yield session
    wal.mark_committed(entry["id"], transaction_guid=transaction_guid)


def _find_txn_by_guid(book, guid_str: str):
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


# ── public tools ──────────────────────────────────────────────────────────────


def post_transaction(date: str, description: str, splits: list) -> dict:
    """Post an arbitrary balanced transaction.

    splits: [{"account_path": str, "amount": str, "memo": str (optional)}]
    Amounts must sum to zero.
    """
    total = sum(Decimal(s["amount"]) for s in splits)
    if total != 0:
        raise SplitsImbalanceError(
            f"Splits must sum to zero; got {total}. Amounts: {[s['amount'] for s in splits]}"
        )
    return _wal_post(
        "post_transaction",
        {"date": date, "description": description, "splits": splits},
        date,
        description,
        splits,
    )


def fund_project(date: str, amount: str, memo: str = "") -> dict:
    """Debit Project Checking, credit Owner Capital."""
    splits = [
        {"account_path": "Assets:Project Checking", "amount": amount, "memo": memo},
        {"account_path": "Equity:Owner Capital", "amount": f"-{amount}", "memo": memo},
    ]
    return _wal_post(
        "fund_project",
        {"date": date, "amount": amount, "memo": memo},
        date,
        f"Fund project: {memo}" if memo else "Fund project",
        splits,
    )


def receive_invoice(
    date: str, vendor: str, invoice_ref: str, amount: str, expense_account: str
) -> dict:
    """Debit expense account, credit AP — vendor."""
    splits = [
        {"account_path": expense_account, "amount": amount, "memo": invoice_ref},
        {"account_path": f"Liabilities:AP — {vendor}", "amount": f"-{amount}", "memo": invoice_ref},
    ]
    return _wal_post(
        "receive_invoice",
        {
            "date": date,
            "vendor": vendor,
            "invoice_ref": invoice_ref,
            "amount": amount,
            "expense_account": expense_account,
        },
        date,
        f"Invoice {invoice_ref} — {vendor}",
        splits,
    )


def pay_invoice(date: str, vendor: str, invoice_ref: str, amount: str) -> dict:
    """Debit AP — vendor, credit Project Checking."""
    splits = [
        {"account_path": f"Liabilities:AP — {vendor}", "amount": amount, "memo": invoice_ref},
        {"account_path": "Assets:Project Checking", "amount": f"-{amount}", "memo": invoice_ref},
    ]
    return _wal_post(
        "pay_invoice",
        {"date": date, "vendor": vendor, "invoice_ref": invoice_ref, "amount": amount},
        date,
        f"Payment {invoice_ref} — {vendor}",
        splits,
    )


def post_interest(month: str, amount: str) -> dict:
    """Debit Project Checking, credit Interest Income.

    month: 'YYYY-MM' or 'YYYY-MM-DD'
    """
    date = f"{month}-01" if len(month) == 7 else month
    memo = f"Interest {month}"
    splits = [
        {"account_path": "Assets:Project Checking", "amount": amount, "memo": memo},
        {"account_path": "Income:Interest Income", "amount": f"-{amount}", "memo": memo},
    ]
    return _wal_post(
        "post_interest",
        {"month": month, "amount": amount},
        date,
        f"Interest income — {month}",
        splits,
    )


def update_transaction(
    transaction_guid: str,
    date: str | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> dict:
    """Update metadata on an existing transaction (date, description, notes).

    Does not change splits or amounts.
    """
    payload = {
        "transaction_guid": transaction_guid,
        "date": date,
        "description": description,
        "notes": notes,
    }
    with _wal_session("update_transaction", payload, transaction_guid) as session:
        txn = _find_txn_by_guid(session.book, transaction_guid)
        if txn is None:
            raise ValueError(f"Transaction {transaction_guid!r} not found")
        with edit_transaction(txn):
            if date is not None:
                set_txn_isodate(txn, date)
            if description is not None:
                txn.SetDescription(description)
            if notes is not None:
                txn.SetNotes(notes)
    return {"status": "ok", "transaction_guid": transaction_guid}


def void_transaction(transaction_guid: str, reason: str) -> dict:
    """Mark a transaction as void, zeroing its balance effect while preserving the audit trail."""
    with _wal_session(
        "void_transaction",
        {"transaction_guid": transaction_guid, "reason": reason},
        transaction_guid,
    ) as session:
        txn = _find_txn_by_guid(session.book, transaction_guid)
        if txn is None:
            raise ValueError(f"Transaction {transaction_guid!r} not found")
        if txn.GetVoidStatus():
            raise ValueError(
                f"Transaction {transaction_guid!r} is already void. "
                "Cannot void a transaction twice."
            )
        txn.Void(reason)
    return {"status": "ok", "transaction_guid": transaction_guid}


def delete_transaction(transaction_guid: str, confirm: bool = False) -> dict:
    """Permanently delete a transaction. Requires confirm=True.

    Prefer void_transaction for accounting corrections; use delete only for
    duplicate or test transactions with no accounting significance.
    """
    if not confirm:
        raise RequiresConfirmationError(
            f"Pass confirm=True to delete transaction {transaction_guid!r}. "
            "Use void_transaction instead for audit trail preservation."
        )
    with _wal_session(
        "delete_transaction", {"transaction_guid": transaction_guid}, transaction_guid
    ) as session:
        txn = _find_txn_by_guid(session.book, transaction_guid)
        if txn is None:
            raise ValueError(f"Transaction {transaction_guid!r} not found")
        txn.Destroy()
    return {"status": "ok", "deleted_guid": transaction_guid}
