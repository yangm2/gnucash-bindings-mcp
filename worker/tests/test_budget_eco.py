"""Tests for Phase 4 budget and ECO tools — T4.1.x, T4.2.x, T4.3.x"""

import pytest

from gnucash_mcp.tools.budget import (
    budget_create,
    budget_list,
    budget_get,
    budget_set_amount,
    budget_update,
    budget_delete,
    RequiresConfirmationError,
)
from gnucash_mcp.tools.eco import (
    eco_create,
    eco_list,
    eco_get,
    eco_approve,
    eco_void,
)
from gnucash_mcp.tools.read import get_project_summary
from gnucash_mcp.tools.write import receive_invoice, pay_invoice, fund_project


TEST_DATE = "2025-06-01"
TEST_DATE_2 = "2025-06-15"

ELECTRICAL_ACCOUNT = "Expenses:Construction:Electrical"
FRAMING_ACCOUNT = "Expenses:Construction:Framing"
DEMO_ACCOUNT = "Expenses:Construction:Demo"


# ── M4.1 Budget CRUD ─────────────────────────────────────────────────────────


class TestBudgetCreate:
    """T4.1.1–T4.1.2: budget_create and budget_list."""

    def test_budget_create_returns_ok(self, full_book):
        """T4.1.1: budget_create creates GncBudget with correct num_periods."""
        result = budget_create(
            "GC Pre-Construction",
            period_start="2025-09-01",
            num_periods=1,
        )
        assert result["status"] == "ok"
        assert "budget_guid" in result

    def test_budget_create_num_periods(self, full_book):
        """T4.1.1: budget_create with num_periods=3 stores correct period count."""
        budget_create("Multi-Period", period_start="2025-01-01", num_periods=3)

        budgets = budget_list()
        entry = next((b for b in budgets if b["name"] == "Multi-Period"), None)
        assert entry is not None
        assert entry["num_periods"] == 3

    def test_budget_list_returns_new_budget(self, full_book):
        """T4.1.2: budget_list returns newly created budget with expected fields."""
        budget_create("GC Pre-Construction", period_start="2025-09-01")

        budgets = budget_list()
        assert len(budgets) >= 1

        entry = next((b for b in budgets if b["name"] == "GC Pre-Construction"), None)
        assert entry is not None
        assert "name" in entry
        assert "num_periods" in entry
        assert "period_start" in entry


class TestBudgetSetAmount:
    """T4.1.3–T4.1.5: budget_set_amount."""

    def test_set_amount_on_existing_account(self, full_book):
        """T4.1.3: budget_set_amount sets amount on existing account."""
        budget_create("GC Budget", period_start="2025-09-01")

        result = budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")
        assert result["status"] == "ok"

    def test_set_amount_creates_missing_account(self, full_book):
        """T4.1.4: budget_set_amount creates account and sets amount when account doesn't exist."""
        budget_create("GC Budget", period_start="2025-09-01")
        new_path = "Expenses:Construction:Insulation"

        result = budget_set_amount("GC Budget", new_path, "8000.00")
        assert result["status"] == "ok"

        detail = budget_get("GC Budget")
        amounts = {a["account"]: a for a in detail["accounts"]}
        assert new_path in amounts
        assert amounts[new_path]["budgeted"] == "8000.00"

    def test_budget_get_shows_all_amounts(self, full_book):
        """T4.1.5: budget_get returns all accounts with correct budgeted amounts."""
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")
        budget_set_amount("GC Budget", FRAMING_ACCOUNT, "32000.00")
        budget_set_amount("GC Budget", DEMO_ACCOUNT, "8600.00")

        detail = budget_get("GC Budget")
        amounts = {a["account"]: a for a in detail["accounts"]}

        assert amounts[ELECTRICAL_ACCOUNT]["budgeted"] == "45000.00"
        assert amounts[FRAMING_ACCOUNT]["budgeted"] == "32000.00"
        assert amounts[DEMO_ACCOUNT]["budgeted"] == "8600.00"


class TestBudgetGetActuals:
    """T4.1.6–T4.1.8: budget_get committed/paid/variance."""

    def test_no_invoices_committed_and_paid_zero(self, full_book):
        """T4.1.6: budget_get shows committed=0, paid=0, variance=budget before any invoices."""
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)

        assert float(elec["committed"]) == 0.0
        assert float(elec["paid"]) == 0.0
        assert elec["variance"] == elec["budgeted"]

    def test_after_invoice_committed_reflects_invoice(self, full_book):
        """T4.1.7: After receive_invoice to a budgeted account, budget_get shows correct committed."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        receive_invoice(
            TEST_DATE,
            "Pacific Crest Electrical",
            "PCE-001",
            "22500.00",
            ELECTRICAL_ACCOUNT,
        )

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)

        assert float(elec["committed"]) == 22500.00
        assert float(elec["paid"]) == 0.0
        assert float(elec["variance"]) == 22500.00

    def test_after_payment_paid_reflects_payment(self, full_book):
        """T4.1.8: After pay_invoice, budget_get shows correct paid; committed unchanged."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        receive_invoice(
            TEST_DATE,
            "Pacific Crest Electrical",
            "PCE-001",
            "22500.00",
            ELECTRICAL_ACCOUNT,
        )
        pay_invoice(TEST_DATE_2, "Pacific Crest Electrical", "PCE-001", "22500.00")

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)

        assert float(elec["committed"]) == 22500.00
        assert float(elec["paid"]) == 22500.00


class TestBudgetUpdateDelete:
    """T4.1.9–T4.1.11: budget_update and budget_delete."""

    def test_budget_update_renames(self, full_book):
        """T4.1.9: budget_update renames budget; amounts unchanged."""
        budget_create("Old Name", period_start="2025-09-01")
        budget_set_amount("Old Name", ELECTRICAL_ACCOUNT, "45000.00")

        result = budget_update("Old Name", new_name="New Name")
        assert result["status"] == "ok"

        budgets = budget_list()
        assert any(b["name"] == "New Name" for b in budgets)
        assert not any(b["name"] == "Old Name" for b in budgets)

        detail = budget_get("New Name")
        amounts = {a["account"]: a for a in detail["accounts"]}
        assert amounts[ELECTRICAL_ACCOUNT]["budgeted"] == "45000.00"

    def test_budget_delete_without_confirm_raises(self, full_book):
        """T4.1.10: budget_delete without confirm=True raises RequiresConfirmationError."""
        budget_create("To Delete", period_start="2025-09-01")

        with pytest.raises(RequiresConfirmationError):
            budget_delete("To Delete")

    def test_budget_delete_removes_budget(self, full_book):
        """T4.1.11: budget_delete with confirm=True removes budget; transactions unaffected."""
        fund_project(TEST_DATE, "100000.00")
        budget_create("To Delete", period_start="2025-09-01")
        budget_set_amount("To Delete", ELECTRICAL_ACCOUNT, "45000.00")

        receive_invoice(
            TEST_DATE, "Pacific Crest Electrical", "PCE-001", "5000.00", ELECTRICAL_ACCOUNT
        )

        result = budget_delete("To Delete", confirm=True)
        assert result["status"] == "ok"

        budgets = budget_list()
        assert not any(b["name"] == "To Delete" for b in budgets)

        from gnucash_mcp.tools.read import get_account_balance

        bal = get_account_balance(ELECTRICAL_ACCOUNT)
        assert float(bal["balance"]) == 5000.00


class TestBudgetFullWorkflow:
    """T4.1.12–T4.1.13: end-to-end budget workflows."""

    def test_full_budget_workflow(self, full_book):
        """T4.1.12: create budget → set 5 line items → receive 2 invoices → correct committed/paid/variance."""
        fund_project(TEST_DATE, "500000.00")
        budget_create("GC Pre-Construction", period_start="2025-09-01")
        budget_set_amount("GC Pre-Construction", DEMO_ACCOUNT, "8600.00")
        budget_set_amount("GC Pre-Construction", FRAMING_ACCOUNT, "32000.00")
        budget_set_amount("GC Pre-Construction", ELECTRICAL_ACCOUNT, "45000.00")
        budget_set_amount("GC Pre-Construction", "Expenses:Construction:Plumbing", "28000.00")
        budget_set_amount("GC Pre-Construction", "Expenses:Construction:HVAC", "22000.00")

        receive_invoice(
            TEST_DATE, "Pacific Crest Electrical", "PCE-001", "15000.00", ELECTRICAL_ACCOUNT
        )
        pay_invoice(TEST_DATE_2, "Pacific Crest Electrical", "PCE-001", "15000.00")
        receive_invoice(
            TEST_DATE, "Summit HVAC", "SH-001", "10000.00", "Expenses:Construction:HVAC"
        )

        detail = budget_get("GC Pre-Construction")
        amounts = {a["account"]: a for a in detail["accounts"]}

        elec = amounts[ELECTRICAL_ACCOUNT]
        assert float(elec["committed"]) == 15000.00
        assert float(elec["paid"]) == 15000.00
        assert float(elec["variance"]) == 30000.00

        hvac = amounts["Expenses:Construction:HVAC"]
        assert float(hvac["committed"]) == 10000.00
        assert float(hvac["paid"]) == 0.0

        framing = amounts[FRAMING_ACCOUNT]
        assert float(framing["committed"]) == 0.0
        assert float(framing["variance"]) == float(framing["budgeted"])

    def test_vendor_replacement_same_trade_budget(self, full_book):
        """T4.1.13: Two vendors billing same trade account; budget_get shows combined committed."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        receive_invoice(
            TEST_DATE, "Pacific Crest Electrical", "PCE-001", "10000.00", ELECTRICAL_ACCOUNT
        )
        receive_invoice(TEST_DATE, "Sparks Electric", "SE-001", "8000.00", ELECTRICAL_ACCOUNT)

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)

        assert float(elec["committed"]) == 18000.00
        assert float(elec["variance"]) == 27000.00


# ── M4.2 ECO tools ───────────────────────────────────────────────────────────


class TestEcoCreate:
    """T4.2.1–T4.2.4: eco_create, eco_list, eco_get."""

    def test_eco_create_pending_no_transactions(self, full_book):
        """T4.2.1: eco_create stores ECO with status=pending; no transactions posted."""
        from gnucash_mcp.tools.read import get_account_balance

        result = eco_create(
            "CO-001",
            description="Add recessed lighting in kitchen",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        assert result["status"] == "ok"

        bal = get_account_balance("Expenses:Change Orders:Electrical")
        assert float(bal["balance"]) == 0.0

    def test_eco_list_shows_new_eco(self, full_book):
        """T4.2.2: eco_list returns newly created ECO with correct fields."""
        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )

        ecos = eco_list()
        co = next((e for e in ecos if e["number"] == "CO-001"), None)
        assert co is not None
        assert co["status"] == "pending"
        assert co["direction"] == "additive"
        assert co["amount"] == "5000.00"

    def test_eco_list_status_filter_excludes_others(self, full_book):
        """T4.2.3: eco_list(status='pending') excludes approved and voided ECOs."""
        eco_create(
            "CO-001",
            description="Pending CO",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_create(
            "CO-002",
            description="To approve",
            direction="additive",
            amount="3000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_create(
            "CO-003",
            description="To void",
            direction="additive",
            amount="1000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_approve("CO-002", date=TEST_DATE)
        eco_void("CO-003", reason="Not needed")

        pending = eco_list(status="pending")
        numbers = {e["number"] for e in pending}
        assert "CO-001" in numbers
        assert "CO-002" not in numbers
        assert "CO-003" not in numbers

    def test_eco_get_full_detail(self, full_book):
        """T4.2.4: eco_get returns full ECO detail including notes."""
        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
            notes="Owner-requested addition per email 2025-05-15",
        )

        detail = eco_get("CO-001")
        assert detail["number"] == "CO-001"
        assert detail["description"] == "Recessed lighting"
        assert detail["direction"] == "additive"
        assert detail["amount"] == "5000.00"
        assert detail["status"] == "pending"
        assert "Owner-requested" in detail["notes"]


class TestEcoApprove:
    """T4.2.5–T4.2.8: eco_approve."""

    def test_approve_additive_posts_dr_change_orders_cr_ap(self, full_book):
        """T4.2.5: eco_approve(additive) posts DR Change Orders / CR AP transaction."""
        from gnucash_mcp.tools.read import get_account_balance

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )

        result = eco_approve("CO-001", date=TEST_DATE)
        assert result["status"] == "ok"

        co_elec = get_account_balance("Expenses:Change Orders:Electrical")
        assert float(co_elec["balance"]) == 5000.00

    def test_approve_additive_increases_budget(self, full_book):
        """T4.2.6: eco_approve(additive) increases budget on affected account."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)
        assert float(elec["budgeted"]) == 50000.00

    def test_approve_deductive_posts_dr_ap_cr_change_orders(self, full_book):
        """T4.2.7: eco_approve(deductive) posts DR AP / CR Change Orders reversal."""
        from gnucash_mcp.tools.read import get_account_balance

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-002",
            description="Remove under-cabinet lighting",
            direction="deductive",
            amount="2000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-002", date=TEST_DATE)

        co_elec = get_account_balance("Expenses:Change Orders:Electrical")
        assert float(co_elec["balance"]) == -2000.00

    def test_approve_deductive_decreases_budget(self, full_book):
        """T4.2.8: eco_approve(deductive) decreases budget on affected account."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-002",
            description="Remove under-cabinet lighting",
            direction="deductive",
            amount="2000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-002", date=TEST_DATE)

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)
        assert float(elec["budgeted"]) == 43000.00


class TestEcoVoid:
    """T4.2.9–T4.2.11: eco_void."""

    def test_void_pending_no_transaction(self, full_book):
        """T4.2.9: eco_void(pending) changes status; no transaction posted."""
        from gnucash_mcp.tools.read import get_account_balance

        eco_create(
            "CO-001",
            description="Pending CO",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )

        result = eco_void("CO-001", reason="Owner decided against it")
        assert result["status"] == "ok"

        detail = eco_get("CO-001")
        assert detail["status"] == "void"

        bal = get_account_balance("Expenses:Change Orders:Electrical")
        assert float(bal["balance"]) == 0.0

    def test_void_approved_reverses_transaction_and_budget(self, full_book):
        """T4.2.10: eco_void(approved) reverses posted transaction; budget reverted."""
        from gnucash_mcp.tools.read import get_account_balance

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        eco_void("CO-001", reason="GC withdrew the CO")

        bal = get_account_balance("Expenses:Change Orders:Electrical")
        assert float(bal["balance"]) == 0.0

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)
        assert float(elec["budgeted"]) == 45000.00

    def test_void_records_reason(self, full_book):
        """T4.2.11: eco_void records reason; ECO visible in eco_list with void status."""
        eco_create(
            "CO-001",
            description="Pending CO",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_void("CO-001", reason="GC withdrew the CO")

        detail = eco_get("CO-001")
        assert detail["status"] == "void"
        assert "GC withdrew" in (detail.get("void_reason") or "")

        all_ecos = eco_list()
        voided = next((e for e in all_ecos if e["number"] == "CO-001"), None)
        assert voided is not None
        assert voided["status"] == "void"


class TestEcoStateTransitionErrors:
    """ECO state machine — invalid transitions must raise."""

    def test_approve_already_approved_raises(self, full_book):
        """eco_approve on an already-approved ECO raises ValueError."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        with pytest.raises(ValueError):
            eco_approve("CO-001", date=TEST_DATE_2)

    def test_approve_voided_eco_raises(self, full_book):
        """eco_approve on a voided ECO raises ValueError."""
        eco_create(
            "CO-001",
            description="Voided CO",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_void("CO-001", reason="Not needed")

        with pytest.raises(ValueError):
            eco_approve("CO-001", date=TEST_DATE)

    def test_void_already_voided_raises(self, full_book):
        """eco_void on an already-voided ECO raises ValueError."""
        eco_create(
            "CO-001",
            description="CO to double-void",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_void("CO-001", reason="First void")

        with pytest.raises(ValueError):
            eco_void("CO-001", reason="Second void attempt")

    def test_duplicate_eco_number_raises(self, full_book):
        """eco_create with a duplicate number raises ValueError."""
        eco_create(
            "CO-001",
            description="Original",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )

        with pytest.raises(ValueError):
            eco_create(
                "CO-001",
                description="Duplicate",
                direction="additive",
                amount="3000.00",
                budget_account=ELECTRICAL_ACCOUNT,
            )


class TestEcoVoidDeductive:
    """Voiding a deductive ECO must reverse the sign correctly."""

    def test_void_approved_deductive_restores_balance_and_budget(self, full_book):
        """eco_void(approved deductive) reverses CR Change Orders entry; budget restored."""
        from gnucash_mcp.tools.read import get_account_balance

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-002",
            description="Remove under-cabinet lighting",
            direction="deductive",
            amount="2000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-002", date=TEST_DATE)

        # After approve: balance should be -2000 (credit), budget 43000
        bal_after_approve = get_account_balance("Expenses:Change Orders:Electrical")
        assert float(bal_after_approve["balance"]) == -2000.00

        eco_void("CO-002", reason="GC reversed the credit")

        # After void: balance back to 0, budget back to 45000
        bal_after_void = get_account_balance("Expenses:Change Orders:Electrical")
        assert float(bal_after_void["balance"]) == 0.0

        detail = budget_get("GC Budget")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)
        assert float(elec["budgeted"]) == 45000.00


class TestEcoListTotals:
    """T4.2.12: eco_list totals."""

    def test_eco_list_shows_approved_and_pending_totals(self, full_book):
        """T4.2.12: eco_list shows correct total approved ECO value and pending ECO exposure."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Approved CO",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_create(
            "CO-002",
            description="Pending CO",
            direction="additive",
            amount="8000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        summary = eco_list()
        approved_total = sum(float(e["amount"]) for e in summary if e["status"] == "approved")
        pending_total = sum(float(e["amount"]) for e in summary if e["status"] == "pending")
        assert approved_total == 5000.00
        assert pending_total == 8000.00


class TestEcoFullWorkflow:
    """T4.2.13: end-to-end ECO workflow."""

    def test_additive_eco_budget_split(self, full_book):
        """T4.2.13: CO-001 additive $5K electrical → approve → budget_get shows original + ECO split."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Pre-Construction", period_start="2025-09-01")
        budget_set_amount("GC Pre-Construction", ELECTRICAL_ACCOUNT, "45000.00")

        receive_invoice(
            TEST_DATE, "Pacific Crest Electrical", "PCE-001", "22500.00", ELECTRICAL_ACCOUNT
        )

        eco_create(
            "CO-001",
            description="Recessed lighting in kitchen",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        detail = budget_get("GC Pre-Construction")
        elec = next(a for a in detail["accounts"] if a["account"] == ELECTRICAL_ACCOUNT)

        assert float(elec["budgeted"]) == 50000.00
        assert float(elec["committed"]) == 22500.00
        assert float(elec["variance"]) == 27500.00


# ── M4.3 get_budget_vs_actual and project_summary ────────────────────────────


class TestGetBudgetVsActual:
    """T4.3.1–T4.3.6: get_budget_vs_actual."""

    def test_no_budget_returns_error(self, full_book):
        """T4.3.1: get_budget_vs_actual with no budget in book returns clear error message."""
        from gnucash_mcp.tools.read import get_budget_vs_actual

        result = get_budget_vs_actual()
        assert "error" in result

    def test_returns_correct_variance(self, full_book):
        """T4.3.2: get_budget_vs_actual returns correct variance after entering GC budget."""
        from gnucash_mcp.tools.read import get_budget_vs_actual

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")
        budget_set_amount("GC Budget", FRAMING_ACCOUNT, "32000.00")

        receive_invoice(
            TEST_DATE, "Pacific Crest Electrical", "PCE-001", "15000.00", ELECTRICAL_ACCOUNT
        )

        result = get_budget_vs_actual()
        assert "error" not in result
        assert "summary" in result
        assert float(result["summary"]["committed"]) == 15000.00
        assert float(result["summary"]["remaining"]) > 0

    def test_include_ecos_true_shows_eco_adjustments(self, full_book):
        """T4.3.3: get_budget_vs_actual(include_ecos=True) shows ECO adjustments separately."""
        from gnucash_mcp.tools.read import get_budget_vs_actual

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        result = get_budget_vs_actual(include_ecos=True)
        summary = result["summary"]
        assert float(summary["original_contract"]) == 45000.00
        assert float(summary["approved_ecos"]) == 5000.00
        assert float(summary["revised_budget"]) == 50000.00

    def test_include_ecos_false_shows_original_only(self, full_book):
        """T4.3.4: get_budget_vs_actual(include_ecos=False) shows only original contract budget."""
        from gnucash_mcp.tools.read import get_budget_vs_actual

        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Recessed lighting",
            direction="additive",
            amount="5000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )
        eco_approve("CO-001", date=TEST_DATE)

        result = get_budget_vs_actual(include_ecos=False)
        summary = result["summary"]
        assert float(summary["original_contract"]) == 45000.00
        assert "approved_ecos" not in summary or float(summary["approved_ecos"]) == 0.0

    def test_project_summary_includes_budget_status(self, full_book):
        """T4.3.5: get_project_summary includes budget_status with correct pending_eco_exposure."""
        fund_project(TEST_DATE, "200000.00")
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        eco_create(
            "CO-001",
            description="Pending CO",
            direction="additive",
            amount="8000.00",
            budget_account=ELECTRICAL_ACCOUNT,
        )

        summary = get_project_summary()
        assert "budget_status" in summary
        bs = summary["budget_status"]
        assert float(bs["pending_eco_exposure"]) == 8000.00

    def test_professional_fees_appear_only_if_budget_set(self, full_book):
        """T4.3.6: Professional fee accounts appear in budget_vs_actual only if budget amount set."""
        from gnucash_mcp.tools.read import get_budget_vs_actual

        arch_account = "Expenses:Architecture — Acme Architecture"
        budget_create("GC Budget", period_start="2025-09-01")
        budget_set_amount("GC Budget", ELECTRICAL_ACCOUNT, "45000.00")

        result_before = get_budget_vs_actual()
        accounts_before = {a["account"] for a in result_before.get("by_account", [])}
        assert arch_account not in accounts_before

        budget_set_amount("GC Budget", arch_account, "60000.00")

        result_after = get_budget_vs_actual()
        accounts_after = {a["account"] for a in result_after.get("by_account", [])}
        assert arch_account in accounts_after
