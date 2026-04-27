"""Vendor management tools — M2.2.

Vendor type is stored in the AP account's Description field:
  trade vendors:        "trade:{expense_path}"        e.g. "trade:Expenses:Construction:Electrical"
  professional vendors: "professional:{expense_path}"  e.g. "professional:Expenses:Architecture — Acme Architecture"

This lets vendor_list/vendor_get_details reconstruct full metadata without
scanning the expense tree.
"""

import os
from pathlib import Path

from gnucash import Account
import gnucash.gnucash_core_c as gc

from gnucash_mcp.session import (
    AccountNotFoundError,
    account_balance_float,
    book_session,
    get_account,
    get_txn_isodate,
)


class RequiresConfirmationError(Exception):
    pass


class VendorHasHistoryError(Exception):
    pass


# Valid expense_category values → prefix used in expense account name
EXPENSE_CATEGORIES: dict[str, str] = {
    "Architecture": "Architecture",
    "Structural": "Structural Engineering",
    "MEP": "MEP Consulting",
    "HVAC": "HVAC Engineering",
}

_AP_PREFIX = "AP — "


def _book_path() -> Path:
    return Path(os.environ.get("GNUCASH_BOOK_PATH", "/data/project.gnucash"))


def _ap_name(vendor_name: str) -> str:
    return f"{_AP_PREFIX}{vendor_name}"


def _expense_account_name(category: str, vendor_name: str) -> str:
    return f"{EXPENSE_CATEGORIES[category]} — {vendor_name}"


def _get_usd(book):
    return book.get_table().lookup("CURRENCY", "USD")


def _read_ap(book, vendor_name: str) -> Account:
    """Return the AP account for vendor_name, raising AccountNotFoundError if absent."""
    return get_account(book, f"Liabilities:{_ap_name(vendor_name)}")


def _parse_desc(ap_acc) -> tuple[str, str]:
    """Return (type, path) parsed from the AP account description."""
    desc = ap_acc.GetDescription()
    if desc.startswith("trade:"):
        return "trade", desc[6:]
    if desc.startswith("professional:"):
        return "professional", desc[13:]
    return "unknown", ""


def _create_ap_account(book, ap_name: str, liabilities, usd, description: str) -> None:
    ap = Account(book)
    ap.SetName(ap_name)
    ap.SetType(gc.ACCT_TYPE_PAYABLE)
    ap.SetCommodity(usd)
    ap.SetDescription(description)
    liabilities.append_child(ap)


def _ensure_expense_account(book, expense_name: str, expenses) -> None:
    existing = {acc.name for acc in expenses.get_children()}
    if expense_name not in existing:
        usd = _get_usd(book)
        exp_acc = Account(book)
        exp_acc.SetName(expense_name)
        exp_acc.SetType(gc.ACCT_TYPE_EXPENSE)
        exp_acc.SetCommodity(usd)
        expenses.append_child(exp_acc)


# ── public tools ──────────────────────────────────────────────────────────────


def vendor_add(
    name: str,
    trade: str | None = None,
    expense_category: str | None = None,
) -> dict:
    """Add a new vendor. Exactly one of trade or expense_category must be provided."""
    if trade and expense_category:
        raise ValueError("Specify exactly one of trade or expense_category, not both")
    if not trade and not expense_category:
        raise ValueError("Specify exactly one of trade or expense_category")
    if expense_category and expense_category not in EXPENSE_CATEGORIES:
        raise ValueError(
            f"Invalid expense_category {expense_category!r}. Valid: {sorted(EXPENSE_CATEGORIES)}"
        )

    with book_session(_book_path()) as session:
        book = session.book
        liabilities = get_account(book, "Liabilities")
        existing_ap = {acc.name for acc in liabilities.get_children()}
        ap_name = _ap_name(name)

        if trade:
            get_account(book, trade)  # raises AccountNotFoundError if path missing
            if ap_name not in existing_ap:
                _create_ap_account(book, ap_name, liabilities, _get_usd(book), f"trade:{trade}")
        else:
            expense_name = _expense_account_name(expense_category, name)  # type: ignore[arg-type]
            expense_path = f"Expenses:{expense_name}"
            usd = _get_usd(book)
            if ap_name not in existing_ap:
                _create_ap_account(book, ap_name, liabilities, usd, f"professional:{expense_path}")
            _ensure_expense_account(book, expense_name, get_account(book, "Expenses"))

    return {"status": "ok", "ap_path": f"Liabilities:{ap_name}"}


def vendor_list() -> list[dict]:
    """List all vendors with type, paths, and current AP balance."""
    with book_session(_book_path()) as session:
        book = session.book
        try:
            liabilities = get_account(book, "Liabilities")
        except AccountNotFoundError:
            return []

        vendors = []
        for acc in liabilities.get_children():
            if not acc.name.startswith(_AP_PREFIX):
                continue
            vendor_name = acc.name[len(_AP_PREFIX) :]
            vtype, path = _parse_desc(acc)
            balance = f"{account_balance_float(acc, negate=True):.2f}"
            entry: dict = {
                "name": vendor_name,
                "type": vtype,
                "ap_path": f"Liabilities:{acc.name}",
                "balance": balance,
            }
            if vtype == "trade":
                entry["trade_path"] = path
            else:
                entry["expense_path"] = path
            vendors.append(entry)

    return vendors


def vendor_get_details(name: str) -> dict:
    """Return full details and transaction history for a named vendor."""
    with book_session(_book_path()) as session:
        book = session.book
        try:
            ap_acc = _read_ap(book, name)
        except AccountNotFoundError:
            return {"error": f"Vendor {name!r} not found"}

        vtype, path = _parse_desc(ap_acc)
        balance = f"{account_balance_float(ap_acc, negate=True):.2f}"

        txns = []
        for split in ap_acc.GetSplitList():
            txn = split.GetParent()
            txns.append(
                {
                    "guid": txn.GetGUID().to_string(),
                    "date": get_txn_isodate(txn),
                    "description": txn.GetDescription(),
                    "amount": f"{split.GetAmount().to_double():.2f}",
                }
            )

        result: dict = {
            "name": name,
            "type": vtype,
            "ap_path": f"Liabilities:{_ap_name(name)}",
            "balance": balance,
            "transactions": txns,
        }
        if vtype == "trade":
            result["trade_path"] = path
        else:
            result["expense_path"] = path

    return result


def vendor_rename(old_name: str, new_name: str) -> dict:
    """Rename a vendor. For professional vendors, renames both AP and expense accounts."""
    with book_session(_book_path()) as session:
        book = session.book
        try:
            ap_acc = _read_ap(book, old_name)
        except AccountNotFoundError:
            raise AccountNotFoundError(f"Vendor {old_name!r} not found")

        vtype, path = _parse_desc(ap_acc)

        if vtype == "professional":
            try:
                exp_acc = get_account(book, path)
                prefix = exp_acc.name.split(" — ")[0]
                new_exp_name = f"{prefix} — {new_name}"
                exp_acc.SetName(new_exp_name)
                ap_acc.SetDescription(f"professional:Expenses:{new_exp_name}")
            except AccountNotFoundError:
                pass

        ap_acc.SetName(_ap_name(new_name))

    return {"status": "ok", "old_name": old_name, "new_name": new_name}


def vendor_update(
    name: str,
    trade: str | None = None,
    expense_category: str | None = None,
) -> dict:
    """Change the expense coding for a vendor. Exactly one of trade or expense_category required.

    For professional vendors: creates a new expense account under the new category;
    the old expense account is left in place (historical transactions unaffected).
    For trade vendors: updates the stored trade path.
    """
    if trade and expense_category:
        raise ValueError("Specify exactly one of trade or expense_category, not both")
    if not trade and not expense_category:
        raise ValueError("Specify exactly one of trade or expense_category")
    if expense_category and expense_category not in EXPENSE_CATEGORIES:
        raise ValueError(
            f"Invalid expense_category {expense_category!r}. Valid: {sorted(EXPENSE_CATEGORIES)}"
        )

    with book_session(_book_path()) as session:
        book = session.book
        try:
            ap_acc = _read_ap(book, name)
        except AccountNotFoundError:
            raise AccountNotFoundError(f"Vendor {name!r} not found")

        if trade:
            get_account(book, trade)  # raises AccountNotFoundError if path missing
            ap_acc.SetDescription(f"trade:{trade}")
        else:
            expense_name = _expense_account_name(expense_category, name)  # type: ignore[arg-type]
            _ensure_expense_account(book, expense_name, get_account(book, "Expenses"))
            ap_acc.SetDescription(f"professional:Expenses:{expense_name}")

    return {"status": "ok", "name": name}


def vendor_delete(name: str, confirm: bool = False) -> dict:
    """Delete a vendor. Requires confirm=True. Fails if AP account has any transactions."""
    if not confirm:
        raise RequiresConfirmationError(
            f"Pass confirm=True to delete vendor {name!r}. "
            "Vendors with transaction history cannot be deleted."
        )

    with book_session(_book_path()) as session:
        book = session.book
        try:
            ap_acc = _read_ap(book, name)
        except AccountNotFoundError:
            raise AccountNotFoundError(f"Vendor {name!r} not found")

        if ap_acc.GetSplitList():
            raise VendorHasHistoryError(
                f"Vendor {name!r} has AP transaction history and cannot be deleted. "
                "Leave the AP account in place; zero-balance AP accounts are invisible "
                "in aging reports."
            )

        vtype, path = _parse_desc(ap_acc)

        if vtype == "professional":
            try:
                exp_acc = get_account(book, path)
                exp_acc.Destroy()
            except AccountNotFoundError:
                pass

        ap_acc.Destroy()

    return {"status": "ok", "deleted": name}


def vendor_guide_resource() -> str:
    """Return the vendor setup guide (gnucash://vendor-guide)."""
    from gnucash_mcp.tools.book import book_get_account_tree

    trade_accounts = book_get_account_tree("Expenses:Construction")
    trade_paths = [
        f"  Expenses:Construction:{a['name']}" for a in trade_accounts if "error" not in a
    ]
    trade_section = "\n".join(trade_paths) if trade_paths else "  (none)"

    return f"""\
# GnuCash Vendor Guide

## vendor_add

Add a new vendor/subcontractor. Exactly one of `trade` or `expense_category` required.

### Trade vendors (construction subcontractors)

Pass the full path of an existing trade expense account.
Creates only `Liabilities:AP — {{name}}`; the trade expense account is shared.

  vendor_add("Pacific Crest Electrical", trade="Expenses:Construction:Electrical")

Current trade accounts:
{trade_section}

### Professional vendors (architects, engineers)

Pass one of the valid `expense_category` values.
Creates both `Liabilities:AP — {{name}}` and a dedicated expense account.

  vendor_add("Hillside Architecture", expense_category="Architecture")

Valid expense_category values:
  Architecture     → Expenses:Architecture — {{name}}
  Structural       → Expenses:Structural Engineering — {{name}}
  MEP              → Expenses:MEP Consulting — {{name}}
  HVAC             → Expenses:HVAC Engineering — {{name}}

## vendor_rename

Rename a vendor. For professional vendors, renames both AP and expense accounts atomically.
Existing transactions are unaffected (accounts tracked by GUID, not name).

## vendor_update

Change expense coding for a vendor.
For professional vendors: creates a new expense account; old account preserved for history.
For trade vendors: reassigns to a different trade account path.

## vendor_delete

Delete a vendor. Requires confirm=True.
Fails if the AP account has any transaction history — leave those vendors in place.
"""
