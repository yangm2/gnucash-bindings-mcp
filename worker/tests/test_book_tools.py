"""Tests for book management tools — T2.1.x"""

import os
import pytest

from gnucash_mcp.tools.book import (
    book_add_account,
    book_get_account_tree,
    book_verify_structure,
    book_set_opening_balance,
    book_rename_account,
    book_move_account,
    book_delete_account,
    book_setup_guide_resource,
    expected_chart_resource,
)
from gnucash_mcp.session import AccountNotFoundError
from gnucash_mcp.tools import read

TEST_DATE = "2025-03-01"


class TestBookAddAccount:
    """T2.1.1–T2.1.4: book_add_account."""

    def test_creates_account_at_correct_path(self, full_book):
        """T2.1.1: account appears in hierarchy under specified parent."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        result = book_add_account(
            name="Landscaping",
            parent_path="Expenses:Construction",
            account_type="EXPENSE",
        )

        assert result["status"] == "ok"
        assert result["path"] == "Expenses:Construction:Landscaping"

        # Confirm account exists in tree
        tree = book_get_account_tree("Expenses:Construction")
        names = [a["name"] for a in tree]
        assert "Landscaping" in names

    def test_nonexistent_parent_raises(self, full_book):
        """T2.1.2: non-existent parent_path raises AccountNotFoundError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        with pytest.raises(AccountNotFoundError):
            book_add_account(
                name="Orphan",
                parent_path="Expenses:DoesNotExist",
                account_type="EXPENSE",
            )

    def test_invalid_account_type_raises(self, full_book):
        """T2.1.3: invalid account_type raises ValueError."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        with pytest.raises(ValueError):
            book_add_account(
                name="Bad",
                parent_path="Expenses",
                account_type="BOGUSTYPE",
            )

    def test_idempotent_no_duplicate(self, full_book):
        """T2.1.4: calling twice with same args does not create a duplicate account."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        book_add_account(
            name="Landscaping",
            parent_path="Expenses:Construction",
            account_type="EXPENSE",
        )
        book_add_account(
            name="Landscaping",
            parent_path="Expenses:Construction",
            account_type="EXPENSE",
        )

        tree = book_get_account_tree("Expenses:Construction")
        names = [a["name"] for a in tree]
        assert names.count("Landscaping") == 1


class TestBookGetAccountTree:
    """T2.1.5: book_get_account_tree."""

    def test_returns_all_ap_accounts(self, full_book):
        """T2.1.5: tree for Liabilities includes all AP accounts."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        tree = book_get_account_tree("Liabilities")

        assert isinstance(tree, list)
        assert len(tree) > 0
        names = [a["name"] for a in tree]
        assert any("AP" in n for n in names)

    def test_root_returns_top_level(self, full_book):
        """book_get_account_tree('') returns top-level account names."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        tree = book_get_account_tree("")

        names = {a["name"] for a in tree}
        assert {"Assets", "Liabilities", "Equity", "Income", "Expenses"}.issubset(names)

    def test_missing_parent_returns_error(self, full_book):
        """book_get_account_tree with bad path returns error dict in list."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        result = book_get_account_tree("Expenses:NoSuchAccount")
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]


class TestBookVerifyStructure:
    """T2.1.6–T2.1.7: book_verify_structure."""

    def test_ok_on_full_chart(self, full_book):
        """T2.1.6: returns ok:true when book matches expected MC-6 structure."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        result = book_verify_structure()

        assert result["ok"] is True
        assert result["missing"] == []

    def test_reports_missing_account(self, full_book):
        """T2.1.7: returns missing account when one has been removed."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        # Use book_delete_account (exercises the M2.1 tool and uses acc.Destroy()
        # which marks the QOF instance dirty and persists correctly)
        book_delete_account("Expenses:Construction:Demo")

        result = book_verify_structure()

        assert result["ok"] is False
        assert any("Demo" in m for m in result["missing"])


class TestBookSetOpeningBalance:
    """T2.1.8: book_set_opening_balance."""

    def test_creates_balanced_transaction(self, full_book):
        """T2.1.8: creates balanced transaction with equity offset."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        result = book_set_opening_balance(
            account_path="Assets:Project Checking",
            amount="50000.00",
            date=TEST_DATE,
        )

        assert result["status"] == "ok"
        assert "transaction_guid" in result

        # Verify the account has the balance
        bal = read.get_account_balance("Assets:Project Checking")
        assert float(bal["balance"]) == 50000.00


class TestBookRenameAccount:
    """T2.1.9: book_rename_account."""

    def test_updates_name(self, full_book):
        """T2.1.9: rename updates account name; existing transactions still resolve."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        # Add an account to rename
        book_add_account("OldName", "Expenses:Construction", "EXPENSE")

        result = book_rename_account(
            account_path="Expenses:Construction:OldName",
            new_name="NewName",
        )

        assert result["status"] == "ok"

        # Old path gone, new path present
        tree = book_get_account_tree("Expenses:Construction")
        names = [a["name"] for a in tree]
        assert "NewName" in names
        assert "OldName" not in names

    def test_nonexistent_account_raises(self, full_book):
        """book_rename_account raises AccountNotFoundError for unknown path."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        with pytest.raises(AccountNotFoundError):
            book_rename_account(
                account_path="Expenses:Construction:NoSuch",
                new_name="Whatever",
            )


class TestBookMoveAccount:
    """T2.1.10: book_move_account."""

    def test_moves_to_new_parent(self, full_book):
        """T2.1.10: moved account appears under new parent; old parent no longer has it."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        book_add_account("Staging", "Expenses:Construction", "EXPENSE")

        result = book_move_account(
            account_path="Expenses:Construction:Staging",
            new_parent_path="Expenses:Change Orders",
        )

        assert result["status"] == "ok"
        assert result["new_path"] == "Expenses:Change Orders:Staging"

        under_construction = [a["name"] for a in book_get_account_tree("Expenses:Construction")]
        under_co = [a["name"] for a in book_get_account_tree("Expenses:Change Orders")]

        assert "Staging" not in under_construction
        assert "Staging" in under_co


class TestBookDeleteAccount:
    """T2.1.11–T2.1.12: book_delete_account."""

    def test_fails_on_account_with_transactions(self, full_book):
        """T2.1.11: fails when account has transactions and require_zero_balance=True."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        # Post a transaction directly to Construction:Electrical
        from gnucash_mcp.tools.write import post_transaction

        post_transaction(
            "2025-01-15",
            "Test expense",
            [
                {"account_path": "Expenses:Construction:Electrical", "amount": "5000.00"},
                {"account_path": "Equity:Owner Capital", "amount": "-5000.00"},
            ],
        )

        with pytest.raises(Exception, match="balance|transaction|history"):
            book_delete_account(
                account_path="Expenses:Construction:Electrical",
                require_zero_balance=True,
            )

    def test_succeeds_on_empty_account(self, full_book):
        """T2.1.12: empty account deleted; absent from tree afterward."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        book_add_account("Temporary", "Expenses:Construction", "EXPENSE")

        result = book_delete_account(
            account_path="Expenses:Construction:Temporary",
            require_zero_balance=True,
        )

        assert result["status"] == "ok"

        tree = book_get_account_tree("Expenses:Construction")
        names = [a["name"] for a in tree]
        assert "Temporary" not in names


class TestBookResources:
    """T2.1.13: resource handlers."""

    def test_book_setup_guide_non_empty(self, full_book):
        """T2.1.13: gnucash://book-setup-guide is non-empty and mentions account_type."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        content = book_setup_guide_resource()

        assert isinstance(content, str)
        assert len(content) > 0
        assert "account_type" in content

    def test_expected_chart_non_empty(self, full_book):
        """T2.3.2: gnucash://expected-chart contains MC-6 account structure."""
        os.environ["GNUCASH_BOOK_PATH"] = str(full_book)

        content = expected_chart_resource()

        assert isinstance(content, (str, dict))
        # Must include key structural accounts
        text = content if isinstance(content, str) else str(content)
        assert "Construction" in text
        assert "Liabilities" in text
