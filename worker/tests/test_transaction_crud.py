"""Tests for Phase 3 transaction CRUD and audit log — T3.1.x, T3.2.x"""

import os
import time

import pytest

from gnucash_mcp.tools.write import (
    fund_project,
    receive_invoice,
    update_transaction,
    void_transaction,
    delete_transaction,
    RequiresConfirmationError,
)
from gnucash_mcp.tools.read import get_transaction, get_audit_log
from gnucash_mcp import wal


TEST_DATE_1 = "2025-01-01"
TEST_DATE_2 = "2025-01-02"
TEST_DATE_3 = "2025-01-03"


def _post_invoice(
    book_path, *, date=TEST_DATE_1, vendor="Acme Architecture", ref="AAI-001", amount="5000.00"
):
    """Helper: receive an invoice and return the result dict."""
    os.environ["GNUCASH_BOOK_PATH"] = str(book_path)
    return receive_invoice(
        date,
        vendor,
        ref,
        amount,
        "Expenses:Architecture — Acme Architecture",
    )


# ── M3.1 Transaction correction tools ────────────────────────────────────────


class TestUpdateTransaction:
    """T3.1.1–T3.1.3: update_transaction."""

    def test_update_description(self, initialized_book, test_wal_path):
        """T3.1.1: update_transaction changes description; balance and splits unchanged."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        guid = result["transaction_guid"]

        before = get_transaction(guid)
        assert "error" not in before

        update_result = update_transaction(guid, description="Updated description")
        assert update_result["status"] == "ok"

        after = get_transaction(guid)
        assert after["description"] == "Updated description"

        # Splits and balance must be unchanged
        assert len(after["splits"]) == len(before["splits"])

    def test_update_date(self, initialized_book, test_wal_path):
        """T3.1.2: update_transaction changes date; transaction appears at new date."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book, date=TEST_DATE_1)
        guid = result["transaction_guid"]

        update_transaction(guid, date=TEST_DATE_2)

        after = get_transaction(guid)
        assert after["date"] == TEST_DATE_2

    def test_update_no_fields_is_noop(self, initialized_book, test_wal_path):
        """T3.1.3: update_transaction with no fields changed returns unchanged record."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        guid = result["transaction_guid"]

        before = get_transaction(guid)
        update_result = update_transaction(guid)
        assert update_result["status"] == "ok"

        after = get_transaction(guid)
        assert after["description"] == before["description"]
        assert after["date"] == before["date"]


class TestVoidTransaction:
    """T3.1.4–T3.1.6: void_transaction."""

    def test_void_zeroes_balance_effect(self, initialized_book, test_wal_path):
        """T3.1.4: void_transaction zeroes account balance effect."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        from gnucash_mcp.tools.read import get_account_balance

        result = _post_invoice(initialized_book, amount="8000.00")
        guid = result["transaction_guid"]

        before_bal = float(
            get_account_balance("Expenses:Architecture — Acme Architecture")["balance"]
        )
        assert before_bal == 8000.00

        void_transaction(guid, reason="Posted in error")

        after_bal = float(
            get_account_balance("Expenses:Architecture — Acme Architecture")["balance"]
        )
        assert after_bal == 0.0

    def test_void_records_reason(self, initialized_book, test_wal_path):
        """T3.1.5: void_transaction records reason in transaction notes."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        guid = result["transaction_guid"]

        void_transaction(guid, reason="Duplicate entry")

        txn = get_transaction(guid)
        assert txn["is_void"] is True
        assert "Duplicate entry" in (txn["void_reason"] or "")

    def test_void_already_voided_raises(self, initialized_book, test_wal_path):
        """T3.1.6: void_transaction on already-voided transaction raises ValueError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        guid = result["transaction_guid"]

        void_transaction(guid, reason="First void")

        with pytest.raises(ValueError):
            void_transaction(guid, reason="Second void attempt")


class TestDeleteTransaction:
    """T3.1.7–T3.1.8: delete_transaction."""

    def test_delete_without_confirm_raises(self, initialized_book, test_wal_path):
        """T3.1.7: delete_transaction without confirm=True raises RequiresConfirmationError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        guid = result["transaction_guid"]

        with pytest.raises(RequiresConfirmationError):
            delete_transaction(guid)

    def test_delete_with_confirm_removes_transaction(self, initialized_book, test_wal_path):
        """T3.1.8: delete_transaction with confirm=True removes transaction; balance corrected."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        from gnucash_mcp.tools.read import get_account_balance

        result = _post_invoice(initialized_book, amount="3000.00")
        guid = result["transaction_guid"]

        bal_before = float(
            get_account_balance("Expenses:Architecture — Acme Architecture")["balance"]
        )
        assert bal_before == 3000.00

        del_result = delete_transaction(guid, confirm=True)
        assert del_result["status"] == "ok"

        # Transaction should no longer be findable
        txn = get_transaction(guid)
        assert "error" in txn

        # Balance should be zero again
        bal_after = float(
            get_account_balance("Expenses:Architecture — Acme Architecture")["balance"]
        )
        assert bal_after == 0.0


class TestGetTransaction:
    """T3.1.9–T3.1.10: get_transaction return shape."""

    def test_returns_splits_with_account_paths_and_reconcile_state(
        self, initialized_book, test_wal_path
    ):
        """T3.1.9: get_transaction returns all splits with full account paths and reconcile_state."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book, amount="7500.00", ref="AAI-099")
        guid = result["transaction_guid"]

        txn = get_transaction(guid)
        assert "error" not in txn
        assert len(txn["splits"]) == 2

        account_paths = {s["account"] for s in txn["splits"]}
        assert "Expenses:Architecture — Acme Architecture" in account_paths
        assert "Liabilities:AP — Acme Architecture" in account_paths

        for split in txn["splits"]:
            assert "reconcile_state" in split

    def test_voided_transaction_shows_void_status(self, initialized_book, test_wal_path):
        """T3.1.10: get_transaction on voided transaction shows void status and reason."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        guid = result["transaction_guid"]

        void_transaction(guid, reason="Wrong amount")

        txn = get_transaction(guid)
        assert txn["is_void"] is True
        assert txn["void_reason"] is not None
        assert "Wrong amount" in txn["void_reason"]

    def test_mcp_slots_on_mcp_posted_transaction(self, initialized_book, test_wal_path):
        """T3.1.12: get_transaction on MCP-posted transaction returns mcp.wal_id and mcp.tool."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        guid = result["transaction_guid"]
        wal_id = result["wal_id"]

        txn = get_transaction(guid)
        assert txn["mcp"] is not None
        assert txn["mcp"]["wal_id"] == wal_id
        assert txn["mcp"]["tool"] == "receive_invoice"

    def test_gui_posted_transaction_has_null_mcp(self, initialized_book, test_wal_path):
        """T3.1.13: get_transaction on GUI-posted transaction (no slots) returns mcp: null."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        # Post a bare transaction without MCP slots via book_set_opening_balance
        from gnucash_mcp.tools.book import book_set_opening_balance

        book_set_opening_balance("Assets:Project Checking", "1000.00", TEST_DATE_1)

        # Fetch via get_transaction — this came through the MCP (book_set_opening_balance
        # does call WAL), so instead post one directly via session without slots
        from gnucash_mcp.session import (
            book_session,
            book_path,
            new_transaction,
            set_txn_isodate,
            get_account,
            get_usd,
            gnc_decimal,
        )
        from gnucash import Split

        with book_session(book_path()) as session:
            book = session.book
            checking = get_account(book, "Assets:Project Checking")
            equity = get_account(book, "Equity:Owner Capital")
            with new_transaction(book) as txn:
                set_txn_isodate(txn, TEST_DATE_3)
                txn.SetDescription("GUI-style entry")
                txn.SetCurrency(get_usd(book))
                for acc, amt in [(checking, "100.00"), (equity, "-100.00")]:
                    s = Split(book)
                    s.SetParent(txn)
                    s.SetAccount(acc)
                    a = gnc_decimal(amt)
                    s.SetAmount(a)
                    s.SetValue(a)
            no_slot_guid = txn.GetGUID().to_string()

        txn_dict = get_transaction(no_slot_guid)
        assert "error" not in txn_dict
        assert txn_dict["mcp"] is None

    def test_wal_guid_matches_get_transaction_guid(self, initialized_book, test_wal_path):
        """T3.1.14: WAL transaction_guid matches guid field in get_transaction output."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = _post_invoice(initialized_book)
        wal_guid = result["transaction_guid"]
        wal_id = result["wal_id"]

        txn = get_transaction(wal_guid)
        assert txn["guid"] == wal_guid

        # Reverse: WAL entry transaction_guid matches
        entries = wal.all_entries()
        entry = next(e for e in entries if e["id"] == wal_id)
        assert entry["transaction_guid"] == txn["guid"]


class TestVoidCorrectionWorkflow:
    """T3.1.11: End-to-end correction workflow."""

    def test_void_and_repost_corrects_balance(self, initialized_book, test_wal_path):
        """T3.1.11: Post wrong amount → void → repost correct amount → balance matches expected."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        from gnucash_mcp.tools.read import get_account_balance

        # Post wrong amount
        wrong = _post_invoice(initialized_book, amount="5000.00", ref="AAI-100")
        void_transaction(wrong["transaction_guid"], reason="Wrong amount — correct is 5500.00")

        # Post correct amount
        _post_invoice(initialized_book, amount="5500.00", ref="AAI-100-R")

        ap_bal = float(get_account_balance("Liabilities:AP — Acme Architecture")["balance"])
        exp_bal = float(get_account_balance("Expenses:Architecture — Acme Architecture")["balance"])

        # Void zeroes the first; only the correcting entry should show
        assert ap_bal == -5500.00
        assert exp_bal == 5500.00


# ── M3.2 Audit log tool ───────────────────────────────────────────────────────


class TestGetAuditLog:
    """T3.2.1–T3.2.7: get_audit_log."""

    def test_returns_reverse_chronological_order(self, initialized_book, test_wal_path):
        """T3.2.1: get_audit_log returns entries in reverse chronological order."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        _post_invoice(initialized_book, ref="AAI-A01")
        time.sleep(0.01)
        _post_invoice(initialized_book, ref="AAI-A02")

        entries = get_audit_log()
        assert len(entries) >= 2
        for i in range(len(entries) - 1):
            assert entries[i]["logged_at"] >= entries[i + 1]["logged_at"]

    def test_limit_caps_results(self, initialized_book, test_wal_path):
        """T3.2.2: limit=5 returns at most 5 entries."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        for i in range(8):
            _post_invoice(initialized_book, ref=f"AAI-L{i:02d}")

        entries = get_audit_log(limit=5)
        assert len(entries) <= 5

    def test_tool_filter(self, initialized_book, test_wal_path):
        """T3.2.3: tool_filter='receive_invoice' returns only invoice receipt entries."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        fund_project(TEST_DATE_1, "1000.00")
        _post_invoice(initialized_book, ref="AAI-F01")

        entries = get_audit_log(tool_filter="receive_invoice")
        assert len(entries) >= 1
        assert all(e["type"] == "receive_invoice" for e in entries)

    def test_since_date_filter(self, initialized_book, test_wal_path):
        """T3.2.4: since_date filters to entries logged after the given date."""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        _post_invoice(initialized_book, ref="AAI-SD01")

        # Use a future cutoff that filters everything out
        entries = get_audit_log(since_date="2099-01-01")
        assert entries == []

    def test_uncommitted_entries_appear_with_null_committed_at(self, test_wal_path, tmp_path):
        """T3.2.5: Uncommitted WAL entries appear with committed_at: null."""
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        # Manually append a pending entry without committing it
        wal.append("receive_invoice", {"date": TEST_DATE_1, "vendor": "Test"})

        entries = get_audit_log()
        pending = [e for e in entries if e["committed_at"] is None]
        assert len(pending) >= 1

    def test_does_not_open_gnucash_session(self, test_wal_path, monkeypatch):
        """T3.2.6: get_audit_log is a pure file read — does not call book_session."""
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        opened = []

        # Patch book_session to detect if it's called
        import gnucash_mcp.session as session_mod

        original_bs = session_mod.book_session

        def spy(*args, **kwargs):
            opened.append(True)
            return original_bs(*args, **kwargs)

        monkeypatch.setattr(session_mod, "book_session", spy)

        get_audit_log()
        assert opened == [], "get_audit_log must not open a GnuCash session"

    def test_empty_wal_returns_empty_list(self, test_wal_path):
        """T3.2.7: Empty WAL returns empty list, not an error."""
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        # WAL file doesn't exist yet
        entries = get_audit_log()
        assert entries == []
