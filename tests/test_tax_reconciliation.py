from __future__ import annotations

from decimal import Decimal

import pytest

from finkit.analysis.tax_reconciliation import reconcile_tax_document, tax_readiness_report
from finkit.config import Settings
from finkit.db import Database
from finkit.operations import init_ledger, open_account, submit_transaction


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def ledger_db(settings):
    db = init_ledger(settings)
    yield db
    db.close()


@pytest.fixture
def populated_ledger(ledger_db):
    """Create accounts and transactions for testing reconciliation."""
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Income:Salary:Acme", type="Income")
    open_account(ledger_db, name="Expenses:Taxes:Federal", type="Expenses")
    open_account(ledger_db, name="Expenses:Taxes:State", type="Expenses")
    open_account(ledger_db, name="Expenses:Taxes:SocialSecurity", type="Expenses")
    open_account(ledger_db, name="Expenses:Taxes:Medicare", type="Expenses")
    open_account(ledger_db, name="Income:Interest:Chase", type="Income")
    ledger_db.conn.commit()

    for month in [1, 2]:
        submit_transaction(
            ledger_db,
            date=f"2024-{month:02d}-15",
            payee="Acme Corp",
            narration="Payroll",
            postings=[
                {"account": "Income:Salary:Acme", "amount": "-5000.00", "currency": "USD"},
                {"account": "Expenses:Taxes:Federal", "amount": "750.00", "currency": "USD"},
                {"account": "Expenses:Taxes:State", "amount": "250.00", "currency": "USD"},
                {"account": "Expenses:Taxes:SocialSecurity", "amount": "310.00", "currency": "USD"},
                {"account": "Expenses:Taxes:Medicare", "amount": "72.50", "currency": "USD"},
                {"account": "Assets:Chase:Checking", "amount": "3617.50", "currency": "USD"},
            ],
        )

    submit_transaction(
        ledger_db,
        date="2024-06-30",
        payee="Chase Bank",
        narration="Interest",
        postings=[
            {"account": "Income:Interest:Chase", "amount": "-50.00", "currency": "USD"},
            {"account": "Assets:Chase:Checking", "amount": "50.00", "currency": "USD"},
        ],
    )

    return ledger_db


class TestReconcileW2Match:
    def test_reconcile_w2_match(self, populated_ledger):
        result = reconcile_tax_document(populated_ledger, "w2", 2024, {
            "wages": "10000.00",
            "federal_tax": "1500.00",
            "state_tax": "500.00",
        })

        assert result["form_type"] == "w2"
        assert result["year"] == 2024

        status_map = {c["field"]: c["status"] for c in result["comparisons"]}
        assert status_map["wages"] == "match"
        assert status_map["federal_tax"] == "match"
        assert status_map["state_tax"] == "match"


class TestReconcileW2Mismatch:
    def test_reconcile_w2_mismatch(self, populated_ledger):
        result = reconcile_tax_document(populated_ledger, "w2", 2024, {
            "wages": "15000.00",
        })

        comparisons = result["comparisons"]
        wages_comp = [c for c in comparisons if c["field"] == "wages"][0]
        assert wages_comp["status"] == "mismatch"
        assert Decimal(wages_comp["form_value"]) == Decimal("15000.00")
        assert Decimal(wages_comp["ledger_value"]) == Decimal("10000")
        assert Decimal(wages_comp["difference"]) == Decimal("5000")


class TestReconcile1099IntMissing:
    def test_reconcile_1099_int_missing(self, populated_ledger):
        # Interest from a bank not in the ledger -- total ledger interest
        # is 50.00, but the form says 245.67 from a different bank.
        # Because the ledger DOES have 50.00 interest total, this will be
        # a mismatch, not missing. Let's test the true missing case by
        # using a year with no interest.
        result = reconcile_tax_document(populated_ledger, "1099_int", 2023, {
            "interest": "245.67",
            "payer": "Other Bank",
        })

        comparisons = result["comparisons"]
        interest_comp = [c for c in comparisons if c["field"] == "interest"][0]
        assert interest_comp["status"] == "missing"

        assert len(result["missing_income"]) == 1
        missing = result["missing_income"][0]
        assert missing["type"] == "interest"
        assert missing["payer"] == "Other Bank"
        assert Decimal(missing["amount"]) == Decimal("245.67")

        suggested = missing["suggested_transaction"]
        assert suggested["date"] == "2023-12-31"
        assert suggested["payee"] == "Other Bank"
        assert len(suggested["postings"]) == 2
        assert "tax-reconciliation" in suggested["tags"]


class TestReconcile1099IntMatch:
    def test_reconcile_1099_int_match(self, populated_ledger):
        result = reconcile_tax_document(populated_ledger, "1099_int", 2024, {
            "interest": "50.00",
            "payer": "Chase Bank",
        })

        comparisons = result["comparisons"]
        interest_comp = [c for c in comparisons if c["field"] == "interest"][0]
        assert interest_comp["status"] == "match"
        assert len(result["missing_income"]) == 0


class TestReconcileUnknownForm:
    def test_reconcile_unknown_form(self, populated_ledger):
        with pytest.raises(ValueError, match="Unknown form type"):
            reconcile_tax_document(populated_ledger, "unknown_form", 2024, {})


class TestTaxReadinessReport:
    def test_tax_readiness_report(self, populated_ledger):
        report = tax_readiness_report(populated_ledger, 2024)

        assert report["year"] == 2024
        assert report["jurisdiction"] == "US"

        assert "salary" in report["income"]
        assert Decimal(report["income"]["salary"]["total"]) == Decimal("10000")
        assert report["income"]["salary"]["transaction_count"] == 2
        assert "Income:Salary:Acme" in report["income"]["salary"]["accounts"]

        assert "interest" in report["income"]
        assert Decimal(report["income"]["interest"]["total"]) == Decimal("50")

        assert Decimal(report["taxes_paid"]["federal"]) == Decimal("1500")
        assert Decimal(report["taxes_paid"]["state"]) == Decimal("500")
        assert Decimal(report["taxes_paid"]["social_security"]) == Decimal("620")
        assert Decimal(report["taxes_paid"]["medicare"]) == Decimal("145")

        assert "capital_gains" in report
        assert "short_term" in report["capital_gains"]
        assert "long_term" in report["capital_gains"]
        assert "total" in report["capital_gains"]


class TestTaxReadinessEmpty:
    def test_tax_readiness_empty(self, ledger_db):
        report = tax_readiness_report(ledger_db, 2024)

        assert report["year"] == 2024
        assert report["income"] == {}
        assert Decimal(report["taxes_paid"]["federal"]) == Decimal("0")
        assert Decimal(report["capital_gains"]["total"]) == Decimal("0")
        assert report["deductible_expenses"] == []
        assert report["gaps"] == []


class TestReconcileSummary:
    def test_reconcile_summary(self, populated_ledger):
        result = reconcile_tax_document(populated_ledger, "w2", 2024, {
            "wages": "10000.00",
            "federal_tax": "1500.00",
            "state_tax": "999.99",
        })

        summary = result["summary"]
        assert summary["total_fields"] == 3
        assert summary["matched"] == 2
        assert summary["mismatched"] == 1
        assert summary["missing"] == 0
