from __future__ import annotations

from decimal import Decimal

import pytest

from finkit.analysis.payslip import (
    build_payslip_transaction,
    get_payroll_account_map,
    setup_payroll_accounts,
)
from finkit.config import Settings
from finkit.db import Database
from finkit.operations import init_ledger, open_account


# ---------------------------------------------------------------------------
# setup_payroll_accounts
# ---------------------------------------------------------------------------


class TestSetupPayrollUS:
    def test_setup_payroll_us(self, ledger_db):
        result = setup_payroll_accounts(ledger_db, "Acme", jurisdiction="US")

        assert result["gross"] == "Income:Salary:Acme"
        assert result["federal_tax"] == "Expenses:Taxes:Federal"
        assert result["state_tax"] == "Expenses:Taxes:State"
        assert result["social_security"] == "Expenses:Taxes:SocialSecurity"
        assert result["medicare"] == "Expenses:Taxes:Medicare"
        assert result["health_insurance"] == "Expenses:Benefits:Health"
        assert result["dental"] == "Expenses:Benefits:Dental"
        assert result["vision"] == "Expenses:Benefits:Vision"
        assert result["life_insurance"] == "Expenses:Benefits:Life"
        assert result["retirement_401k"] == "Assets:Retirement:401k"
        assert result["hsa"] == "Assets:Retirement:HSA"
        assert result["fsa"] == "Assets:Retirement:FSA"

        for name in result.values():
            row = ledger_db.fetchone("SELECT id FROM accounts WHERE name = ?", (name,))
            assert row is not None, f"Account {name} not found in database"


class TestSetupPayrollIndia:
    def test_setup_payroll_india(self, ledger_db):
        result = setup_payroll_accounts(ledger_db, "Infosys", jurisdiction="IN")

        assert result["gross"] == "Income:Salary:Infosys"
        assert result["income_tax"] == "Expenses:Taxes:IncomeTax"
        assert result["professional_tax"] == "Expenses:Taxes:ProfessionalTax"
        assert result["pf"] == "Expenses:Benefits:PF"
        assert result["health_insurance"] == "Expenses:Benefits:Health"
        assert result["epf"] == "Assets:Retirement:EPF"
        assert result["nps"] == "Assets:Retirement:NPS"

        for name in result.values():
            row = ledger_db.fetchone("SELECT id FROM accounts WHERE name = ?", (name,))
            assert row is not None, f"Account {name} not found in database"


class TestSetupPayrollIdempotent:
    def test_setup_payroll_idempotent(self, ledger_db):
        first = setup_payroll_accounts(ledger_db, "Acme", jurisdiction="US")
        second = setup_payroll_accounts(ledger_db, "Acme", jurisdiction="US")

        assert first == second

        rows = ledger_db.fetchall(
            "SELECT name FROM accounts WHERE name LIKE '%Salary%' OR name LIKE '%Tax%' "
            "OR name LIKE '%Benefits%' OR name LIKE '%Retirement%'"
        )
        names = [r["name"] for r in rows]
        assert len(names) == len(set(names)), "Duplicate accounts found"


# ---------------------------------------------------------------------------
# build_payslip_transaction
# ---------------------------------------------------------------------------


class TestBuildPayslipTransaction:
    def test_build_payslip_transaction(self):
        line_items = [
            {"label": "Gross Pay", "account": "Income:Salary:Acme", "amount": "5000.00"},
            {"label": "Federal Tax", "account": "Expenses:Taxes:Federal", "amount": "750.00"},
            {"label": "State Tax", "account": "Expenses:Taxes:State", "amount": "250.00"},
            {"label": "Social Security", "account": "Expenses:Taxes:SocialSecurity", "amount": "310.00"},
            {"label": "Medicare", "account": "Expenses:Taxes:Medicare", "amount": "72.50"},
            {"label": "Health Insurance", "account": "Expenses:Benefits:Health", "amount": "200.00"},
            {"label": "401k", "account": "Assets:Retirement:401k", "amount": "500.00"},
        ]

        result = build_payslip_transaction(
            date="2024-01-15",
            pay_period="2024-01-01 to 2024-01-15",
            employer="Acme",
            line_items=line_items,
            net_pay_account="Assets:Chase:Checking",
            currency="USD",
        )

        assert result["date"] == "2024-01-15"
        assert result["payee"] == "Acme"
        assert result["narration"] == "Payroll 2024-01-01 to 2024-01-15"
        assert result["tags"] == ["payroll"]

        postings = result["postings"]

        # Gross pay should be negative
        gross_posting = [p for p in postings if p["account"] == "Income:Salary:Acme"][0]
        assert Decimal(gross_posting["amount"]) == Decimal("-5000.00")

        # Net pay: 5000 - 750 - 250 - 310 - 72.50 - 200 - 500 = 2917.50
        net_posting = [p for p in postings if p["account"] == "Assets:Chase:Checking"][0]
        assert Decimal(net_posting["amount"]) == Decimal("2917.50")

        # All postings must sum to zero
        total = sum(Decimal(p["amount"]) for p in postings)
        assert abs(total) <= Decimal("0.01")


class TestBuildPayslipImbalanced:
    def test_build_payslip_imbalanced(self):
        line_items = [
            {"label": "Gross Pay", "account": "Income:Salary:Acme", "amount": "5000.00"},
            {"label": "Federal Tax", "account": "Expenses:Taxes:Federal", "amount": "750.00"},
        ]

        # Manually patch to force imbalance: override the function's net_pay calc
        # by providing items that would cause an internal math error is not possible,
        # so instead we test the validation path by making gross NOT labeled with "gross"
        # Actually, let's test with a scenario where we break the balance check.
        # The function always computes net_pay = gross - deductions, so it always balances.
        # We need to test that the validation catches an impossible state.
        # Since the function auto-computes net pay, the only way to fail is if
        # there's no gross item at all.
        bad_items = [
            {"label": "Federal Tax", "account": "Expenses:Taxes:Federal", "amount": "750.00"},
            {"label": "State Tax", "account": "Expenses:Taxes:State", "amount": "250.00"},
        ]

        with pytest.raises(ValueError, match="gross"):
            build_payslip_transaction(
                date="2024-01-15",
                pay_period="2024-01-01 to 2024-01-15",
                employer="Acme",
                line_items=bad_items,
                net_pay_account="Assets:Chase:Checking",
            )


# ---------------------------------------------------------------------------
# get_payroll_account_map
# ---------------------------------------------------------------------------


class TestGetPayrollAccountMap:
    def test_get_payroll_account_map(self, ledger_db):
        setup_payroll_accounts(ledger_db, "Acme", jurisdiction="US")
        result = get_payroll_account_map(ledger_db, "Acme")

        assert result["gross"] == "Income:Salary:Acme"
        assert result["federal_tax"] == "Expenses:Taxes:Federal"
        assert result["state_tax"] == "Expenses:Taxes:State"
        assert result["social_security"] == "Expenses:Taxes:SocialSecurity"
        assert result["medicare"] == "Expenses:Taxes:Medicare"
        assert result["health_insurance"] == "Expenses:Benefits:Health"
        assert result["dental"] == "Expenses:Benefits:Dental"
        assert result["vision"] == "Expenses:Benefits:Vision"
        assert result["life_insurance"] == "Expenses:Benefits:Life"
        assert result["retirement_401k"] == "Assets:Retirement:401k"
        assert result["hsa"] == "Assets:Retirement:HSA"
        assert result["fsa"] == "Assets:Retirement:FSA"


class TestGetPayrollAccountMapEmpty:
    def test_get_payroll_account_map_empty(self, ledger_db):
        result = get_payroll_account_map(ledger_db, "NonExistent")
        assert result == {}
