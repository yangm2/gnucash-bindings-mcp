"""ECO (Engineering Change Order) tools (M4.2).

ECO state is persisted in a JSONL file alongside the book:
  {book_path}.eco.jsonl

Each approved ECO posts a GnuCash transaction:
  additive:  DR Expenses:Change Orders:{trade}  /  CR Liabilities:AP — Change Orders
  deductive: DR Liabilities:AP — Change Orders  /  CR Expenses:Change Orders:{trade}

Voiding an approved ECO calls GnuCash's Void() on the transaction (zeros splits)
and reverses the budget adjustment.
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import gnucash.gnucash_core_c as gc
from gnucash import Account, Split

from gnucash_mcp.session import (
    book_path,
    book_session,
    get_account,
    get_usd,
    gnc_decimal,
    new_transaction,
    set_txn_isodate,
)
from gnucash_mcp.tools.budget import _load_budgets, _upsert_budget

_CO_AP_ACCOUNT = "Liabilities:AP — Change Orders"
_CHANGE_ORDERS_ROOT = "Expenses:Change Orders"


# ── ECO store ─────────────────────────────────────────────────────────────────


def _eco_path() -> Path:
    env = os.environ.get("GNUCASH_ECO_PATH")
    if env:
        return Path(env)
    book = os.environ.get("GNUCASH_BOOK_PATH", "/data/project.gnucash")
    return Path(book).with_suffix(".eco.jsonl")


def _load_ecos() -> list[dict]:
    path = _eco_path()
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _persist_ecos(ecos: list[dict]) -> None:
    with open(_eco_path(), "w", encoding="utf-8") as f:
        for e in ecos:
            f.write(json.dumps(e) + "\n")


def _upsert_eco(eco: dict) -> None:
    ecos = _load_ecos()
    idx = next((i for i, e in enumerate(ecos) if e["number"] == eco["number"]), None)
    if idx is not None:
        ecos[idx] = eco
    else:
        ecos.append(eco)
    _persist_ecos(ecos)


def _get_eco(number: str) -> dict | None:
    return next((e for e in _load_ecos() if e["number"] == number), None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── account helpers ───────────────────────────────────────────────────────────


def _change_orders_path(budget_account: str) -> str:
    """Map Construction account to its Change Orders mirror.

    'Expenses:Construction:Electrical' → 'Expenses:Change Orders:Electrical'
    """
    return f"{_CHANGE_ORDERS_ROOT}:{budget_account.split(':')[-1]}"


def _ensure_account(book, account_path: str) -> None:
    usd = get_usd(book)
    parts = account_path.split(":")
    _TYPE_MAP = {
        "Expenses": gc.ACCT_TYPE_EXPENSE,
        "Liabilities": gc.ACCT_TYPE_LIABILITY,
        "Assets": gc.ACCT_TYPE_ASSET,
        "Income": gc.ACCT_TYPE_INCOME,
        "Equity": gc.ACCT_TYPE_EQUITY,
    }
    top_type = _TYPE_MAP.get(parts[0], gc.ACCT_TYPE_EXPENSE)
    current = book.get_root_account()
    for part in parts:
        children = {acc.name: acc for acc in current.get_children()}
        if part in children:
            current = children[part]
        else:
            acc = Account(book)
            acc.SetName(part)
            acc.SetType(top_type)
            acc.SetCommodity(usd)
            current.append_child(acc)
            current = acc


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


def _find_budget_for_account(account_path: str) -> dict | None:
    """Return first JSONL budget record that has an amount for account_path, or None."""
    return next(
        (b for b in _load_budgets() if account_path in b.get("accounts", {})),
        None,
    )


def _adjust_budget_amount(budget_record: dict, account_path: str, delta: Decimal) -> None:
    """Add delta to the budget amount for account_path and persist."""
    current = Decimal(budget_record["accounts"][account_path])
    budget_record["accounts"][account_path] = f"{current + delta:.2f}"
    _upsert_budget(budget_record)


# ── public tools ──────────────────────────────────────────────────────────────


def eco_create(
    number: str,
    description: str,
    direction: str,
    amount: str,
    budget_account: str,
    notes: str = "",
) -> dict:
    """Create a new ECO in pending state. No transaction posted."""
    if _get_eco(number) is not None:
        raise ValueError(f"ECO {number!r} already exists")
    if direction not in ("additive", "deductive"):
        raise ValueError(f"direction must be 'additive' or 'deductive', got {direction!r}")

    eco: dict = {
        "number": number,
        "description": description,
        "direction": direction,
        "amount": amount,
        "budget_account": budget_account,
        "notes": notes,
        "status": "pending",
        "created_at": _now(),
        "approved_at": None,
        "approved_date": None,
        "void_at": None,
        "void_reason": None,
        "transaction_guid": None,
    }
    _upsert_eco(eco)
    return {"status": "ok", "number": number}


def eco_list(status: str | None = None) -> list:
    """List ECOs, optionally filtered by status."""
    ecos = _load_ecos()
    if status is not None:
        ecos = [e for e in ecos if e["status"] == status]
    return [
        {
            "number": e["number"],
            "description": e["description"],
            "direction": e["direction"],
            "amount": e["amount"],
            "budget_account": e["budget_account"],
            "status": e["status"],
        }
        for e in ecos
    ]


def eco_get(number: str) -> dict:
    """Return full ECO detail."""
    eco = _get_eco(number)
    if eco is None:
        raise ValueError(f"ECO {number!r} not found")
    return eco


def eco_approve(number: str, date: str) -> dict:
    """Approve ECO: post Change Orders transaction and update budget amount."""
    eco = _get_eco(number)
    if eco is None:
        raise ValueError(f"ECO {number!r} not found")
    if eco["status"] != "pending":
        raise ValueError(
            f"ECO {number!r} has status {eco['status']!r}; only pending ECOs can be approved"
        )

    co_path = _change_orders_path(eco["budget_account"])
    amount = eco["amount"]
    direction = eco["direction"]

    txn_guid: str
    with book_session(book_path()) as session:
        book = session.book

        _ensure_account(book, co_path)
        _ensure_account(book, _CO_AP_ACCOUNT)

        co_acc = get_account(book, co_path)
        ap_acc = get_account(book, _CO_AP_ACCOUNT)

        gnc_pos = gnc_decimal(amount)
        gnc_neg = gnc_decimal(f"-{amount}")

        with new_transaction(book) as txn:
            set_txn_isodate(txn, date)
            txn.SetDescription(f"ECO {number}: {eco['description']}")
            txn.SetCurrency(get_usd(book))
            txn.SetNotes(f"eco-number:{number}")

            if direction == "additive":
                # DR Change Orders / CR AP
                dr_acc, dr_amt, cr_acc, cr_amt = co_acc, gnc_pos, ap_acc, gnc_neg
            else:
                # DR AP / CR Change Orders
                dr_acc, dr_amt, cr_acc, cr_amt = ap_acc, gnc_pos, co_acc, gnc_neg

            for acc, amt in [(dr_acc, dr_amt), (cr_acc, cr_amt)]:
                s = Split(book)
                s.SetParent(txn)
                s.SetAccount(acc)
                s.SetAmount(amt)
                s.SetValue(amt)

        txn_guid = txn.GetGUID().to_string()

    budget_record = _find_budget_for_account(eco["budget_account"])
    if budget_record is not None:
        delta = Decimal(amount) if direction == "additive" else -Decimal(amount)
        _adjust_budget_amount(budget_record, eco["budget_account"], delta)

    eco["status"] = "approved"
    eco["approved_at"] = _now()
    eco["approved_date"] = date
    eco["transaction_guid"] = txn_guid
    _upsert_eco(eco)

    return {"status": "ok", "number": number, "transaction_guid": txn_guid}


def eco_void(number: str, reason: str) -> dict:
    """Void an ECO. If approved, reverses the transaction and restores budget."""
    eco = _get_eco(number)
    if eco is None:
        raise ValueError(f"ECO {number!r} not found")
    if eco["status"] == "void":
        raise ValueError(f"ECO {number!r} is already void")

    if eco["status"] == "approved":
        txn_guid = eco["transaction_guid"]
        amount = eco["amount"]
        direction = eco["direction"]

        with book_session(book_path()) as session:
            book = session.book

            txn = _find_txn_by_guid(book, txn_guid)
            if txn is not None:
                txn.Void(f"ECO void: {reason}")

        budget_record = _find_budget_for_account(eco["budget_account"])
        if budget_record is not None:
            delta = -Decimal(amount) if direction == "additive" else Decimal(amount)
            _adjust_budget_amount(budget_record, eco["budget_account"], delta)

    eco["status"] = "void"
    eco["void_at"] = _now()
    eco["void_reason"] = reason
    _upsert_eco(eco)

    return {"status": "ok", "number": number}
