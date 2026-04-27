#!/usr/bin/env python3
"""
M1.2: Initialize GnuCash book with full chart of accounts (MC-6).

Idempotent: running twice does not create duplicate accounts.
Creates or opens book at GNUCASH_BOOK_PATH environment variable.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gnucash_mcp.session import book_session
from gnucash_mcp.chart import CHART, ensure_subtree, count_accounts
from gnucash import GnuCashBackendException


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
