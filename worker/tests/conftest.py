"""Pytest configuration and fixtures for Phase 1 tests."""

import os
import pytest
import tempfile
from pathlib import Path
from shutil import rmtree

from gnucash_mcp.session import book_session
from gnucash_mcp import wal
from gnucash import Account
import gnucash.gnucash_core_c as gc


@pytest.fixture
def tmpdir_cleanup(tmp_path):
    """Fixture providing a temporary directory that's cleaned up after the test."""
    yield tmp_path
    if tmp_path.exists():
        rmtree(tmp_path, ignore_errors=True)


@pytest.fixture
def test_book_path(tmpdir_cleanup):
    """Fixture providing a path to a test GnuCash book."""
    path = tmpdir_cleanup / "test.gnucash"
    return path


@pytest.fixture
def test_wal_path(tmpdir_cleanup):
    """Fixture providing a path to a test WAL file."""
    path = tmpdir_cleanup / "test.wal.jsonl"
    return path


@pytest.fixture
def initialized_book(test_book_path, test_wal_path):
    """Fixture providing a newly-initialized GnuCash book with MC-6 chart."""
    # Set env vars for session and WAL
    os.environ["GNUCASH_BOOK_PATH"] = str(test_book_path)
    os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
    wal.init(test_wal_path)

    # Create book with full chart of accounts
    with book_session(test_book_path, is_new=True) as session:
        book = session.book
        root = book.get_root_account()

        # Minimal MC-6 chart for testing
        usd = book.get_table().lookup("CURRENCY", "USD")

        def create_account(parent, name, acct_type):
            acc = Account(book)
            acc.SetName(name)
            acc.SetType(acct_type)
            acc.SetCommodity(usd)
            parent.append_child(acc)
            return acc

        # Create main accounts
        assets = create_account(root, "Assets", gc.ACCT_TYPE_ASSET)
        create_account(assets, "Project Checking", gc.ACCT_TYPE_BANK)

        liabilities = create_account(root, "Liabilities", gc.ACCT_TYPE_LIABILITY)
        create_account(liabilities, "AP — Acme Architecture", gc.ACCT_TYPE_PAYABLE)
        create_account(liabilities, "AP — Peak Structural", gc.ACCT_TYPE_PAYABLE)

        equity = create_account(root, "Equity", gc.ACCT_TYPE_EQUITY)
        create_account(equity, "Owner Capital", gc.ACCT_TYPE_EQUITY)

        income = create_account(root, "Income", gc.ACCT_TYPE_INCOME)
        create_account(income, "Interest Income", gc.ACCT_TYPE_INCOME)

        expenses = create_account(root, "Expenses", gc.ACCT_TYPE_EXPENSE)
        create_account(expenses, "Architecture — Acme Architecture", gc.ACCT_TYPE_EXPENSE)
        create_account(expenses, "Structural Engineering — Peak Structural",
                      gc.ACCT_TYPE_EXPENSE)

    yield test_book_path

    # Cleanup
    if test_book_path.exists():
        test_book_path.unlink()
    if test_wal_path.exists():
        test_wal_path.unlink()
    if Path(str(test_book_path) + ".LCK").exists():
        Path(str(test_book_path) + ".LCK").unlink()


@pytest.fixture(autouse=True)
def reset_wal():
    """Reset global WAL path before each test."""
    wal._wal_path = None
    yield
    wal._wal_path = None
