"""MC-6 chart of accounts definition and helpers.

CHART is the canonical account structure for the construction project ledger.
Both init_book.py and book_verify_structure() use this as the source of truth.
"""

import gnucash.gnucash_core_c as gc
from gnucash import Account

ASSET = gc.ACCT_TYPE_ASSET
BANK = gc.ACCT_TYPE_BANK
LIAB = gc.ACCT_TYPE_LIABILITY
PAYABLE = gc.ACCT_TYPE_PAYABLE
EQUITY = gc.ACCT_TYPE_EQUITY
INCOME = gc.ACCT_TYPE_INCOME
EXPENSE = gc.ACCT_TYPE_EXPENSE

# (type, description, children)  — children is None for leaf accounts
CHART: dict = {
    "Assets": (
        ASSET,
        None,
        {
            "Project Checking": (BANK, "First Project Bank", None),
        },
    ),
    "Liabilities": (
        LIAB,
        None,
        {
            "AP — Acme Architecture": (PAYABLE, None, None),
            "AP — Peak Structural": (PAYABLE, None, None),
            "AP — Meridian MEP": (PAYABLE, None, None),
            "AP — Summit HVAC": (PAYABLE, None, None),
        },
    ),
    "Equity": (
        EQUITY,
        None,
        {
            "Owner Capital": (EQUITY, "First Project Bank", None),
        },
    ),
    "Income": (
        INCOME,
        None,
        {
            "Interest Income": (INCOME, "Project Account", None),
        },
    ),
    "Expenses": (
        EXPENSE,
        None,
        {
            "Architecture — Acme Architecture": (EXPENSE, None, None),
            "Structural Engineering — Peak Structural": (EXPENSE, None, None),
            "MEP Consulting — Meridian MEP": (EXPENSE, None, None),
            "HVAC Engineering — Summit HVAC": (EXPENSE, None, None),
            "Permits and Fees": (EXPENSE, None, None),
            "Construction": (
                EXPENSE,
                None,
                {
                    "Demo": (EXPENSE, None, None),
                    "Framing": (EXPENSE, None, None),
                    "Electrical": (EXPENSE, None, None),
                    "Plumbing": (EXPENSE, None, None),
                    "HVAC": (EXPENSE, None, None),
                    "Tile": (EXPENSE, None, None),
                    "Finish Carpentry": (EXPENSE, None, None),
                    "Painting": (EXPENSE, None, None),
                    "Contractor Fee": (EXPENSE, None, None),
                },
            ),
            "Change Orders": (
                EXPENSE,
                None,
                {
                    "Demo": (EXPENSE, None, None),
                    "Electrical": (EXPENSE, None, None),
                    "New Scope": (EXPENSE, None, None),
                },
            ),
        },
    ),
}


def _get_usd(book):
    return book.get_table().lookup("CURRENCY", "USD")


def _existing_children(parent) -> dict:
    return {acc.name: acc for acc in parent.get_children()}


def ensure_subtree(book, parent, spec: dict, usd=None) -> int:
    """Recursively ensure all accounts in spec exist under parent.

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


def count_accounts(acc) -> int:
    """Recursively count accounts under acc (including acc itself)."""
    return 1 + sum(count_accounts(child) for child in acc.get_children())
