"""Property-based tests for transaction CRUD numeric invariants.

Each Hypothesis example needs a fresh GnuCash book — shared book state
(accumulated balances, duplicate invoice refs) would poison later examples.
We create and tear down a book inline per example.
"""

import os
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import gnucash.gnucash_core_c as gc
from gnucash_mcp import wal
from gnucash_mcp.session import book_session, get_usd, new_account
from gnucash_mcp.tools.read import get_account_balance, get_transaction
from gnucash_mcp.tools.write import (
    fund_project,
    receive_invoice,
    update_transaction,
    void_transaction,
    delete_transaction,
)

EXPENSE_ACCT = "Expenses:Architecture — Acme Architecture"
AP_ACCT = "Liabilities:AP — Acme Architecture"
TEST_DATE = "2025-03-01"
TEST_DATE_2 = "2025-03-15"


amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(str)

descriptions = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
    min_size=1,
    max_size=80,
)


@contextmanager
def _fresh_book():
    """Inline book setup/teardown for one Hypothesis example."""
    tmpdir = tempfile.mkdtemp()
    book_path = Path(tmpdir) / "test.gnucash"
    wal_path = Path(tmpdir) / "test.wal.jsonl"
    try:
        os.environ["GNUCASH_BOOK_PATH"] = str(book_path)
        os.environ["GNUCASH_WAL_PATH"] = str(wal_path)
        wal.init(wal_path)

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
            mk(liabilities, "AP — Acme Architecture", gc.ACCT_TYPE_PAYABLE)
            equity = mk(root, "Equity", gc.ACCT_TYPE_EQUITY)
            mk(equity, "Owner Capital", gc.ACCT_TYPE_EQUITY)
            expenses = mk(root, "Expenses", gc.ACCT_TYPE_EXPENSE)
            mk(expenses, "Architecture — Acme Architecture", gc.ACCT_TYPE_EXPENSE)

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


# ── Balance identity ──────────────────────────────────────────────────────────


@settings(max_examples=50)
@given(amount=amounts)
def test_receive_invoice_balance_identity(amount):
    """For any amount: expense debit == AP credit == amount after receive_invoice."""
    with _fresh_book():
        receive_invoice(TEST_DATE, "Acme Architecture", "INV-001", amount, EXPENSE_ACCT)

        expense_bal = Decimal(get_account_balance(EXPENSE_ACCT)["balance"])
        ap_bal = Decimal(get_account_balance(AP_ACCT)["balance"])

        assert expense_bal == Decimal(amount)
        assert ap_bal == -Decimal(amount)


@settings(max_examples=50)
@given(amount=amounts)
def test_void_is_net_zero(amount):
    """For any amount: void after receive_invoice returns both accounts to zero."""
    with _fresh_book():
        guid = receive_invoice(TEST_DATE, "Acme Architecture", "INV-001", amount, EXPENSE_ACCT)[
            "transaction_guid"
        ]

        void_transaction(guid, reason="Property test void")

        assert Decimal(get_account_balance(EXPENSE_ACCT)["balance"]) == Decimal("0")
        assert Decimal(get_account_balance(AP_ACCT)["balance"]) == Decimal("0")


@settings(max_examples=50)
@given(amount=amounts)
def test_delete_is_net_zero(amount):
    """For any amount: delete after receive_invoice returns both accounts to zero."""
    with _fresh_book():
        guid = receive_invoice(TEST_DATE, "Acme Architecture", "INV-001", amount, EXPENSE_ACCT)[
            "transaction_guid"
        ]

        delete_transaction(guid, confirm=True)

        assert Decimal(get_account_balance(EXPENSE_ACCT)["balance"]) == Decimal("0")
        assert Decimal(get_account_balance(AP_ACCT)["balance"]) == Decimal("0")


# ── update_transaction preserves splits ───────────────────────────────────────


@settings(max_examples=40)
@given(amount=amounts, description=descriptions)
def test_update_preserves_split_amounts(amount, description):
    """For any amount and description: update_transaction does not alter split amounts."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        guid = receive_invoice(TEST_DATE, "Acme Architecture", "INV-001", amount, EXPENSE_ACCT)[
            "transaction_guid"
        ]

        before = get_transaction(guid)
        before_amounts = {s["account"]: s["amount"] for s in before["splits"]}

        update_transaction(guid, description=description)

        after = get_transaction(guid)
        after_amounts = {s["account"]: s["amount"] for s in after["splits"]}

        assert after_amounts == before_amounts
        assert after["description"] == description


@settings(max_examples=40)
@given(amount=amounts)
def test_update_date_preserves_split_amounts(amount):
    """For any amount: changing date does not alter split amounts."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        guid = receive_invoice(TEST_DATE, "Acme Architecture", "INV-001", amount, EXPENSE_ACCT)[
            "transaction_guid"
        ]

        before_amounts = {s["account"]: s["amount"] for s in get_transaction(guid)["splits"]}

        update_transaction(guid, date=TEST_DATE_2)

        after = get_transaction(guid)
        after_amounts = {s["account"]: s["amount"] for s in after["splits"]}

        assert after_amounts == before_amounts
        assert after["date"] == TEST_DATE_2


# ── Multiple invoices sum correctly ───────────────────────────────────────────


@settings(max_examples=30)
@given(amounts_list=st.lists(amounts, min_size=1, max_size=6))
def test_multiple_invoices_sum_to_balance(amounts_list):
    """For any list of amounts: expense balance == exact sum of all invoices posted."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        expected = Decimal("0")
        for i, amount in enumerate(amounts_list):
            receive_invoice(TEST_DATE, "Acme Architecture", f"INV-{i:03d}", amount, EXPENSE_ACCT)
            expected += Decimal(amount)

        actual = Decimal(get_account_balance(EXPENSE_ACCT)["balance"])
        assert actual == expected


# ── WAL / get_transaction consistency ────────────────────────────────────────


@settings(max_examples=40)
@given(amount=amounts)
def test_wal_id_matches_get_transaction_mcp_slot(amount):
    """For any amount: wal_id returned by receive_invoice matches mcp.wal_id in get_transaction."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        result = receive_invoice(TEST_DATE, "Acme Architecture", "INV-001", amount, EXPENSE_ACCT)

        txn = get_transaction(result["transaction_guid"])
        assert txn["mcp"] is not None
        assert txn["mcp"]["wal_id"] == result["wal_id"]
        assert txn["mcp"]["tool"] == "receive_invoice"


# ── Void terminality ──────────────────────────────────────────────────────────


@settings(max_examples=30)
@given(amount=amounts)
def test_void_is_terminal(amount):
    """For any amount: a second void on an already-voided transaction raises ValueError."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        guid = receive_invoice(TEST_DATE, "Acme Architecture", "INV-001", amount, EXPENSE_ACCT)[
            "transaction_guid"
        ]

        void_transaction(guid, reason="First void")

        with pytest.raises(ValueError):
            void_transaction(guid, reason="Second void attempt")
