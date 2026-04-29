"""Property-based tests for write tool numeric invariants.

Covers pay_invoice, post_interest, and post_transaction — the three write
tools not exercised by test_transaction_crud_properties.py.

Each Hypothesis example creates a fresh book inline (same pattern as
test_transaction_crud_properties.py) to avoid accumulated state.
"""

import glob
import os
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import gnucash.gnucash_core_c as gc
from gnucash_mcp import wal
from gnucash_mcp.session import book_session, get_usd, new_account
from gnucash_mcp.tools.read import get_account_balance, get_transaction
from gnucash_mcp.tools.write import (
    fund_project,
    pay_invoice,
    post_interest,
    post_transaction,
    receive_invoice,
    SplitsImbalanceError,
)

VENDOR = "Acme Architecture"
EXPENSE_ACCT = "Expenses:Architecture — Acme Architecture"
AP_ACCT = f"Liabilities:AP — {VENDOR}"
TEST_DATE = "2025-04-01"

# ── Strategies ────────────────────────────────────────────────────────────────

amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(str)

# YYYY-MM month strings within a sane range.
months = st.dates(
    min_value=__import__("datetime").date(2020, 1, 1),
    max_value=__import__("datetime").date(2035, 12, 31),
).map(lambda d: d.strftime("%Y-%m"))

# Full YYYY-MM-DD dates.
dates = st.dates(
    min_value=__import__("datetime").date(2020, 1, 1),
    max_value=__import__("datetime").date(2035, 12, 31),
).map(lambda d: d.strftime("%Y-%m-%d"))


# ── Fresh-book context (mirrors test_transaction_crud_properties.py) ──────────


def _purge_all_backups(path) -> None:
    for f in glob.glob(f"{path}.*.gnucash"):
        try:
            Path(f).unlink()
        except OSError:
            pass


@contextmanager
def _fresh_book():
    tmpdir = tempfile.mkdtemp()
    book_path = Path(tmpdir) / "test.gnucash"
    wal_path = Path(tmpdir) / "test.wal.jsonl"
    try:
        os.environ["GNUCASH_BOOK_PATH"] = str(book_path)
        os.environ["GNUCASH_WAL_PATH"] = str(wal_path)
        wal.init(wal_path)

        with patch("gnucash_mcp.session._purge_same_second_backup", _purge_all_backups):
            with book_session(book_path, is_new=True) as session:
                book = session.book
                root = book.get_root_account()
                usd = get_usd(book)

                def mk(parent, name, acct_type):
                    with new_account(book, parent) as acc:
                        acc.SetName(name)
                        acc.SetType(acct_type)
                        acc.SetCommodity(usd)
                    return acc

                assets = mk(root, "Assets", gc.ACCT_TYPE_ASSET)
                mk(assets, "Project Checking", gc.ACCT_TYPE_BANK)
                liabilities = mk(root, "Liabilities", gc.ACCT_TYPE_LIABILITY)
                mk(liabilities, f"AP — {VENDOR}", gc.ACCT_TYPE_PAYABLE)
                equity = mk(root, "Equity", gc.ACCT_TYPE_EQUITY)
                mk(equity, "Owner Capital", gc.ACCT_TYPE_EQUITY)
                income = mk(root, "Income", gc.ACCT_TYPE_INCOME)
                mk(income, "Interest Income", gc.ACCT_TYPE_INCOME)
                expenses = mk(root, "Expenses", gc.ACCT_TYPE_EXPENSE)
                mk(expenses, f"Architecture — {VENDOR}", gc.ACCT_TYPE_EXPENSE)

            yield

    finally:
        wal._wal_path = None
        for suffix in ("", ".LCK"):
            p = Path(str(book_path) + suffix)
            if p.exists():
                p.unlink()
        if wal_path.exists():
            wal_path.unlink()
        try:
            Path(tmpdir).rmdir()
        except OSError:
            pass


# ── pay_invoice ───────────────────────────────────────────────────────────────


@settings(max_examples=50)
@given(amount=amounts)
def test_pay_invoice_clears_ap_balance(amount):
    """For any amount: receive_invoice then pay_invoice leaves AP at zero."""
    with _fresh_book():
        receive_invoice(TEST_DATE, VENDOR, "INV-001", amount, EXPENSE_ACCT)
        pay_invoice(TEST_DATE, VENDOR, "INV-001", amount)

        assert Decimal(get_account_balance(AP_ACCT)["balance"]) == Decimal("0")


@settings(max_examples=50)
@given(amount=amounts)
def test_pay_invoice_reduces_checking_by_amount(amount):
    """For any amount: pay_invoice reduces Project Checking by exactly that amount."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        checking_before = Decimal(get_account_balance("Assets:Project Checking")["balance"])

        receive_invoice(TEST_DATE, VENDOR, "INV-001", amount, EXPENSE_ACCT)
        pay_invoice(TEST_DATE, VENDOR, "INV-001", amount)

        checking_after = Decimal(get_account_balance("Assets:Project Checking")["balance"])
        assert checking_before - checking_after == Decimal(amount)


@settings(max_examples=50)
@given(amount=amounts)
def test_pay_invoice_does_not_touch_expense_balance(amount):
    """For any amount: pay_invoice does not alter the expense account balance."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        receive_invoice(TEST_DATE, VENDOR, "INV-001", amount, EXPENSE_ACCT)
        expense_after_invoice = Decimal(get_account_balance(EXPENSE_ACCT)["balance"])

        pay_invoice(TEST_DATE, VENDOR, "INV-001", amount)

        expense_after_payment = Decimal(get_account_balance(EXPENSE_ACCT)["balance"])
        assert expense_after_payment == expense_after_invoice


@settings(max_examples=30)
@given(amounts_list=st.lists(amounts, min_size=2, max_size=6))
def test_partial_pay_ap_balance_equals_unpaid_sum(amounts_list):
    """Post N invoices, pay a subset: AP balance equals sum of unpaid invoices."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        for i, amount in enumerate(amounts_list):
            receive_invoice(TEST_DATE, VENDOR, f"INV-{i:03d}", amount, EXPENSE_ACCT)

        # Pay only even-indexed invoices.
        unpaid = Decimal("0")
        for i, amount in enumerate(amounts_list):
            if i % 2 == 0:
                pay_invoice(TEST_DATE, VENDOR, f"INV-{i:03d}", amount)
            else:
                unpaid += Decimal(amount)

        assert Decimal(get_account_balance(AP_ACCT)["balance"]) == -unpaid


# ── post_interest ─────────────────────────────────────────────────────────────


@settings(max_examples=50)
@given(month=months, amount=amounts)
def test_post_interest_increases_checking_by_amount(month, amount):
    """For any month and amount: post_interest credits Project Checking by exactly amount."""
    with _fresh_book():
        checking_before = Decimal(get_account_balance("Assets:Project Checking")["balance"])
        post_interest(month, amount)
        checking_after = Decimal(get_account_balance("Assets:Project Checking")["balance"])
        assert checking_after - checking_before == Decimal(amount)


@settings(max_examples=50)
@given(month=months, amount=amounts)
def test_post_interest_credits_income_by_amount(month, amount):
    """For any month and amount: Income:Interest Income balance equals -amount."""
    with _fresh_book():
        post_interest(month, amount)
        income_bal = Decimal(get_account_balance("Income:Interest Income")["balance"])
        assert income_bal == -Decimal(amount)


@settings(max_examples=50)
@given(date=dates, amount=amounts)
def test_post_interest_full_date_format(date, amount):
    """YYYY-MM-DD format is accepted and posts the same accounting entries."""
    with _fresh_book():
        post_interest(date, amount)
        checking = Decimal(get_account_balance("Assets:Project Checking")["balance"])
        assert checking == Decimal(amount)


@settings(max_examples=40)
@given(month=months, amount=amounts)
def test_post_interest_splits_sum_to_zero(month, amount):
    """For any month and amount: the posted transaction's splits sum to zero."""
    with _fresh_book():
        result = post_interest(month, amount)
        txn = get_transaction(result["transaction_guid"])
        total = sum(Decimal(s["amount"]) for s in txn["splits"])
        assert total == Decimal("0")


# ── post_transaction ──────────────────────────────────────────────────────────


@settings(max_examples=200)
@given(
    amounts_list=st.lists(
        st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("9999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=1,
        max_size=8,
    )
)
def test_post_transaction_rejects_imbalanced_splits(amounts_list):
    """For any list of positive amounts (which cannot sum to zero):
    post_transaction raises SplitsImbalanceError before touching the book.
    No fresh book needed — the check fires before the session opens."""
    splits = [
        {"account_path": "Assets:Project Checking", "amount": str(a)}
        for a in amounts_list
    ]
    with pytest.raises(SplitsImbalanceError):
        post_transaction(TEST_DATE, "Imbalanced", splits)


@settings(max_examples=50)
@given(amount=amounts)
def test_post_transaction_balanced_pair_posts_correctly(amount):
    """For any amount: a balanced debit/credit pair posts and round-trips via
    get_transaction with matching split amounts."""
    with _fresh_book():
        splits = [
            {"account_path": EXPENSE_ACCT, "amount": amount},
            {"account_path": AP_ACCT, "amount": f"-{amount}"},
        ]
        result = post_transaction(TEST_DATE, "Manual balanced post", splits)

        txn = get_transaction(result["transaction_guid"])
        posted = {s["account"]: Decimal(s["amount"]) for s in txn["splits"]}

        assert posted[EXPENSE_ACCT] == Decimal(amount)
        assert posted[AP_ACCT] == -Decimal(amount)


@settings(max_examples=30)
@given(
    amounts_list=st.lists(
        st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=1,
        max_size=6,
    )
)
def test_post_transaction_multi_split_sums_to_zero(amounts_list):
    """For any set of expense amounts: a post_transaction with offsetting AP
    splits produces a transaction whose splits sum to exactly zero."""
    with _fresh_book():
        total = sum(amounts_list)
        splits = (
            [{"account_path": EXPENSE_ACCT, "amount": str(a)} for a in amounts_list]
            + [{"account_path": AP_ACCT, "amount": str(-total)}]
        )
        result = post_transaction(TEST_DATE, "Multi-split", splits)

        txn = get_transaction(result["transaction_guid"])
        split_sum = sum(Decimal(s["amount"]) for s in txn["splits"])
        assert split_sum == Decimal("0")
