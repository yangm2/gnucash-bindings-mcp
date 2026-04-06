#!/usr/bin/env python3
"""
M1.2: Initialize GnuCash book with full chart of accounts (MC-6).

Idempotent: running twice does not create duplicate accounts.
Creates or opens book at GNUCASH_BOOK_PATH environment variable.
"""

import os
import sys
from pathlib import Path

# Add gnucash_mcp to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gnucash_mcp.session import book_session
from gnucash import GnuCashBackendException, Account
import gnucash.gnucash_core_c as gc

# Map account type names to GnuCash enum values
# Using gnucash_core_c enum values
ACCOUNT_TYPES = {
    "ASSET": gc.ACCT_TYPE_ASSET,
    "BANK": gc.ACCT_TYPE_BANK,
    "PAYABLE": gc.ACCT_TYPE_PAYABLE,
    "EQUITY": gc.ACCT_TYPE_EQUITY,
    "INCOME": gc.ACCT_TYPE_INCOME,
    "EXPENSE": gc.ACCT_TYPE_EXPENSE,
    "LIABILITY": gc.ACCT_TYPE_LIABILITY,
}

# MC-6 chart of accounts structure (simplified for M1.2)
CHART = {
    "Assets": {"type": "ASSET"},
    "Liabilities": {"type": "LIABILITY"},
    "Equity": {"type": "EQUITY"},
    "Income": {"type": "INCOME"},
    "Expenses": {"type": "EXPENSE"},
}


def ensure_accounts(book):
    """Ensure all accounts from CHART exist. Create if missing."""
    root = book.get_root_account()

    # Iterate existing children to see what's there
    existing_names = {acc.name for acc in root.get_children()}

    # Create top-level accounts if missing
    for name, config in CHART.items():
        if name not in existing_names:
            try:
                # Create account using C API directly on the book
                # xaccMallocAccount only takes the book parameter
                acc_ptr = gc.xaccMallocAccount(book)

                # Now set properties on the C object
                gc.xaccAccountSetName(acc_ptr, name)
                gc.xaccAccountSetType(acc_ptr, ACCOUNT_TYPES.get(config["type"], gc.ACCT_TYPE_EXPENSE))
                gc.xaccAccountInsertSubAccount(root, acc_ptr)

                print(f"  Created: {name}")
            except Exception as e:
                print(f"  ERROR creating {name}: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()

    return True


def main():
    """Initialize book and create base chart of accounts."""
    book_path = os.environ.get("GNUCASH_BOOK_PATH")
    if not book_path:
        print("ERROR: GNUCASH_BOOK_PATH not set", file=sys.stderr)
        sys.exit(1)

    book_path = Path(book_path)
    is_new = not book_path.exists()

    try:
        with book_session(book_path, is_new=is_new) as session:
            book = session.book

            # Ensure chart of accounts
            ensure_accounts(book)

            # Count accounts
            root = book.get_root_account()
            def count_accounts(acc):
                return 1 + sum(count_accounts(child) for child in acc.get_children())

            total = count_accounts(root)

            if is_new:
                print(f"✓ Created new book at {book_path}")
            else:
                print(f"✓ Opened existing book at {book_path}")

            print(f"✓ Accounts initialized: {total} total")

    except GnuCashBackendException as e:
        print(f"ERROR: GnuCash backend: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
