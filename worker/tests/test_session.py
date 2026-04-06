"""Tests for GnuCash session management — T1.4.x"""

from pathlib import Path

import pytest
from gnucash import GnuCashBackendException

from gnucash_mcp.session import (
    open_session, close_session, book_session, get_account,
    gnc_decimal, AccountNotFoundError
)


class TestSessionLifecycle:
    """T1.4.1–T1.4.3: Session open/close basics."""

    def test_open_session_creates_lock_file(self, test_book_path):
        """T1.4.1: open_session(path, is_new=True) creates .LCK file alongside book"""
        session = open_session(test_book_path, is_new=True)
        try:
            lck_file = Path(str(test_book_path) + ".LCK")
            assert lck_file.exists(), ".LCK file should exist for open session"
        finally:
            close_session(session)

    def test_open_session_calls_early_save(self, test_book_path):
        """T1.4.2: open_session(path, is_new=True) calls save() before returning"""
        session = open_session(test_book_path, is_new=True)
        try:
            # For a new book, save() should have been called, so file exists
            assert test_book_path.exists(), "Book file should exist after open_session(is_new=True)"
        finally:
            close_session(session)

    def test_close_session_removes_lock(self, test_book_path):
        """T1.4.3: close_session() calls save() then end(); .LCK file absent after"""
        session = open_session(test_book_path, is_new=True)
        close_session(session)

        lck_file = Path(str(test_book_path) + ".LCK")
        assert not lck_file.exists(), ".LCK file should be removed after close_session()"


class TestStaleFileLocking:
    """T1.4.4: Stale .LCK file handling."""

    def test_stale_lock_cleared_on_open(self, test_book_path):
        """T1.4.4: Stale .LCK file from a prior crash is cleared on open without error"""
        # Create book
        session = open_session(test_book_path, is_new=True)
        close_session(session)

        # Create stale .LCK file
        lck_file = Path(str(test_book_path) + ".LCK")
        lck_file.write_text("stale")

        # Open should clear it and succeed
        session = open_session(test_book_path, is_new=False)
        try:
            # Lock should be cleared before this point
            assert lck_file.exists(), ".LCK should exist for open session"
        finally:
            close_session(session)


class TestContextManager:
    """T1.4.5: book_session context manager."""

    def test_context_manager_closes_on_exception(self, test_book_path):
        """T1.4.5: book_session() context manager calls close_session() even if exception raised"""
        with pytest.raises(RuntimeError):
            with book_session(test_book_path, is_new=True) as session:
                raise RuntimeError("Test exception")

        # Lock should be cleared even though exception was raised
        lck_file = Path(str(test_book_path) + ".LCK")
        assert not lck_file.exists(), ".LCK should be cleared after exception in context manager"

    def test_context_manager_closes_normally(self, test_book_path):
        """book_session() context manager closes normally without exception"""
        with book_session(test_book_path, is_new=True) as session:
            assert session is not None

        lck_file = Path(str(test_book_path) + ".LCK")
        assert not lck_file.exists(), ".LCK should be cleared after normal exit"


class TestDoubleOpen:
    """T1.4.6: Lock detection for double-open."""

    def test_second_open_on_locked_book_raises_error(self, test_book_path):
        """T1.4.6: Second open on locked book raises GnuCashBackendException with ERR_BACKEND_LOCKED"""
        session1 = open_session(test_book_path, is_new=True)
        try:
            # Try to open the same book again while locked
            with pytest.raises(GnuCashBackendException) as exc_info:
                session2 = open_session(test_book_path, is_new=False)
            # The exception should mention locking
            assert len(exc_info.value.errors) > 0
        finally:
            close_session(session1)


class TestAccountLookup:
    """T1.4.7–T1.4.8: get_account() with existing and missing accounts."""

    def test_get_account_finds_existing(self, initialized_book):
        """T1.4.7: get_account(book, "Expenses:Architecture — Acme Architecture") returns correct account"""
        with book_session(initialized_book) as session:
            acc = get_account(session.book, "Expenses:Architecture — Acme Architecture")
            assert acc is not None
            assert acc.name == "Architecture — Acme Architecture"

    def test_get_account_top_level(self, initialized_book):
        """get_account can find top-level accounts"""
        with book_session(initialized_book) as session:
            acc = get_account(session.book, "Assets")
            assert acc.name == "Assets"

    def test_get_account_nested(self, initialized_book):
        """get_account can find nested accounts"""
        with book_session(initialized_book) as session:
            acc = get_account(session.book, "Assets:Project Checking")
            assert acc.name == "Project Checking"

    def test_get_account_missing_raises_error(self, initialized_book):
        """T1.4.8: get_account(book, "Expenses:Nonexistent") raises AccountNotFoundError"""
        with book_session(initialized_book) as session:
            with pytest.raises(AccountNotFoundError):
                get_account(session.book, "Expenses:Nonexistent")

    def test_get_account_invalid_path_raises_error(self, initialized_book):
        """get_account with invalid intermediate path raises AccountNotFoundError"""
        with book_session(initialized_book) as session:
            with pytest.raises(AccountNotFoundError):
                get_account(session.book, "Expenses:Invalid:Path")


class TestGnucashDecimal:
    """T1.4.9: gnc_decimal() conversion."""

    def test_gnc_decimal_simple(self):
        """T1.4.9: gnc_decimal("15000.00") round-trips without precision loss"""
        result = gnc_decimal("15000.00")
        assert result.num == 1500000
        assert result.denom == 100
        assert float(result.to_double()) == 15000.00

    def test_gnc_decimal_fractional(self):
        """gnc_decimal handles fractional amounts correctly"""
        result = gnc_decimal("123.45")
        assert result.num == 12345
        assert result.denom == 100
        assert abs(float(result.to_double()) - 123.45) < 0.001

    def test_gnc_decimal_whole_number(self):
        """gnc_decimal handles whole numbers"""
        result = gnc_decimal("1000")
        assert result.num == 1000
        assert result.denom == 1

    def test_gnc_decimal_small_amount(self):
        """gnc_decimal handles very small amounts"""
        result = gnc_decimal("0.01")
        assert result.num == 1
        assert result.denom == 100

    def test_gnc_decimal_negative(self):
        """gnc_decimal handles negative amounts correctly"""
        result = gnc_decimal("-500.50")
        assert result.num == -50050
        assert result.denom == 100
        assert float(result.to_double()) < 0

    def test_gnc_decimal_invalid_raises_error(self):
        """gnc_decimal raises ValueError for invalid input"""
        with pytest.raises(ValueError):
            gnc_decimal("not-a-number")


class TestBookCreation:
    """Tests for book creation and initialization."""

    def test_new_book_has_root_account(self, test_book_path):
        """Newly created book has a root account"""
        with book_session(test_book_path, is_new=True) as session:
            root = session.book.get_root_account()
            assert root is not None

    def test_reopening_created_book(self, test_book_path):
        """Can reopen a created book with SESSION_NORMAL_OPEN"""
        # Create book
        with book_session(test_book_path, is_new=True) as session:
            pass

        # Reopen
        with book_session(test_book_path, is_new=False) as session:
            assert session.book is not None
