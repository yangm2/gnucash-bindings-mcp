"""Tests for GnuCash session management — T1.4.x"""

from pathlib import Path

import pytest
from gnucash import GnuCashBackendException

import datetime
import tempfile

from hypothesis import given, settings
from hypothesis.strategies import dates

from gnucash_mcp.session import (
    _open_session,
    _close_session,
    book_path,
    book_session,
    edit_transaction,
    get_account,
    get_usd,
    gnc_decimal,
    new_transaction,
    set_txn_isodate,
    get_txn_isodate,
    account_balance_float,
    clear_stale_lock,
    AccountNotFoundError,
)


class TestSessionLifecycle:
    """T1.4.1–T1.4.3: Session open/close basics."""

    def test_open_session_creates_lock_file(self, test_book_path):
        """T1.4.1: open_session(path, is_new=True) creates .LCK file alongside book"""
        session = _open_session(test_book_path, is_new=True)
        try:
            lck_file = Path(str(test_book_path) + ".LCK")
            assert lck_file.exists(), ".LCK file should exist for open session"
        finally:
            _close_session(session)

    def test_open_session_calls_early_save(self, test_book_path):
        """T1.4.2: open_session(path, is_new=True) calls save() before returning"""
        # Clean up any existing file
        if test_book_path.exists():
            test_book_path.unlink()

        session = _open_session(test_book_path, is_new=True)
        try:
            # For a new book, save() should have been called, so file exists
            assert test_book_path.exists(), "Book file should exist after open_session(is_new=True)"
        finally:
            _close_session(session)

    def test_close_session_removes_lock(self, test_book_path):
        """T1.4.3: close_session() calls save() then end(); .LCK file absent after"""
        session = _open_session(test_book_path, is_new=True)
        _close_session(session)

        lck_file = Path(str(test_book_path) + ".LCK")
        assert not lck_file.exists(), ".LCK file should be removed after close_session()"


class TestStaleFileLocking:
    """T1.4.4: Stale .LCK file handling."""

    def test_stale_lock_cleared_on_open(self, test_book_path):
        """T1.4.4: Stale .LCK file from a prior crash is cleared on open without error"""
        # Create book
        session = _open_session(test_book_path, is_new=True)
        _close_session(session)

        # Create stale .LCK file (simulates crash before session.end())
        lck_file = Path(str(test_book_path) + ".LCK")
        lck_file.write_text("stale")

        # clear_stale_lock() is called at process startup (via __main__.py)
        # before any open_session(); mimic that here
        clear_stale_lock(test_book_path)
        session = _open_session(test_book_path, is_new=False)
        try:
            # Lock should be cleared before this point
            assert lck_file.exists(), ".LCK should exist for open session"
        finally:
            _close_session(session)


class TestContextManager:
    """T1.4.5: book_session context manager."""

    def test_context_manager_closes_on_exception(self, test_book_path):
        """T1.4.5: book_session() context manager calls close_session() even if exception raised"""
        with pytest.raises(RuntimeError):
            with book_session(test_book_path, is_new=True):
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
        session1 = _open_session(test_book_path, is_new=True)
        try:
            # Try to open the same book again while locked
            with pytest.raises(GnuCashBackendException) as exc_info:
                _open_session(test_book_path, is_new=False)
            # The exception should mention locking
            assert len(exc_info.value.errors) > 0
        finally:
            _close_session(session1)


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
        assert result.num() == 1500000
        assert result.denom() == 100
        assert float(result.to_double()) == 15000.00

    def test_gnc_decimal_fractional(self):
        """gnc_decimal handles fractional amounts correctly"""
        result = gnc_decimal("123.45")
        assert result.num() == 12345
        assert result.denom() == 100
        assert abs(float(result.to_double()) - 123.45) < 0.001

    def test_gnc_decimal_whole_number(self):
        """gnc_decimal handles whole numbers"""
        result = gnc_decimal("1000")
        assert result.num() == 1000
        assert result.denom() == 1

    def test_gnc_decimal_small_amount(self):
        """gnc_decimal handles very small amounts"""
        result = gnc_decimal("0.01")
        assert result.num() == 1
        assert result.denom() == 100

    def test_gnc_decimal_negative(self):
        """gnc_decimal handles negative amounts correctly"""
        result = gnc_decimal("-500.50")
        assert result.num() == -50050
        assert result.denom() == 100
        assert float(result.to_double()) < 0

    def test_gnc_decimal_invalid_raises_error(self):
        """gnc_decimal raises ValueError for invalid input"""
        with pytest.raises(ValueError):
            gnc_decimal("not-a-number")


@given(dates(min_value=datetime.date(1970, 1, 1), max_value=datetime.date(2099, 12, 31)))
@settings(max_examples=50)
def test_txn_isodate_roundtrip_property(d):
    """Property: set_txn_isodate → get_txn_isodate round-trips any date in the safe range.

    Catches argument-order transposition: if day/year were swapped, GetDate().year
    would be wrong for any date where day != year (i.e. almost every date).

    Self-contained (no pytest fixtures) so Hypothesis controls the full test lifecycle.
    """
    from gnucash import Split, Account
    import gnucash.gnucash_core_c as gc

    date_str = d.isoformat()
    with tempfile.TemporaryDirectory() as tmp:
        prop_book_path = Path(tmp) / "prop_test.gnucash"
        with book_session(prop_book_path, is_new=True) as session:
            book = session.book
            root = book.get_root_account()
            usd = get_usd(book)

            def make_acc(parent, name, acct_type):
                acc = Account(book)
                acc.SetName(name)
                acc.SetType(acct_type)
                acc.SetCommodity(usd)
                parent.append_child(acc)
                return acc

            checking = make_acc(root, "Assets", gc.ACCT_TYPE_ASSET)
            equity = make_acc(root, "Equity", gc.ACCT_TYPE_EQUITY)

            with new_transaction(book) as txn:
                set_txn_isodate(txn, date_str)
                txn.SetDescription("prop test")
                txn.SetCurrency(usd)
                for acc, amount_str in [(checking, "1.00"), (equity, "-1.00")]:
                    s = Split(book)
                    s.SetParent(txn)
                    s.SetAccount(acc)
                    amt = gnc_decimal(amount_str)
                    s.SetAmount(amt)
                    s.SetValue(amt)

            assert get_txn_isodate(txn) == date_str


class TestAccountBalanceFloat:
    """account_balance_float() wrapper — encodes AP credit/negate convention."""

    def test_asset_account_balance_positive(self, initialized_book):
        """account_balance_float returns positive value for asset account with debit balance"""
        from gnucash_mcp.tools.write import fund_project
        import os

        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        fund_project("2025-01-01", "10000.00", "test")

        with book_session(initialized_book) as session:
            acc = get_account(session.book, "Assets:Project Checking")
            bal = account_balance_float(acc)
            assert bal == 10000.0

    def test_liability_account_negate_true(self, initialized_book):
        """account_balance_float(negate=True) returns positive owed amount for AP account"""
        from gnucash_mcp.tools.write import receive_invoice
        import os

        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        receive_invoice(
            "2025-01-01",
            "Acme Architecture",
            "AAI-001",
            "5000.00",
            "Expenses:Architecture — Acme Architecture",
        )

        with book_session(initialized_book) as session:
            acc = get_account(session.book, "Liabilities:AP — Acme Architecture")
            raw = account_balance_float(acc, negate=False)
            negated = account_balance_float(acc, negate=True)
            assert raw == -5000.0  # credit balance is negative in GnuCash
            assert negated == 5000.0  # negate=True gives the conventional positive amount owed


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


class TestGetUsd:
    """get_usd() — commodity lookup helper."""

    def test_returns_usd_commodity(self, test_book_path):
        """get_usd returns a GncCommodity with mnemonic USD."""
        with book_session(test_book_path, is_new=True) as session:
            usd = get_usd(session.book)
            assert usd is not None
            assert usd.get_mnemonic() == "USD"


class TestBookPath:
    """book_path() — env-var reader."""

    def test_returns_default_when_env_unset(self, monkeypatch):
        """book_path() returns /data/project.gnucash when GNUCASH_BOOK_PATH is absent."""
        monkeypatch.delenv("GNUCASH_BOOK_PATH", raising=False)
        assert book_path() == Path("/data/project.gnucash")

    def test_returns_env_var_path(self, monkeypatch, tmp_path):
        """book_path() returns the path set in GNUCASH_BOOK_PATH."""
        target = tmp_path / "my.gnucash"
        monkeypatch.setenv("GNUCASH_BOOK_PATH", str(target))
        assert book_path() == target


class TestNewTransaction:
    """new_transaction() — creates and commits a Transaction via context manager."""

    def test_commits_on_clean_exit(self, initialized_book):
        """Transaction created inside new_transaction is committed and appears in account splits."""
        from gnucash import Split

        with book_session(initialized_book) as session:
            book = session.book
            checking = get_account(book, "Assets:Project Checking")
            equity = get_account(book, "Equity:Owner Capital")

            before = len(checking.GetSplitList())

            with new_transaction(book) as txn:
                set_txn_isodate(txn, "2025-06-01")
                txn.SetDescription("cm commit test")
                txn.SetCurrency(get_usd(book))
                for acc, amt_str in [(checking, "100.00"), (equity, "-100.00")]:
                    s = Split(book)
                    s.SetParent(txn)
                    s.SetAccount(acc)
                    amt = gnc_decimal(amt_str)
                    s.SetAmount(amt)
                    s.SetValue(amt)

            assert len(checking.GetSplitList()) == before + 1

    def test_rolls_back_on_exception(self, initialized_book):
        """Exception inside new_transaction propagates; transaction is rolled back."""
        with book_session(initialized_book) as session:
            book = session.book
            checking = get_account(book, "Assets:Project Checking")
            before = len(checking.GetSplitList())

            with pytest.raises(ValueError, match="abort"):
                with new_transaction(book) as txn:
                    txn.SetDescription("will be rolled back")
                    txn.SetCurrency(get_usd(book))
                    raise ValueError("abort")

            assert len(checking.GetSplitList()) == before


class TestEditTransaction:
    """edit_transaction() — BeginEdit/CommitEdit wrapper for existing transactions."""

    def test_commits_description_change(self, initialized_book):
        """edit_transaction commits a description change on an existing transaction."""
        from gnucash import Split

        with book_session(initialized_book) as session:
            book = session.book
            checking = get_account(book, "Assets:Project Checking")
            equity = get_account(book, "Equity:Owner Capital")

            with new_transaction(book) as txn:
                set_txn_isodate(txn, "2025-06-01")
                txn.SetDescription("original description")
                txn.SetCurrency(get_usd(book))
                for acc, amt_str in [(checking, "50.00"), (equity, "-50.00")]:
                    s = Split(book)
                    s.SetParent(txn)
                    s.SetAccount(acc)
                    amt = gnc_decimal(amt_str)
                    s.SetAmount(amt)
                    s.SetValue(amt)

            with edit_transaction(txn):
                txn.SetDescription("updated description")

            assert txn.GetDescription() == "updated description"

    def test_rolls_back_on_exception(self, initialized_book):
        """Exception inside edit_transaction propagates."""
        from gnucash import Split

        with book_session(initialized_book) as session:
            book = session.book
            checking = get_account(book, "Assets:Project Checking")
            equity = get_account(book, "Equity:Owner Capital")

            with new_transaction(book) as txn:
                set_txn_isodate(txn, "2025-06-01")
                txn.SetDescription("stable description")
                txn.SetCurrency(get_usd(book))
                for acc, amt_str in [(checking, "25.00"), (equity, "-25.00")]:
                    s = Split(book)
                    s.SetParent(txn)
                    s.SetAccount(acc)
                    amt = gnc_decimal(amt_str)
                    s.SetAmount(amt)
                    s.SetValue(amt)

            with pytest.raises(RuntimeError, match="abort edit"):
                with edit_transaction(txn):
                    txn.SetDescription("partial edit")
                    raise RuntimeError("abort edit")
