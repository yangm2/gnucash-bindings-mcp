"""Tests for vendor management tools — T2.2.x"""

import os
import pytest

from gnucash_mcp.tools.vendor import (
    vendor_add,
    vendor_list,
    vendor_get_details,
    vendor_rename,
    vendor_update,
    vendor_delete,
    vendor_guide_resource,
    RequiresConfirmationError,
    VendorHasHistoryError,
)
from gnucash_mcp.session import AccountNotFoundError
from gnucash_mcp.tools import read
from gnucash_mcp.tools.write import fund_project, receive_invoice, pay_invoice

TEST_DATE = "2025-03-01"
TEST_DATE_2 = "2025-03-15"


class TestVendorAddTrade:
    """T2.2.1, T2.2.3–T2.2.6: vendor_add for trade vendors."""

    def test_creates_only_ap_account(self, full_book):
        """T2.2.1: trade vendor creates only AP account; no new expense account."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        result = vendor_add(
            "Pacific Crest Electrical",
            trade="Expenses:Construction:Electrical",
        )

        assert result["status"] == "ok"

        # AP account exists
        ap = read.get_account_balance("Liabilities:AP — Pacific Crest Electrical")
        assert "error" not in ap

        # No new expense account created under Electrical
        from gnucash_mcp.tools.book import book_get_account_tree

        elec_children = book_get_account_tree("Expenses:Construction:Electrical")
        names = [a["name"] for a in elec_children]
        assert "Pacific Crest Electrical" not in names

    def test_both_args_raises(self, full_book):
        """T2.2.3: specifying both trade and expense_category raises ValueError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        with pytest.raises(ValueError):
            vendor_add(
                "Confusion Co",
                trade="Expenses:Construction:Electrical",
                expense_category="Architecture",
            )

    def test_neither_arg_raises(self, full_book):
        """T2.2.4: specifying neither trade nor expense_category raises ValueError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        with pytest.raises(ValueError):
            vendor_add("Mystery Vendor")

    def test_nonexistent_trade_path_raises(self, full_book):
        """T2.2.5: non-existent trade path raises AccountNotFoundError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        with pytest.raises(AccountNotFoundError):
            vendor_add("Ghost Sub", trade="Expenses:Construction:Nonexistent")

    def test_idempotent_no_duplicate_ap(self, full_book):
        """T2.2.6: calling vendor_add twice with same name does not duplicate AP account."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Pacific Crest Electrical", trade="Expenses:Construction:Electrical")
        vendor_add("Pacific Crest Electrical", trade="Expenses:Construction:Electrical")

        from gnucash_mcp.tools.book import book_get_account_tree

        ap_accounts = book_get_account_tree("Liabilities")
        names = [a["name"] for a in ap_accounts]
        assert names.count("AP — Pacific Crest Electrical") == 1


class TestVendorAddProfessional:
    """T2.2.2: vendor_add for professional vendors."""

    def test_creates_both_accounts(self, full_book):
        """T2.2.2: professional vendor creates AP and dedicated expense accounts."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        result = vendor_add(
            "Hillside Architecture",
            expense_category="Architecture",
        )

        assert result["status"] == "ok"

        # Both accounts must exist
        ap = read.get_account_balance("Liabilities:AP — Hillside Architecture")
        assert "error" not in ap

        expense = read.get_account_balance("Expenses:Architecture — Hillside Architecture")
        assert "error" not in expense


class TestVendorList:
    """T2.2.7–T2.2.9: vendor_list."""

    def test_includes_new_trade_vendor(self, full_book):
        """T2.2.7: newly added trade vendor appears in list with $0 balance."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("River City Framing", trade="Expenses:Construction:Framing")

        vendors = vendor_list()
        vendor = next((v for v in vendors if v["name"] == "River City Framing"), None)

        assert vendor is not None
        assert float(vendor["balance"]) == 0.00

    def test_trade_shows_trade_path_professional_shows_expense_path(self, full_book):
        """T2.2.8: list shows trade path for trade vendors, expense path for professional."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("River City Framing", trade="Expenses:Construction:Framing")
        vendor_add("Summit Design Group", expense_category="Architecture")

        vendors = vendor_list()
        trade_v = next(v for v in vendors if v["name"] == "River City Framing")
        prof_v = next(v for v in vendors if v["name"] == "Summit Design Group")

        assert trade_v["type"] == "trade"
        assert "Framing" in trade_v["trade_path"]

        assert prof_v["type"] == "professional"
        assert "Summit Design Group" in prof_v["expense_path"]

    def test_shows_ap_balance_after_invoice(self, full_book):
        """T2.2.9: AP balance reflects received invoice."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Summit Design Group", expense_category="Architecture")
        fund_project("2025-01-01", "100000.00")
        receive_invoice(
            TEST_DATE,
            "Summit Design Group",
            "SDG-001",
            "8000.00",
            "Expenses:Architecture — Summit Design Group",
        )

        vendors = vendor_list()
        v = next(v for v in vendors if v["name"] == "Summit Design Group")
        assert float(v["balance"]) == 8000.00


class TestVendorGetDetails:
    """T2.2.13: vendor_get_details."""

    def test_returns_correct_fields_for_new_vendor(self, full_book):
        """T2.2.13: returns type, paths, and $0 balance for a new vendor."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Cascade Plumbing", trade="Expenses:Construction:Plumbing")

        details = vendor_get_details("Cascade Plumbing")

        assert details["name"] == "Cascade Plumbing"
        assert details["type"] == "trade"
        assert "AP — Cascade Plumbing" in details["ap_path"]
        assert "Plumbing" in details["trade_path"]
        assert float(details["balance"]) == 0.00
        assert isinstance(details["transactions"], list)
        assert len(details["transactions"]) == 0

    def test_unknown_vendor_returns_error(self, full_book):
        """vendor_get_details returns error dict for unknown vendor."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        result = vendor_get_details("Nobody Inc")
        assert "error" in result


class TestVendorRename:
    """T2.2.10–T2.2.12: vendor_rename."""

    def test_professional_vendor_renames_both_accounts(self, full_book):
        """T2.2.10: rename professional vendor updates both AP and expense account names."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("OldArch LLC", expense_category="Architecture")

        result = vendor_rename("OldArch LLC", "NewArch LLC")

        assert result["status"] == "ok"

        # New paths should exist
        ap = read.get_account_balance("Liabilities:AP — NewArch LLC")
        expense = read.get_account_balance("Expenses:Architecture — NewArch LLC")
        assert "error" not in ap
        assert "error" not in expense

        # Old paths should be gone
        ap_old = read.get_account_balance("Liabilities:AP — OldArch LLC")
        assert "error" in ap_old

    def test_trade_vendor_renames_only_ap(self, full_book):
        """T2.2.11: rename trade vendor updates only AP account; trade account unchanged."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("OldElec Inc", trade="Expenses:Construction:Electrical")

        result = vendor_rename("OldElec Inc", "NewElec Inc")

        assert result["status"] == "ok"

        ap_new = read.get_account_balance("Liabilities:AP — NewElec Inc")
        assert "error" not in ap_new

        # Shared trade account untouched
        elec = read.get_account_balance("Expenses:Construction:Electrical")
        assert "error" not in elec

    def test_renamed_vendor_transactions_still_valid(self, full_book):
        """T2.2.12: existing transactions remain valid after rename (GUID-tracked accounts)."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("OldArch LLC", expense_category="Architecture")
        fund_project("2025-01-01", "100000.00")
        inv = receive_invoice(
            TEST_DATE,
            "OldArch LLC",
            "OA-001",
            "5000.00",
            "Expenses:Architecture — OldArch LLC",
        )
        assert inv["status"] == "ok"

        vendor_rename("OldArch LLC", "NewArch LLC")

        # Balance is now on the renamed account
        expense = read.get_account_balance("Expenses:Architecture — NewArch LLC")
        assert "error" not in expense
        assert float(expense["balance"]) == 5000.00


class TestVendorUpdate:
    """T2.2.14–T2.2.18: vendor_update."""

    def test_professional_vendor_moves_expense_account(self, full_book):
        """T2.2.14: vendor_update on professional vendor moves expense account."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Apex Consulting", expense_category="Architecture")

        result = vendor_update("Apex Consulting", expense_category="Structural")

        assert result["status"] == "ok"

        # Expense account should now be under Structural Engineering
        new_expense = read.get_account_balance("Expenses:Structural Engineering — Apex Consulting")
        assert "error" not in new_expense

    def test_professional_vendor_historical_transactions_unaffected(self, full_book):
        """T2.2.15: transactions before update remain on old expense path."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Apex Consulting", expense_category="Architecture")
        fund_project("2025-01-01", "100000.00")
        receive_invoice(
            TEST_DATE,
            "Apex Consulting",
            "APC-001",
            "3000.00",
            "Expenses:Architecture — Apex Consulting",
        )

        vendor_update("Apex Consulting", expense_category="Structural")

        # Old account still has the historical transaction balance
        old_expense = read.get_account_balance("Expenses:Architecture — Apex Consulting")
        assert "error" not in old_expense
        assert float(old_expense["balance"]) == 3000.00

    def test_trade_vendor_reassigned_to_different_trade(self, full_book):
        """T2.2.16: vendor_update reassigns trade vendor to a different trade account."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Multi Trade Co", trade="Expenses:Construction:Electrical")

        result = vendor_update("Multi Trade Co", trade="Expenses:Construction:Plumbing")

        assert result["status"] == "ok"

        details = vendor_get_details("Multi Trade Co")
        assert "Plumbing" in details["trade_path"]

    def test_invalid_expense_category_raises(self, full_book):
        """T2.2.17: vendor_update with invalid expense_category raises ValueError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Apex Consulting", expense_category="Architecture")

        with pytest.raises(ValueError):
            vendor_update("Apex Consulting", expense_category="InvalidCategory")

    def test_nonexistent_trade_path_raises(self, full_book):
        """T2.2.18: vendor_update with non-existent trade path raises AccountNotFoundError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Multi Trade Co", trade="Expenses:Construction:Electrical")

        with pytest.raises(AccountNotFoundError):
            vendor_update("Multi Trade Co", trade="Expenses:Construction:Ghost")


class TestVendorDelete:
    """T2.2.19–T2.2.22: vendor_delete."""

    def test_requires_confirm_true(self, full_book):
        """T2.2.19: vendor_delete without confirm=True raises RequiresConfirmationError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Temp Sub", trade="Expenses:Construction:Electrical")

        with pytest.raises(RequiresConfirmationError):
            vendor_delete("Temp Sub")

    def test_trade_vendor_removes_only_ap(self, full_book):
        """T2.2.20: trade vendor delete removes only AP account; trade account intact."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Temp Elec", trade="Expenses:Construction:Electrical")

        result = vendor_delete("Temp Elec", confirm=True)

        assert result["status"] == "ok"

        # AP account gone
        ap = read.get_account_balance("Liabilities:AP — Temp Elec")
        assert "error" in ap

        # Shared trade account still present and intact
        elec = read.get_account_balance("Expenses:Construction:Electrical")
        assert "error" not in elec

    def test_professional_vendor_removes_both_accounts(self, full_book):
        """T2.2.21: professional vendor delete removes both AP and expense accounts."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Temp Arch LLC", expense_category="Architecture")

        result = vendor_delete("Temp Arch LLC", confirm=True)

        assert result["status"] == "ok"

        ap = read.get_account_balance("Liabilities:AP — Temp Arch LLC")
        expense = read.get_account_balance("Expenses:Architecture — Temp Arch LLC")
        assert "error" in ap
        assert "error" in expense

    def test_vendor_with_history_raises_even_with_confirm(self, full_book):
        """T2.2.22: vendor with AP transaction history raises VendorHasHistoryError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Temp Arch LLC", expense_category="Architecture")
        fund_project("2025-01-01", "100000.00")
        receive_invoice(
            TEST_DATE,
            "Temp Arch LLC",
            "TA-001",
            "2000.00",
            "Expenses:Architecture — Temp Arch LLC",
        )

        with pytest.raises(VendorHasHistoryError):
            vendor_delete("Temp Arch LLC", confirm=True)


class TestVendorGuideResource:
    """T2.2.23–T2.2.24: vendor resource handlers."""

    def test_vendor_guide_lists_trade_accounts_from_live_book(self, full_book):
        """T2.2.23: vendor_guide_resource lists current trade accounts from live book."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        content = vendor_guide_resource()

        assert isinstance(content, str)
        assert len(content) > 0
        assert "Electrical" in content  # from Construction:Electrical

    def test_vendors_resource_updated_after_add(self, full_book):
        """T2.2.24: gnucash://vendors resource reflects newly added vendor (live query)."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Fresh Vendor Inc", trade="Expenses:Construction:Framing")

        vendors = read.vendors_resource()
        names = [v["name"] for v in vendors]
        assert "Fresh Vendor Inc" in names


class TestVendorEndToEnd:
    """T2.2.25–T2.2.26: end-to-end workflows."""

    def test_trade_vendor_full_cycle(self, full_book):
        """T2.2.25: add trade vendor → invoice → pay → AP clears; trade shows spend."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Pacific Crest Electrical", trade="Expenses:Construction:Electrical")
        fund_project("2025-01-01", "100000.00")

        receive_invoice(
            TEST_DATE,
            "Pacific Crest Electrical",
            "PCE-001",
            "12000.00",
            "Expenses:Construction:Electrical",
        )
        pay_invoice(TEST_DATE_2, "Pacific Crest Electrical", "PCE-001", "12000.00")

        ap = read.get_account_balance("Liabilities:AP — Pacific Crest Electrical")
        assert float(ap["balance"]) == 0.00

        elec = read.get_account_balance("Expenses:Construction:Electrical")
        assert float(elec["balance"]) == 12000.00

    def test_two_trade_vendors_same_trade_combined_spend(self, full_book):
        """T2.2.26: two trade vendors on same trade; Construction:Electrical shows combined spend."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        vendor_add("Pacific Crest Electrical", trade="Expenses:Construction:Electrical")
        vendor_add("Volt Masters LLC", trade="Expenses:Construction:Electrical")
        fund_project("2025-01-01", "200000.00")

        receive_invoice(
            "2025-02-01",
            "Pacific Crest Electrical",
            "PCE-001",
            "10000.00",
            "Expenses:Construction:Electrical",
        )
        pay_invoice("2025-02-15", "Pacific Crest Electrical", "PCE-001", "10000.00")

        receive_invoice(
            "2025-03-01",
            "Volt Masters LLC",
            "VM-001",
            "7500.00",
            "Expenses:Construction:Electrical",
        )
        pay_invoice("2025-03-15", "Volt Masters LLC", "VM-001", "7500.00")

        elec = read.get_account_balance("Expenses:Construction:Electrical")
        assert float(elec["balance"]) == 17500.00

        pce_ap = read.get_account_balance("Liabilities:AP — Pacific Crest Electrical")
        vm_ap = read.get_account_balance("Liabilities:AP — Volt Masters LLC")
        assert float(pce_ap["balance"]) == 0.00
        assert float(vm_ap["balance"]) == 0.00
