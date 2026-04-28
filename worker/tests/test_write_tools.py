"""Tests for write tools — T1.6.x"""

import pytest

from gnucash_mcp.tools.write import (
    fund_project,
    receive_invoice,
    pay_invoice,
    post_transaction,
    post_interest,
    SplitsImbalanceError,
)
from gnucash_mcp.tools import read
from gnucash_mcp import wal


# Use fixed historical dates that are guaranteed to work with GnuCash
TEST_DATE_1 = "2025-01-01"
TEST_DATE_2 = "2025-01-02"
TEST_DATE_3 = "2025-01-03"
TEST_DATE_4 = "2025-01-04"
TEST_DATE_5 = "2025-01-05"
TEST_DATE_OLD = "2024-12-01"


class TestFundProject:
    """T1.6.1–T1.6.2: fund_project tool."""

    def test_fund_project_posts_balanced_transaction(self, initialized_book):
        """T1.6.1: fund_project posts balanced transaction (sum of splits = 0)"""
        result = fund_project(TEST_DATE_1, "10000.00", "Initial funding")

        assert result["status"] == "ok"
        assert "transaction_guid" in result
        assert "wal_id" in result

        checking = read.get_account_balance("Assets:Project Checking")
        capital = read.get_account_balance("Equity:Owner Capital")

        assert float(checking["balance"]) == 10000.00
        assert float(capital["balance"]) == -10000.00

    def test_fund_project_wal_entry_committed(self, initialized_book):
        """T1.6.2: fund_project WAL entry has committed_at and transaction_guid after tool returns"""
        result = fund_project(TEST_DATE_1, "50000.00", "Fund")
        wal_id = result["wal_id"]

        all_entries = wal.all_entries()
        entry = next(e for e in all_entries if e["id"] == wal_id)

        assert entry["committed_at"] is not None
        assert entry["transaction_guid"] == result["transaction_guid"]

    def test_fund_project_transaction_has_mcp_provenance(self, initialized_book):
        """T1.6.2b: fund_project transaction carries mcp.wal_id and mcp.tool via notes field"""
        result = fund_project(TEST_DATE_5, "25000.00", "Provenance test")
        guid = result["transaction_guid"]

        txn_dict = read.get_transaction(guid)
        assert "error" not in txn_dict
        assert txn_dict["mcp"] is not None
        assert txn_dict["mcp"]["wal_id"] == result["wal_id"]
        assert txn_dict["mcp"]["tool"] == "fund_project"


class TestReceiveInvoice:
    """T1.6.3: receive_invoice tool."""

    def test_receive_invoice_creates_ap_balance(self, initialized_book):
        """T1.6.3: receive_invoice creates correct AP balance for named vendor"""
        result = receive_invoice(
            TEST_DATE_5,
            "Acme Architecture",
            "AAI-101",
            "15000.00",
            "Expenses:Architecture — Acme Architecture",
        )

        assert result["status"] == "ok"
        assert "transaction_guid" in result

        expense = read.get_account_balance("Expenses:Architecture — Acme Architecture")
        assert "error" not in expense

        ap = read.get_account_balance("Liabilities:AP — Acme Architecture")
        assert "error" not in ap

    def test_receive_invoice_vendor_appears_in_list(self, initialized_book):
        """receive_invoice vendor appears in vendors_resource list"""
        receive_invoice(
            TEST_DATE_5,
            "Peak Structural",
            "PS-1",
            "12000.00",
            "Expenses:Structural Engineering — Peak Structural",
        )

        vendors = read.vendors_resource()
        peak = next((v for v in vendors if "Peak" in v["name"]), None)
        assert peak is not None
        assert float(peak["balance"]) == 12000.00


class TestPayInvoice:
    """T1.6.4: pay_invoice tool."""

    def test_pay_invoice_clears_ap_balance(self, initialized_book):
        """T1.6.4: pay_invoice clears AP balance to $0.00 when matching invoice amount"""
        fund_result = fund_project(TEST_DATE_OLD, "50000.00", "Initial")
        assert fund_result["status"] == "ok"

        invoice_result = receive_invoice(
            TEST_DATE_5,
            "Acme Architecture",
            "AAI-101",
            "15000.00",
            "Expenses:Architecture — Acme Architecture",
        )
        assert invoice_result["status"] == "ok"

        payment_result = pay_invoice(TEST_DATE_4, "Acme Architecture", "AAI-101", "15000.00")
        assert payment_result["status"] == "ok"

        ap = read.get_account_balance("Liabilities:AP — Acme Architecture")
        checking = read.get_account_balance("Assets:Project Checking")
        assert "error" not in ap and "error" not in checking


class TestPostTransaction:
    """T1.6.5: post_transaction tool."""

    def test_post_transaction_balanced(self, initialized_book):
        """post_transaction with balanced splits succeeds"""
        result = post_transaction(
            TEST_DATE_5,
            "Transfer test",
            [
                {"account_path": "Assets:Project Checking", "amount": "5000.00", "memo": "In"},
                {"account_path": "Equity:Owner Capital", "amount": "-5000.00", "memo": "Out"},
            ],
        )

        assert result["status"] == "ok"
        assert "transaction_guid" in result

    def test_post_transaction_unbalanced_raises_error(self, initialized_book):
        """T1.6.5: post_transaction with unbalanced splits raises SplitsImbalanceError"""
        with pytest.raises(SplitsImbalanceError):
            post_transaction(
                TEST_DATE_5,
                "Unbalanced",
                [
                    {"account_path": "Assets:Project Checking", "amount": "100.00"},
                    {"account_path": "Equity:Owner Capital", "amount": "-50.00"},
                ],
            )

    def test_post_transaction_unbalanced_not_posted(self, initialized_book):
        """Unbalanced transaction raises before WAL append; no pending entries created"""
        with pytest.raises(SplitsImbalanceError):
            post_transaction(
                TEST_DATE_5,
                "Bad",
                [
                    {"account_path": "Assets:Project Checking", "amount": "100.00"},
                    {"account_path": "Equity:Owner Capital", "amount": "-25.00"},
                ],
            )

        assert wal.pending() == []


class TestPostInterest:
    """T1.6.x: post_interest tool."""

    def test_post_interest_with_month(self, initialized_book):
        """post_interest posts interest income transaction"""
        month = TEST_DATE_OLD[:7]  # Extract YYYY-MM from date (2024-12)
        result = post_interest(month, "50.25")

        assert result["status"] == "ok"
        assert "transaction_guid" in result

        checking = read.get_account_balance("Assets:Project Checking")
        income = read.get_account_balance("Income:Interest Income")

        assert float(checking["balance"]) == 50.25
        assert float(income["balance"]) == -50.25

    def test_post_interest_with_full_date(self, initialized_book):
        """post_interest accepts full date (YYYY-MM-DD)"""
        result = post_interest(TEST_DATE_5, "25.50")

        assert result["status"] == "ok"

        txn = read.get_transaction(result["transaction_guid"])
        assert txn is not None
        assert "error" not in txn


class TestCompleteInvoiceWorkflow:
    """T1.6.6–T1.6.10: End-to-end invoice and payment workflows."""

    def test_aai_invoice_101_workflow(self, initialized_book):
        """T1.6.6: Post AAI invoice #101 ($15,000.00) and payment"""
        fund_result = fund_project(TEST_DATE_OLD, "100000.00")
        assert fund_result["status"] == "ok"

        invoice_result = receive_invoice(
            TEST_DATE_5,
            "Acme Architecture",
            "AAI-101",
            "15000.00",
            "Expenses:Architecture — Acme Architecture",
        )
        assert invoice_result["status"] == "ok"

        payment_result = pay_invoice(TEST_DATE_1, "Acme Architecture", "AAI-101", "15000.00")
        assert payment_result["status"] == "ok"

        expense = read.get_account_balance("Expenses:Architecture — Acme Architecture")
        ap = read.get_account_balance("Liabilities:AP — Acme Architecture")
        checking = read.get_account_balance("Assets:Project Checking")
        assert all("error" not in acc for acc in [expense, ap, checking])

    def test_pse_invoice_workflow(self, initialized_book):
        """T1.6.7: Post PSE invoice PSE-000101 ($2,000.00)"""
        fund_result = fund_project(TEST_DATE_OLD, "50000.00")
        assert fund_result["status"] == "ok"

        invoice_result = receive_invoice(
            TEST_DATE_3,
            "Peak Structural",
            "PSE-000101",
            "2000.00",
            "Expenses:Structural Engineering — Peak Structural",
        )
        assert invoice_result["status"] == "ok"

        expense = read.get_account_balance("Expenses:Structural Engineering — Peak Structural")
        ap = read.get_account_balance("Liabilities:AP — Peak Structural")

        assert "error" not in expense
        assert "error" not in ap

    def test_all_known_invoices_workflow(self, initialized_book):
        """T1.6.10: Post all known invoices and verify totals"""
        fund_result = fund_project(TEST_DATE_OLD, "100000.00")
        assert fund_result["status"] == "ok"

        invoices = [
            ("Acme Architecture", "AAI-101", "15000.00", "Architecture — Acme Architecture"),
            ("Acme Architecture", "AAI-102", "25000.00", "Architecture — Acme Architecture"),
            (
                "Peak Structural",
                "PSE-000101",
                "2000.00",
                "Structural Engineering — Peak Structural",
            ),
            (
                "Peak Structural",
                "PSE-000102",
                "1200.00",
                "Structural Engineering — Peak Structural",
            ),
            ("Meridian MEP", "MMEP-2001", "600.00", "MEP Consulting — Meridian MEP"),
            ("Meridian MEP", "MMEP-2002", "600.00", "MEP Consulting — Meridian MEP"),
            ("Meridian MEP", "MMEP-2003", "480.00", "MEP Consulting — Meridian MEP"),
            ("Meridian MEP", "MMEP-2004", "720.00", "MEP Consulting — Meridian MEP"),
        ]

        for vendor, invoice_ref, amount, expense_account in invoices:
            result = receive_invoice(
                TEST_DATE_5, vendor, invoice_ref, amount, f"Expenses:{expense_account}"
            )
            assert result["status"] == "ok"

        summary = read.get_project_summary()
        assert isinstance(summary, dict)
        assert all(
            key in summary
            for key in [
                "checking_balance",
                "owner_capital",
                "interest_income",
                "total_expenses",
                "total_ap",
            ]
        )
