"""Property-based tests for ECO state machine and numeric round-trips.

Each Hypothesis example needs a fresh GnuCash book — shared book state
(duplicate ECO numbers, accumulated budget entries) would poison later
examples. We create and tear down a book inline per example rather than
using pytest fixtures.
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
from gnucash_mcp.tools.budget import budget_create, budget_get, budget_set_amount
from gnucash_mcp.tools.eco import eco_approve, eco_create, eco_get, eco_void
from gnucash_mcp.tools.write import fund_project

ELECTRICAL_ACCOUNT = "Expenses:Construction:Electrical"
TEST_DATE = "2025-06-01"
TEST_DATE_2 = "2025-06-15"

amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(str)

directions = st.sampled_from(["additive", "deductive"])


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
            mk(liabilities, "AP — Pacific Crest Electrical", gc.ACCT_TYPE_PAYABLE)
            equity = mk(root, "Equity", gc.ACCT_TYPE_EQUITY)
            mk(equity, "Owner Capital", gc.ACCT_TYPE_EQUITY)
            expenses = mk(root, "Expenses", gc.ACCT_TYPE_EXPENSE)
            construction = mk(expenses, "Construction", gc.ACCT_TYPE_EXPENSE)
            mk(construction, "Electrical", gc.ACCT_TYPE_EXPENSE)
            change_orders = mk(expenses, "Change Orders", gc.ACCT_TYPE_EXPENSE)
            mk(change_orders, "Electrical", gc.ACCT_TYPE_EXPENSE)

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


# ── Numeric round-trip ────────────────────────────────────────────────────────


@settings(max_examples=40)
@given(amount=amounts, direction=directions)
def test_approve_then_void_is_net_zero(amount, direction):
    """For any amount and direction: approve(CO) then void(CO) leaves budget and
    Change Orders balance exactly where they started."""
    from gnucash_mcp.tools.read import get_account_balance

    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "100000.00")

        budgeted_before = next(
            a["budgeted"]
            for a in budget_get("GC Budget")["accounts"]
            if a["account"] == ELECTRICAL_ACCOUNT
        )
        bal_before = get_account_balance("Expenses:Change Orders:Electrical")["balance"]

        eco_create(
            "CO-001",
            description="Round-trip test",
            direction=direction,
            amount=amount,
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)
        eco_void("CO-001", reason="Round-trip void")

        budgeted_after = next(
            a["budgeted"]
            for a in budget_get("GC Budget")["accounts"]
            if a["account"] == ELECTRICAL_ACCOUNT
        )
        bal_after = get_account_balance("Expenses:Change Orders:Electrical")["balance"]

        assert budgeted_after == budgeted_before
        assert bal_after == bal_before


@settings(max_examples=40)
@given(amount=amounts, direction=directions)
def test_approve_changes_budget_by_exact_amount(amount, direction):
    """For any amount and direction: approve changes budget by exactly ±amount
    (additive increases, deductive decreases)."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "100000.00")

        before = Decimal(
            next(
                a["budgeted"]
                for a in budget_get("GC Budget")["accounts"]
                if a["account"] == ELECTRICAL_ACCOUNT
            )
        )

        eco_create(
            "CO-001",
            description="Delta test",
            direction=direction,
            amount=amount,
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        after = Decimal(
            next(
                a["budgeted"]
                for a in budget_get("GC Budget")["accounts"]
                if a["account"] == ELECTRICAL_ACCOUNT
            )
        )

        delta = after - before
        if direction == "additive":
            assert delta == Decimal(amount)
        else:
            assert delta == -Decimal(amount)


# ── State machine ─────────────────────────────────────────────────────────────
#
# The ECO state machine has three states and two transitions:
#
#   pending ──approve──▶ approved
#   pending ──void────▶ void
#   approved ──void───▶ void
#
# Any other call (approve×2, void×2, approve after void) must raise ValueError.
# We model this with @given over lists of actions and verify the state machine
# contract holds for every generated sequence.


def _model_transition(current_status: str, action: str) -> str | None:
    """Return next status if the transition is valid, else None."""
    valid = {
        ("pending", "approve"): "approved",
        ("pending", "void"): "void",
        ("approved", "void"): "void",
    }
    return valid.get((current_status, action))


@settings(max_examples=200)
@given(actions=st.lists(st.sampled_from(["approve", "void"]), min_size=1, max_size=12))
def test_state_machine_transitions(actions):
    """For any sequence of approve/void calls: valid transitions succeed,
    invalid transitions raise ValueError, and eco_get always agrees with
    the model's expected status."""
    with _fresh_book():
        fund_project(TEST_DATE, "999999.99")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "100000.00")

        eco_create(
            "CO-001",
            description="State machine test",
            direction="additive",
            amount="1000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )

        model_status = "pending"

        for action in actions:
            next_status = _model_transition(model_status, action)

            if next_status is not None:
                if action == "approve":
                    result = eco_approve("CO-001", date=TEST_DATE)
                    assert result["status"] == "ok"
                else:
                    result = eco_void("CO-001", reason="State machine void")
                    assert result["status"] == "ok"
                model_status = next_status
            else:
                if action == "approve":
                    with pytest.raises(ValueError):
                        eco_approve("CO-001", date=TEST_DATE)
                else:
                    with pytest.raises(ValueError):
                        eco_void("CO-001", reason="Should fail")

            assert eco_get("CO-001")["status"] == model_status
