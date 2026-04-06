"""Tests for read tools — T1.5.x"""

import os
from decimal import Decimal

import pytest

from gnucash_mcp.tools import read
from gnucash_mcp.session import book_session, get_account
from gnucash_mcp.tools.write import fund_project
from gnucash_mcp import wal


class TestReadToolsBasics:
    """T1.5.1–T1.5.9: Read tool functionality."""

    def test_get_account_balance_returns_dict(self, initialized_book):
        """T1.5.4: get_account_balance returns correct balance after a known funding entry"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        # Fund the project with $50,000
        fund_project("2025-01-01", "50000.00", "Initial funding")

        # Query the balance
        result = read.get_account_balance("Assets:Project Checking")

        assert isinstance(result, dict)
        assert "account" in result
        assert "balance" in result
        assert "currency" in result
        assert result["account"] == "Assets:Project Checking"
        assert result["currency"] == "USD"
        # Balance should be $50,000
        assert float(result["balance"]) == 50000.00

    def test_get_account_balance_missing_account(self, initialized_book):
        """get_account_balance with missing account returns error dict"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        result = read.get_account_balance("Assets:Nonexistent")
        assert "error" in result

    def test_list_accounts_root(self, initialized_book):
        """T1.5.5: list_accounts(None) returns all top-level account names"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        result = read.list_accounts(None)

        assert isinstance(result, list)
        assert len(result) > 0

        names = {acc["name"] for acc in result}
        assert "Assets" in names
        assert "Liabilities" in names
        assert "Equity" in names
        assert "Income" in names
        assert "Expenses" in names

    def test_list_accounts_with_parent(self, initialized_book):
        """list_accounts with parent path returns children"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        result = read.list_accounts("Assets")

        assert isinstance(result, list)
        assert len(result) > 0
        assert any(acc["name"] == "Project Checking" for acc in result)

    def test_list_accounts_missing_parent(self, initialized_book):
        """list_accounts with missing parent returns error"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        result = read.list_accounts("Assets:Nonexistent")
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    def test_list_transactions_empty(self, initialized_book):
        """T1.5.6: list_transactions with limit=5 returns at most 5 entries, newest first"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        result = read.list_transactions("Assets:Project Checking", limit=5)

        # Initially empty
        assert isinstance(result, list)
        assert len(result) == 0

    def test_list_transactions_with_data(self, initialized_book):
        """list_transactions returns posted transactions"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        # Post two transactions
        fund_project("2025-01-01", "10000.00", "Fund 1")
        fund_project("2025-01-02", "20000.00", "Fund 2")

        result = read.list_transactions("Assets:Project Checking", limit=5)

        assert len(result) == 2
        # Newest first
        assert result[0]["date"] == "2025-01-02"
        assert result[1]["date"] == "2025-01-01"

    def test_list_transactions_respects_limit(self, initialized_book):
        """list_transactions respects limit parameter"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        # Post three transactions
        for i in range(1, 4):
            fund_project(f"2025-01-{i:02d}", f"{i*1000}.00", f"Fund {i}")

        result = read.list_transactions("Assets:Project Checking", limit=2)
        assert len(result) == 2

    def test_get_transaction_by_guid(self, initialized_book):
        """get_transaction fetches transaction by GUID"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        # Post a transaction
        result = fund_project("2025-01-01", "30000.00", "Test fund")
        guid = result["transaction_guid"]

        # Fetch it
        txn_dict = read.get_transaction(guid)

        assert "error" not in txn_dict
        assert txn_dict["guid"] == guid
        assert txn_dict["date"] == "2025-01-01"
        assert txn_dict["description"] == "Fund project: Test fund"
        assert len(txn_dict["splits"]) == 2

    def test_get_transaction_missing(self, initialized_book):
        """get_transaction with missing GUID returns error"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        result = read.get_transaction("fake-guid-12345")
        assert "error" in result

    def test_get_project_summary(self, initialized_book):
        """T1.5.7: get_project_summary() all five fields present and non-null"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        # Post some transactions
        fund_project("2025-01-01", "50000.00", "Initial")

        result = read.get_project_summary()

        assert isinstance(result, dict)
        # All fields should be present
        required_fields = {
            "checking_balance", "owner_capital",
            "interest_income", "total_expenses", "total_ap"
        }
        assert set(result.keys()) == required_fields

        # Verify types
        for key in required_fields:
            assert result[key] is not None
            # Values should be stringified floats or None
            assert isinstance(result[key], (str, type(None)))

    def test_project_summary_balances_correct(self, initialized_book):
        """get_project_summary returns correct computed balances"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        fund_project("2025-01-01", "100000.00", "Initial")

        result = read.get_project_summary()

        assert float(result["checking_balance"]) == 100000.00
        assert float(result["owner_capital"]) == -100000.00  # Credit

    def test_get_audit_log_empty(self, initialized_book, test_wal_path):
        """T1.5.8: get_audit_log returns WAL entries"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        result = read.get_audit_log()
        assert isinstance(result, list)
        assert len(result) == 0  # No entries yet

    def test_get_audit_log_with_entries(self, initialized_book, test_wal_path):
        """get_audit_log returns entries in reverse chronological order"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)
        os.environ["GNUCASH_WAL_PATH"] = str(test_wal_path)
        wal.init(test_wal_path)

        fund_project("2025-01-01", "10000.00", "Fund 1")
        fund_project("2025-01-02", "20000.00", "Fund 2")

        result = read.get_audit_log()
        assert len(result) >= 2
        # Should be reversed (newest first)
        assert result[0]["logged_at"] >= result[1]["logged_at"]

    def test_vendors_resource_empty(self, initialized_book):
        """vendors_resource returns empty list initially"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        result = read.vendors_resource()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_vendors_resource_with_ap(self, initialized_book):
        """vendors_resource returns AP vendors with balances"""
        os.environ["GNUCASH_BOOK_PATH"] = str(initialized_book)

        from gnucash_mcp.tools.write import receive_invoice

        # Create an invoice
        receive_invoice(
            "2025-01-01", "Acme Architecture", "AAI-001",
            "15000.00", "Expenses:Architecture — Acme Architecture"
        )

        result = read.vendors_resource()
        assert len(result) > 0

        # Find Acme Architecture
        acme = next((v for v in result if "Acme" in v["name"]), None)
        assert acme is not None
        assert float(acme["balance"]) == 15000.00
