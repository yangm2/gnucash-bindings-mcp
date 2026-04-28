"""Budget CRUD tools (M4.1).

Budgets are stored in a JSONL file alongside the book:
  {book_path}.budget.jsonl

The GnuCash Python bindings do not expose the GncBudget API, so budget data
lives in the JSONL store. Actuals (committed/paid) are computed live from
GnuCash transactions.
"""

import json
import os
import uuid
from decimal import Decimal
from pathlib import Path

from gnucash import Account

import gnucash.gnucash_core_c as gc

from gnucash_mcp.session import (
    AccountNotFoundError,
    book_path,
    book_session,
    get_account,
    get_usd,
)


class RequiresConfirmationError(Exception):
    pass


# ── budget store ──────────────────────────────────────────────────────────────


def _budget_path() -> Path:
    env = os.environ.get("GNUCASH_BUDGET_PATH")
    if env:
        return Path(env)
    book = os.environ.get("GNUCASH_BOOK_PATH", "/data/project.gnucash")
    return Path(book).with_suffix(".budget.jsonl")


def _load_budgets() -> list[dict]:
    path = _budget_path()
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _persist_budgets(budgets: list[dict]) -> None:
    with open(_budget_path(), "w", encoding="utf-8") as f:
        for b in budgets:
            f.write(json.dumps(b) + "\n")


def _get_budget(name: str) -> dict | None:
    return next((b for b in _load_budgets() if b["name"] == name), None)


def _upsert_budget(budget: dict) -> None:
    budgets = _load_budgets()
    idx = next((i for i, b in enumerate(budgets) if b["name"] == budget["name"]), None)
    if idx is not None:
        budgets[idx] = budget
    else:
        budgets.append(budget)
    _persist_budgets(budgets)


# ── account helpers ───────────────────────────────────────────────────────────


def _account_full_path(acc) -> str:
    parts = []
    current = acc
    while current is not None:
        parent = current.get_parent()
        if parent is None:
            break
        parts.append(current.name)
        current = parent
    parts.reverse()
    return ":".join(parts)


def _ensure_account(book, account_path: str) -> None:
    """Create account and any missing ancestors."""
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


def _compute_actuals(book, account_path: str) -> tuple[float, float]:
    """Return (committed, paid) for an expense account.

    committed: sum of positive (DR) splits in the expense account.
    paid: sum of positive (DR) splits in AP accounts linked via invoice transactions.
    """
    try:
        acc = get_account(book, account_path)
    except AccountNotFoundError:
        return 0.0, 0.0

    committed = 0.0
    ap_paths: set[str] = set()

    for split in acc.GetSplitList():
        amt = split.GetAmount().to_double()
        if amt > 0:
            committed += amt
        txn = split.GetParent()
        for s in txn.GetSplitList():
            path = _account_full_path(s.GetAccount())
            if path.startswith("Liabilities:AP — "):
                ap_paths.add(path)

    paid = 0.0
    for ap_path in ap_paths:
        try:
            ap_acc = get_account(book, ap_path)
            for split in ap_acc.GetSplitList():
                amt = split.GetAmount().to_double()
                if amt > 0:
                    paid += amt
        except AccountNotFoundError:
            pass

    return committed, paid


# ── public tools ──────────────────────────────────────────────────────────────


def budget_create(name: str, period_start: str, num_periods: int = 1) -> dict:
    """Create a new budget."""
    if _get_budget(name) is not None:
        raise ValueError(f"Budget {name!r} already exists")
    budget = {
        "name": name,
        "period_start": period_start,
        "num_periods": num_periods,
        "guid": str(uuid.uuid4()),
        "accounts": {},
    }
    _upsert_budget(budget)
    return {"status": "ok", "budget_guid": budget["guid"]}


def budget_list() -> list:
    """List all budgets."""
    return [
        {
            "name": b["name"],
            "num_periods": b["num_periods"],
            "period_start": b["period_start"],
            "guid": b["guid"],
        }
        for b in _load_budgets()
    ]


def budget_set_amount(budget_name: str, account_path: str, amount: str) -> dict:
    """Set budget amount for account_path. Creates the GnuCash account if missing."""
    budget = _get_budget(budget_name)
    if budget is None:
        raise ValueError(f"Budget {budget_name!r} not found")

    with book_session(book_path()) as session:
        try:
            get_account(session.book, account_path)
        except AccountNotFoundError:
            _ensure_account(session.book, account_path)

    budget["accounts"][account_path] = amount
    _upsert_budget(budget)
    return {"status": "ok"}


def budget_get(budget_name: str) -> dict:
    """Return budget detail with committed/paid/variance for each account."""
    budget = _get_budget(budget_name)
    if budget is None:
        raise ValueError(f"Budget {budget_name!r} not found")

    with book_session(book_path()) as session:
        book = session.book
        accounts = []
        for acct_path, budgeted_str in budget["accounts"].items():
            budgeted = Decimal(budgeted_str)
            committed, paid = _compute_actuals(book, acct_path)
            accounts.append(
                {
                    "account": acct_path,
                    "budgeted": f"{budgeted:.2f}",
                    "committed": f"{committed:.2f}",
                    "paid": f"{paid:.2f}",
                    "variance": f"{budgeted - Decimal(str(committed)):.2f}",
                }
            )

    return {"name": budget_name, "accounts": accounts}


def budget_update(budget_name: str, new_name: str | None = None) -> dict:
    """Update budget metadata."""
    budget = _get_budget(budget_name)
    if budget is None:
        raise ValueError(f"Budget {budget_name!r} not found")

    if new_name is not None:
        budgets = _load_budgets()
        for b in budgets:
            if b["name"] == budget_name:
                b["name"] = new_name
        _persist_budgets(budgets)

    return {"status": "ok"}


def budget_delete(budget_name: str, confirm: bool = False) -> dict:
    """Delete a budget. Requires confirm=True."""
    if not confirm:
        raise RequiresConfirmationError(f"Pass confirm=True to delete budget {budget_name!r}.")
    budgets = _load_budgets()
    budgets = [b for b in budgets if b["name"] != budget_name]
    _persist_budgets(budgets)
    return {"status": "ok"}
