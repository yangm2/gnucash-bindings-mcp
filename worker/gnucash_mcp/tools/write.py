"""Write tools — Tier 1 write MCP tools (M1.6).

Each write tool follows the pattern:
  1. append WAL entry
  2. open session
  3. post transaction with MCP slots
  4. session.save() + session.end()
  5. mark WAL committed (with transaction GUID)

Book path from GNUCASH_BOOK_PATH env var.
"""

import os
from decimal import Decimal
from pathlib import Path

from gnucash import Transaction, Split

from gnucash_mcp.session import book_session, get_account, gnc_decimal, set_txn_isodate
from gnucash_mcp import wal


class SplitsImbalanceError(Exception):
    pass


def _book_path() -> Path:
    return Path(os.environ.get("GNUCASH_BOOK_PATH", "/data/project.gnucash"))


def _post_transaction(book, date_str: str, description: str, splits: list):
    """Create and commit a balanced transaction. Returns (txn, guid_str)."""
    txn = Transaction(book)
    txn.BeginEdit()
    set_txn_isodate(txn, date_str)
    txn.SetDescription(description)

    usd = book.get_table().lookup("CURRENCY", "USD")
    txn.SetCurrency(usd)

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

    txn.CommitEdit()
    return txn, txn.GetGUID().to_string()


def _stamp_slots(txn, wal_entry: dict, tool_name: str) -> None:
    """Stamp MCP tracking slots on a transaction (best-effort)."""
    try:
        txn.BeginEdit()
        txn.SetSlot("mcp-wal-id", wal_entry["id"])
        txn.SetSlot("mcp-tool", tool_name)
        txn.SetSlot("mcp-version", "1")
        txn.CommitEdit()
    except Exception:
        pass  # Slots are best-effort; never fail the transaction


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

    with book_session(_book_path()) as session:
        txn, guid = _post_transaction(session.book, date, description, splits)
        _stamp_slots(txn, entry, "post_transaction")

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


def fund_project(date: str, amount: str, memo: str = "") -> dict:
    """Debit Project Checking, credit Owner Capital."""
    splits = [
        {"account_path": "Assets:Project Checking", "amount": amount, "memo": memo},
        {"account_path": "Equity:Owner Capital", "amount": f"-{amount}", "memo": memo},
    ]
    entry = wal.append("fund_project", {"date": date, "amount": amount, "memo": memo})

    with book_session(_book_path()) as session:
        txn, guid = _post_transaction(
            session.book, date, f"Fund project{': ' + memo if memo else ''}", splits
        )
        _stamp_slots(txn, entry, "fund_project")

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

    with book_session(_book_path()) as session:
        txn, guid = _post_transaction(
            session.book, date, f"Invoice {invoice_ref} — {vendor}", splits
        )
        _stamp_slots(txn, entry, "receive_invoice")

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

    with book_session(_book_path()) as session:
        txn, guid = _post_transaction(
            session.book, date, f"Payment {invoice_ref} — {vendor}", splits
        )
        _stamp_slots(txn, entry, "pay_invoice")

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


def post_interest(month: str, amount: str) -> dict:
    """Debit Project Checking, credit Interest Income.

    month: 'YYYY-MM' or 'YYYY-MM-DD'
    """
    date = f"{month}-01" if len(month) == 7 else month
    splits = [
        {"account_path": "Assets:Project Checking", "amount": amount, "memo": f"Interest {month}"},
        {
            "account_path": "Income:Interest Income",
            "amount": f"-{amount}",
            "memo": f"Interest {month}",
        },
    ]
    entry = wal.append("post_interest", {"month": month, "amount": amount})

    with book_session(_book_path()) as session:
        txn, guid = _post_transaction(session.book, date, f"Interest income — {month}", splits)
        _stamp_slots(txn, entry, "post_interest")

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}
