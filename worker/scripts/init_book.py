#!/usr/bin/env python3
"""
M1.2: Initialize GnuCash book with full chart of accounts (MC-6).

Idempotent: running twice does not create duplicate accounts.
Creates or opens book at GNUCASH_BOOK_PATH environment variable.

Account creation pattern (GnuCash 5.14):
    acc = Account(book)
    acc.SetName("Name")
    acc.SetType(gc.ACCT_TYPE_ASSET)   # integer enum from gnucash_core_c
    parent.append_child(acc)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gnucash_mcp.session import book_session
from gnucash import Account, GnuCashBackendException
import gnucash.gnucash_core_c as gc


# MC-6 chart of accounts structure.
# Leaf values: (account_type_int, description | None)
# Dict values: (account_type_int, description | None, children_dict)

ASSET    = gc.ACCT_TYPE_ASSET
BANK     = gc.ACCT_TYPE_BANK
LIAB     = gc.ACCT_TYPE_LIABILITY
PAYABLE  = gc.ACCT_TYPE_PAYABLE
EQUITY   = gc.ACCT_TYPE_EQUITY
INCOME   = gc.ACCT_TYPE_INCOME
EXPENSE  = gc.ACCT_TYPE_EXPENSE

# (type, description, children)  — children is None for leaf accounts
CHART = {
    "Assets": (ASSET, None, {
        "Project Checking": (BANK, "First Project Bank", None),
    }),
    "Liabilities": (LIAB, None, {
        "AP — Acme Architecture":  (PAYABLE, None, None),
        "AP — Peak Structural":    (PAYABLE, None, None),
        "AP — Meridian MEP":       (PAYABLE, None, None),
        "AP — Summit HVAC":        (PAYABLE, None, None),
    }),
    "Equity": (EQUITY, None, {
        "Owner Capital": (EQUITY, "First Project Bank", None),
    }),
    "Income": (INCOME, None, {
        "Interest Income": (INCOME, "Project Account", None),
    }),
    "Expenses": (EXPENSE, None, {
        "Architecture — Acme Architecture":      (EXPENSE, None, None),
        "Structural Engineering — Peak Structural": (EXPENSE, None, None),
        "MEP Consulting — Meridian MEP":         (EXPENSE, None, None),
        "HVAC Engineering — Summit HVAC":        (EXPENSE, None, None),
        "Permits and Fees":                      (EXPENSE, None, None),
        "Construction": (EXPENSE, None, {
            "Demo":             (EXPENSE, None, None),
            "Framing":          (EXPENSE, None, None),
            "Electrical":       (EXPENSE, None, None),
            "Plumbing":         (EXPENSE, None, None),
            "HVAC":             (EXPENSE, None, None),
            "Tile":             (EXPENSE, None, None),
            "Finish Carpentry": (EXPENSE, None, None),
            "Painting":         (EXPENSE, None, None),
            "Contractor Fee":   (EXPENSE, None, None),
        }),
        "Change Orders": (EXPENSE, None, {
            "Demo":       (EXPENSE, None, None),
            "Electrical": (EXPENSE, None, None),
            "New Scope":  (EXPENSE, None, None),
        }),
    }),
}


def _existing_children(parent):
    """Return a dict of {name: Account} for direct children of parent."""
    return {acc.name: acc for acc in parent.get_children()}


def _get_usd(book):
    """Return the USD GncCommodity from the book's commodity table."""
    table = book.get_table()
    return table.lookup("CURRENCY", "USD")


def ensure_subtree(book, parent, spec, usd=None):
    """Recursively ensure all accounts in spec exist under parent.

    spec is a dict: {name: (type_int, description, children_spec | None)}
    Returns count of accounts created.
    """
    if usd is None:
        usd = _get_usd(book)

    created = 0
    existing = _existing_children(parent)

    for name, (acct_type, description, children) in spec.items():
        if name in existing:
            acc = existing[name]
        else:
            acc = Account(book)
            acc.SetName(name)
            acc.SetType(acct_type)
            acc.SetCommodity(usd)
            if description:
                acc.SetDescription(description)
            parent.append_child(acc)
            created += 1

        if children:
            created += ensure_subtree(book, acc, children, usd=usd)

    return created


def count_accounts(acc):
    """Recursively count accounts under acc (including acc itself)."""
    return 1 + sum(count_accounts(child) for child in acc.get_children())


def main():
    book_path = os.environ.get("GNUCASH_BOOK_PATH")
    if not book_path:
        print("ERROR: GNUCASH_BOOK_PATH not set", file=sys.stderr)
        sys.exit(1)

    book_path = Path(book_path)
    is_new = not book_path.exists()

    try:
        with book_session(book_path, is_new=is_new) as session:
            book = session.book
            root = book.get_root_account()

            created = ensure_subtree(book, root, CHART)

            total = count_accounts(root) - 1  # exclude root itself

            action = "Created" if is_new else "Opened"
            print(f"✓ {action} book: {book_path}")
            if created:
                print(f"  + {created} account(s) added")
            print(f"  {total} account(s) total")

    except GnuCashBackendException as exc:
        print(f"ERROR: GnuCash backend: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
