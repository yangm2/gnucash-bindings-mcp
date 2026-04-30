"""Pytest configuration and fixtures for gnucash_mcp tests."""

import os
import pytest
from pathlib import Path
from shutil import rmtree
from hypothesis import settings

# GnuCash I/O is variable; the 200ms default deadline causes spurious FlakyFailure.
settings.register_profile("gnucash", deadline=None)
settings.load_profile("gnucash")

from gnucash_mcp.session import book_session, new_account, get_usd
from gnucash_mcp import wal
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
        usd = get_usd(book)

        def mk(parent, name, acct_type):
            with new_account(book, parent) as acc:
                acc.SetName(name)
                acc.SetType(acct_type)
                acc.SetCommodity(usd)
            return acc

        # Create main accounts
        assets = mk(root, "Assets", gc.ACCT_TYPE_ASSET)
        mk(assets, "Project Checking", gc.ACCT_TYPE_BANK)

        liabilities = mk(root, "Liabilities", gc.ACCT_TYPE_LIABILITY)
        mk(liabilities, "AP — Acme Architecture", gc.ACCT_TYPE_PAYABLE)
        mk(liabilities, "AP — Peak Structural", gc.ACCT_TYPE_PAYABLE)
        mk(liabilities, "AP — Meridian MEP", gc.ACCT_TYPE_PAYABLE)
        mk(liabilities, "AP — Summit HVAC", gc.ACCT_TYPE_PAYABLE)

        equity = mk(root, "Equity", gc.ACCT_TYPE_EQUITY)
        mk(equity, "Owner Capital", gc.ACCT_TYPE_EQUITY)

        income = mk(root, "Income", gc.ACCT_TYPE_INCOME)
        mk(income, "Interest Income", gc.ACCT_TYPE_INCOME)

        expenses = mk(root, "Expenses", gc.ACCT_TYPE_EXPENSE)
        mk(expenses, "Architecture — Acme Architecture", gc.ACCT_TYPE_EXPENSE)
        mk(expenses, "Structural Engineering — Peak Structural", gc.ACCT_TYPE_EXPENSE)
        mk(expenses, "MEP Consulting — Meridian MEP", gc.ACCT_TYPE_EXPENSE)
        mk(expenses, "HVAC Engineering — Summit HVAC", gc.ACCT_TYPE_EXPENSE)

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


@pytest.fixture
def full_book(test_book_path, test_wal_path):
    """Book initialized with the full MC-6 chart (used by Phase 2 tests).

    Includes Construction:*, Change Orders:*, and professional fee accounts, but
    no pre-existing AP accounts beyond the four initial vendors from the project
    charter.  Tests that need a clean vendor slate should add uniquely-named
    vendors rather than reusing Acme / Peak / Meridian / Summit.
    """
    from gnucash_mcp.chart import CHART, ensure_subtree

    os.environ["GNUCASH_BOOK_PATH"] = str(test_book_path)
    os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
    wal.init(test_wal_path)

    with book_session(test_book_path, is_new=True) as session:
        book = session.book
        root = book.get_root_account()
        ensure_subtree(book, root, CHART)

    yield test_book_path

    for suffix in ("", ".LCK"):
        p = Path(str(test_book_path) + suffix)
        if p.exists():
            p.unlink()
    if test_wal_path.exists():
        test_wal_path.unlink()
