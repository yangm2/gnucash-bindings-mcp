"""Book management tools — M2.1.

Tools for creating, renaming, moving, and deleting accounts, verifying the
chart of accounts structure, and posting opening balance transactions.
"""

from gnucash import Account, Transaction, Split

import gnucash.gnucash_core_c as gc

from gnucash_mcp.session import (
    AccountNotFoundError,
    book_path,
    book_session,
    get_account,
    get_usd,
    gnc_decimal,
    set_txn_isodate,
)
from gnucash_mcp import wal

# Supported account type strings → GnuCash integer constants
ACCOUNT_TYPES: dict[str, int] = {
    "ASSET": gc.ACCT_TYPE_ASSET,
    "BANK": gc.ACCT_TYPE_BANK,
    "CASH": gc.ACCT_TYPE_CASH,
    "CREDIT": gc.ACCT_TYPE_CREDIT,
    "EQUITY": gc.ACCT_TYPE_EQUITY,
    "EXPENSE": gc.ACCT_TYPE_EXPENSE,
    "INCOME": gc.ACCT_TYPE_INCOME,
    "LIABILITY": gc.ACCT_TYPE_LIABILITY,
    "PAYABLE": gc.ACCT_TYPE_PAYABLE,
    "RECEIVABLE": gc.ACCT_TYPE_RECEIVABLE,
}

# Opening balance equity account created automatically when needed
_OPENING_BALANCES_PATH = "Equity:Opening Balances"


class AccountHasTransactionsError(Exception):
    pass


def _ensure_opening_balances(book) -> Account:
    """Return Equity:Opening Balances, creating it if absent."""
    try:
        return get_account(book, _OPENING_BALANCES_PATH)
    except AccountNotFoundError:
        equity = get_account(book, "Equity")
        acc = Account(book)
        acc.SetName("Opening Balances")
        acc.SetType(gc.ACCT_TYPE_EQUITY)
        acc.SetCommodity(get_usd(book))
        equity.append_child(acc)
        return acc


# ── public tools ──────────────────────────────────────────────────────────────


def book_add_account(
    name: str,
    parent_path: str,
    account_type: str,
    commodity: str = "USD",
) -> dict:
    """Add account to chart of accounts. Idempotent: no-op if account already exists."""
    if account_type not in ACCOUNT_TYPES:
        raise ValueError(
            f"Invalid account_type {account_type!r}. Valid values: {sorted(ACCOUNT_TYPES)}"
        )

    with book_session(book_path()) as session:
        book = session.book
        parent = get_account(book, parent_path)  # raises AccountNotFoundError if missing

        existing = {acc.name for acc in parent.get_children()}
        if name not in existing:
            usd = book.get_table().lookup("CURRENCY", commodity)
            acc = Account(book)
            acc.SetName(name)
            acc.SetType(ACCOUNT_TYPES[account_type])
            acc.SetCommodity(usd)
            parent.append_child(acc)

    return {"status": "ok", "path": f"{parent_path}:{name}"}


def book_get_account_tree(parent_path: str = "") -> list[dict]:
    """Return direct children of parent_path as a flat list of account dicts.

    Pass parent_path="" to get top-level accounts.
    """
    with book_session(book_path()) as session:
        book = session.book
        if parent_path == "":
            parent = book.get_root_account()
        else:
            try:
                parent = get_account(book, parent_path)
            except AccountNotFoundError as exc:
                return [{"error": str(exc)}]

        result = []
        for child in parent.get_children():
            result.append(
                {
                    "name": child.name,
                    "type": gc.xaccAccountGetTypeStr(child.GetType()),
                    "balance": f"{child.GetBalance().to_double():.2f}",
                    "path": f"{parent_path}:{child.name}" if parent_path else child.name,
                }
            )

    return result


def book_verify_structure() -> dict:
    """Compare live chart of accounts against the expected MC-6 structure.

    Returns {"ok": bool, "missing": [...], "unexpected": [...]}.
    Uses the same CHART constant as init_book.py.
    """
    from gnucash_mcp.chart import CHART

    def _expected_paths(spec: dict, prefix: str = "") -> set[str]:
        paths: set[str] = set()
        for name, (_, _, children) in spec.items():
            path = f"{prefix}:{name}" if prefix else name
            paths.add(path)
            if children:
                paths |= _expected_paths(children, path)
        return paths

    def _live_paths(acc, prefix: str = "") -> set[str]:
        paths: set[str] = set()
        for child in acc.get_children():
            path = f"{prefix}:{child.name}" if prefix else child.name
            paths.add(path)
            paths |= _live_paths(child, path)
        return paths

    expected = _expected_paths(CHART)

    with book_session(book_path()) as session:
        live = _live_paths(session.book.get_root_account())

    missing = sorted(expected - live)
    unexpected = sorted(live - expected)

    return {"ok": len(missing) == 0, "missing": missing, "unexpected": unexpected}


def book_set_opening_balance(account_path: str, amount: str, date: str) -> dict:
    """Post an opening balance transaction, crediting Equity:Opening Balances."""
    entry = wal.append(
        "book_set_opening_balance",
        {"account_path": account_path, "amount": amount, "date": date},
    )

    with book_session(book_path()) as session:
        book = session.book
        target = get_account(book, account_path)
        ob_equity = _ensure_opening_balances(book)

        usd = get_usd(book)
        txn = Transaction(book)
        txn.BeginEdit()
        set_txn_isodate(txn, date)
        txn.SetDescription(f"Opening balance — {account_path}")
        txn.SetCurrency(usd)

        debit = Split(book)
        debit.SetParent(txn)
        debit.SetAccount(target)
        amt = gnc_decimal(amount)
        debit.SetAmount(amt)
        debit.SetValue(amt)

        neg = gnc_decimal(f"-{amount}")
        credit = Split(book)
        credit.SetParent(txn)
        credit.SetAccount(ob_equity)
        credit.SetAmount(neg)
        credit.SetValue(neg)

        txn.CommitEdit()
        guid = txn.GetGUID().to_string()

    wal.mark_committed(entry["id"], transaction_guid=guid)
    return {"status": "ok", "transaction_guid": guid, "wal_id": entry["id"]}


def book_rename_account(account_path: str, new_name: str) -> dict:
    """Rename an account leaf. Does not affect existing transactions."""
    with book_session(book_path()) as session:
        acc = get_account(session.book, account_path)
        acc.SetName(new_name)

    return {"status": "ok", "old_path": account_path, "new_name": new_name}


def book_move_account(account_path: str, new_parent_path: str) -> dict:
    """Move an account to a new parent. Existing transactions are unaffected."""
    with book_session(book_path()) as session:
        book = session.book
        acc = get_account(book, account_path)
        new_parent = get_account(book, new_parent_path)
        old_parent = acc.get_parent()
        old_parent.remove_child(acc)
        new_parent.append_child(acc)
        new_path = f"{new_parent_path}:{acc.name}"

    return {"status": "ok", "new_path": new_path}


def book_delete_account(account_path: str, require_zero_balance: bool = True) -> dict:
    """Delete an account.

    Raises AccountHasTransactionsError if the account has any splits and
    require_zero_balance=True.
    """
    with book_session(book_path()) as session:
        book = session.book
        acc = get_account(book, account_path)

        if require_zero_balance and acc.GetSplitList():
            raise AccountHasTransactionsError(
                f"Account {account_path!r} has transaction history and cannot be deleted. "
                "Set require_zero_balance=False to override, or leave the account in place."
            )

        acc.Destroy()

    return {"status": "ok", "deleted_path": account_path}


# ── resource handlers ─────────────────────────────────────────────────────────


def book_setup_guide_resource() -> str:
    """Return the static book setup guide (gnucash://book-setup-guide)."""
    return """\
# GnuCash Book Setup Guide

## book_add_account

Add a new account to the chart of accounts.

Parameters:
  name          – leaf account name (e.g. "Landscaping")
  parent_path   – colon-separated path to the parent account (e.g. "Expenses:Construction")
  account_type  – one of: ASSET, BANK, CASH, CREDIT, EQUITY, EXPENSE, INCOME,
                  LIABILITY, PAYABLE, RECEIVABLE
  commodity     – currency code, default "USD"

This call is idempotent: if an account with the same name already exists under
the parent, the existing account is returned unchanged.

Raises:
  AccountNotFoundError  – parent_path does not exist
  ValueError            – account_type is not a recognised value

## book_verify_structure

Compare the live chart of accounts against the expected MC-6 structure.
Returns {"ok": bool, "missing": [...], "unexpected": [...]}.
Run this after bulk account creation to confirm correctness before posting
any transactions.

## Chart of accounts naming conventions (MC-6)

- Trade subcontractor AP:    Liabilities:AP — {vendor name}
- Professional fee AP:       Liabilities:AP — {vendor name}
- Professional fee expense:  Expenses:{category} — {vendor name}
  Valid categories: Architecture, Structural Engineering, MEP Consulting,
                    HVAC Engineering
- Construction trade:        Expenses:Construction:{trade}
- Change orders:             Expenses:Change Orders:{trade}
- Permits:                   Expenses:Permits and Fees (direct, no vendor)
"""


def expected_chart_resource() -> str:
    """Return the expected MC-6 chart structure as text (gnucash://expected-chart)."""
    from gnucash_mcp.chart import CHART
    import json

    def _chart_to_dict(spec: dict) -> dict:
        result = {}
        for name, (acct_type, _, children) in spec.items():
            result[name] = {
                "type": acct_type,
                **({"children": _chart_to_dict(children)} if children else {}),
            }
        return result

    return json.dumps(_chart_to_dict(CHART), indent=2)
