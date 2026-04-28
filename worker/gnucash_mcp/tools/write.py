"""Write tools — Tier 1 write MCP tools (M1.6).

Each write tool follows the pattern:
  1. append WAL entry
  2. open session
  3. post transaction with MCP slots
  4. session.save() + session.end()
  5. mark WAL committed (with transaction GUID)

Book path from GNUCASH_BOOK_PATH env var.
"""

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


def _post_transaction(
    book,
    date_str: str,
    description: str,
    splits: list,
    wal_entry: dict | None = None,
    tool_name: str | None = None,
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

        if wal_entry is not None and tool_name is not None:
            txn.SetNotes(f"mcp-wal-id:{wal_entry['id']}|mcp-tool:{tool_name}")

    return txn, txn.GetGUID().to_string()


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

    entry = wal.append(
        "post_transaction",
        {
            "date": date,
            "description": description,
            "splits": splits,
        },
    )

    with book_session(book_path()) as session:
        _, guid = _post_transaction(
            session.book, date, description, splits, entry, "post_transaction"
        )

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


def fund_project(date: str, amount: str, memo: str = "") -> dict:
    """Debit Project Checking, credit Owner Capital."""
    splits = [
        {"account_path": "Assets:Project Checking", "amount": amount, "memo": memo},
        {"account_path": "Equity:Owner Capital", "amount": f"-{amount}", "memo": memo},
    ]
    entry = wal.append("fund_project", {"date": date, "amount": amount, "memo": memo})

    with book_session(book_path()) as session:
        _, guid = _post_transaction(
            session.book,
            date,
            f"Fund project: {memo}" if memo else "Fund project",
            splits,
            entry,
            "fund_project",
        )

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


def receive_invoice(
    date: str, vendor: str, invoice_ref: str, amount: str, expense_account: str
) -> dict:
    """Debit expense account, credit AP — vendor."""
    ap_account = f"Liabilities:AP — {vendor}"
    splits = [
        {"account_path": expense_account, "amount": amount, "memo": invoice_ref},
        {"account_path": ap_account, "amount": f"-{amount}", "memo": invoice_ref},
    ]
    entry = wal.append(
        "receive_invoice",
        {
            "date": date,
            "vendor": vendor,
            "invoice_ref": invoice_ref,
            "amount": amount,
            "expense_account": expense_account,
        },
    )

    with book_session(book_path()) as session:
        _, guid = _post_transaction(
            session.book,
            date,
            f"Invoice {invoice_ref} — {vendor}",
            splits,
            entry,
            "receive_invoice",
        )

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


def pay_invoice(date: str, vendor: str, invoice_ref: str, amount: str) -> dict:
    """Debit AP — vendor, credit Project Checking."""
    ap_account = f"Liabilities:AP — {vendor}"
    splits = [
        {"account_path": ap_account, "amount": amount, "memo": invoice_ref},
        {"account_path": "Assets:Project Checking", "amount": f"-{amount}", "memo": invoice_ref},
    ]
    entry = wal.append(
        "pay_invoice",
        {
            "date": date,
            "vendor": vendor,
            "invoice_ref": invoice_ref,
            "amount": amount,
        },
    )

    with book_session(book_path()) as session:
        _, guid = _post_transaction(
            session.book, date, f"Payment {invoice_ref} — {vendor}", splits, entry, "pay_invoice"
        )

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


class RequiresConfirmationError(Exception):
    pass


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


def update_transaction(
    transaction_guid: str,
    date: str | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> dict:
    """Update metadata on an existing transaction (date, description, notes).

    Does not change splits or amounts.
    """
    entry = wal.append(
        "update_transaction",
        {
            "transaction_guid": transaction_guid,
            "date": date,
            "description": description,
            "notes": notes,
        },
    )

    with book_session(book_path()) as session:
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

    wal.mark_committed(entry["id"])
    return {"status": "ok", "transaction_guid": transaction_guid}


def void_transaction(transaction_guid: str, reason: str) -> dict:
    """Mark a transaction as void, zeroing its balance effect while preserving the audit trail."""
    entry = wal.append(
        "void_transaction",
        {"transaction_guid": transaction_guid, "reason": reason},
    )

    with book_session(book_path()) as session:
        txn = _find_txn_by_guid(session.book, transaction_guid)
        if txn is None:
            raise ValueError(f"Transaction {transaction_guid!r} not found")

        if txn.GetVoidStatus():
            raise ValueError(
                f"Transaction {transaction_guid!r} is already void. "
                "Cannot void a transaction twice."
            )

        txn.Void(reason)

    wal.mark_committed(entry["id"])
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

    entry = wal.append(
        "delete_transaction",
        {"transaction_guid": transaction_guid},
    )

    with book_session(book_path()) as session:
        txn = _find_txn_by_guid(session.book, transaction_guid)
        if txn is None:
            raise ValueError(f"Transaction {transaction_guid!r} not found")

        txn.Destroy()

    wal.mark_committed(entry["id"])
    return {"status": "ok", "deleted_guid": transaction_guid}


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
    entry = wal.append("post_interest", {"month": month, "amount": amount})

    with book_session(book_path()) as session:
        _, guid = _post_transaction(
            session.book, date, f"Interest income — {month}", splits, entry, "post_interest"
        )

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}
