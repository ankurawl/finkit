from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from finkit.analysis.capital_gains import report_capital_gains
from finkit.analysis.export import export_csv, export_json
from finkit.analysis.portfolio import analyze_portfolio
from finkit.analysis.spending import analyze_spending, compare_budget
from finkit.analysis.whatif import what_if_sell
from finkit.config import Settings
from finkit.db import Database
from finkit.engine.prices import store_price
from finkit.operations import init_ledger, open_account, submit_transaction


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _setup_expense_accounts(db: Database) -> None:
    open_account(db, "Assets:Chase:Checking", "Assets", currency="USD")
    open_account(db, "Expenses:Groceries", "Expenses", currency="USD")
    open_account(db, "Expenses:Utilities", "Expenses", currency="USD")
    open_account(db, "Expenses:Entertainment", "Expenses", currency="USD")
    open_account(db, "Income:Salary", "Income", currency="USD")
    db.conn.commit()


def _setup_brokerage_accounts(db: Database) -> None:
    open_account(
        db, "Assets:Schwab:Stocks", "Assets",
        currency="USD", booking_method="FIFO",
        institution="schwab", asset_class="equity", jurisdiction="US",
    )
    open_account(db, "Assets:Schwab:Cash", "Assets", currency="USD")
    open_account(db, "Income:Dividends", "Income", currency="USD")
    open_account(db, "Income:CapitalGains", "Income", currency="USD")
    db.conn.commit()


# ---------------------------------------------------------------------------
# spending analysis
# ---------------------------------------------------------------------------


class TestSpendingBreakdown:
    def test_spending_breakdown(self, ledger_db, settings):
        _setup_expense_accounts(ledger_db)

        submit_transaction(
            ledger_db, "2024-01-15",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-100.00", "currency": "USD"},
                {"account": "Expenses:Groceries", "amount": "100.00", "currency": "USD"},
            ],
            payee="Whole Foods",
            settings=settings,
        )
        submit_transaction(
            ledger_db, "2024-01-20",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
                {"account": "Expenses:Utilities", "amount": "50.00", "currency": "USD"},
            ],
            payee="Electric Co",
            settings=settings,
        )
        submit_transaction(
            ledger_db, "2024-01-25",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-30.00", "currency": "USD"},
                {"account": "Expenses:Entertainment", "amount": "30.00", "currency": "USD"},
            ],
            payee="Netflix",
            settings=settings,
        )

        result = analyze_spending(ledger_db, year_month="2024-01", months=1, currency="USD")

        assert Decimal(result["total_expenses"]) == Decimal("180")
        assert len(result["by_category"]) == 3

        category_map = {c["account"]: Decimal(c["total"]) for c in result["by_category"]}
        assert category_map["Expenses:Groceries"] == Decimal("100")
        assert category_map["Expenses:Utilities"] == Decimal("50")
        assert category_map["Expenses:Entertainment"] == Decimal("30")


# ---------------------------------------------------------------------------
# portfolio analysis
# ---------------------------------------------------------------------------


class TestPortfolioAnalysis:
    def test_portfolio_analysis(self, ledger_db, settings):
        _setup_brokerage_accounts(ledger_db)

        submit_transaction(
            ledger_db, "2024-01-10",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "10",
                    "currency": "AAPL",
                    "price": "185.50",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "-1855.00", "currency": "USD"},
            ],
            payee="Buy AAPL",
            settings=settings,
        )

        store_price(ledger_db, "AAPL", "USD", Decimal("195.00"), "2024-02-01")
        ledger_db.conn.commit()

        result = analyze_portfolio(ledger_db)

        assert len(result["holdings"]) >= 1
        aapl_holding = [h for h in result["holdings"] if h["commodity"] == "AAPL"]
        assert len(aapl_holding) == 1
        assert Decimal(aapl_holding[0]["quantity"]) == Decimal("10")
        assert Decimal(aapl_holding[0]["cost_basis"]) == Decimal("1855")


# ---------------------------------------------------------------------------
# capital gains
# ---------------------------------------------------------------------------


class TestCapitalGainsReport:
    def test_capital_gains_report(self, ledger_db, settings):
        _setup_brokerage_accounts(ledger_db)

        submit_transaction(
            ledger_db, "2024-01-10",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "10",
                    "currency": "AAPL",
                    "price": "185.50",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "-1855.00", "currency": "USD"},
            ],
            payee="Buy AAPL",
            settings=settings,
        )

        submit_transaction(
            ledger_db, "2024-03-15",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "-5",
                    "currency": "AAPL",
                    "price": "195.00",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "975.00", "currency": "USD"},
            ],
            payee="Sell AAPL",
            settings=settings,
        )

        result = report_capital_gains(ledger_db, year=2024)

        assert len(result["detail"]) >= 1
        disposition = result["detail"][0]
        assert disposition["commodity"] == "AAPL"
        assert Decimal(disposition["quantity"]) == Decimal("5")
        gain = Decimal(disposition["gain_loss"])
        expected_gain = Decimal("5") * (Decimal("195.00") - Decimal("185.50"))
        assert gain == expected_gain
        assert disposition["term"] == "short"


# ---------------------------------------------------------------------------
# what-if sell
# ---------------------------------------------------------------------------


class TestWhatIfSell:
    def test_whatif_sell(self, ledger_db, settings):
        _setup_brokerage_accounts(ledger_db)

        submit_transaction(
            ledger_db, "2024-01-10",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "10",
                    "currency": "AAPL",
                    "price": "185.50",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "-1855.00", "currency": "USD"},
            ],
            payee="Buy AAPL",
            settings=settings,
        )

        result = what_if_sell(
            ledger_db,
            account_name="Assets:Schwab:Stocks",
            commodity="AAPL",
            quantity="5",
            booking_method="FIFO",
            sell_price="200.00",
            sell_date="2024-06-15",
            settings=settings,
        )

        assert len(result["lots_to_sell"]) == 1
        assert Decimal(result["lots_to_sell"][0]["quantity_from_lot"]) == Decimal("5")
        expected_gain = Decimal("5") * (Decimal("200.00") - Decimal("185.50"))
        assert Decimal(result["total_gain_loss"]) == expected_gain
        assert Decimal(result["total_proceeds"]) == Decimal("1000.00")

    def test_whatif_does_not_modify(self, ledger_db, settings):
        _setup_brokerage_accounts(ledger_db)

        submit_transaction(
            ledger_db, "2024-01-10",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "10",
                    "currency": "AAPL",
                    "price": "185.50",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "-1855.00", "currency": "USD"},
            ],
            payee="Buy AAPL",
            settings=settings,
        )

        lots_before = ledger_db.fetchall(
            "SELECT quantity FROM lots WHERE commodity = 'AAPL' AND disposed = 0"
        )
        qty_before = sum(Decimal(str(r["quantity"])) for r in lots_before)

        what_if_sell(
            ledger_db,
            account_name="Assets:Schwab:Stocks",
            commodity="AAPL",
            quantity="5",
            booking_method="FIFO",
            sell_price="200.00",
            sell_date="2024-06-15",
            settings=settings,
        )

        lots_after = ledger_db.fetchall(
            "SELECT quantity FROM lots WHERE commodity = 'AAPL' AND disposed = 0"
        )
        qty_after = sum(Decimal(str(r["quantity"])) for r in lots_after)

        assert qty_after == qty_before


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


class TestExportCsv:
    def test_export_csv(self):
        data = [
            {"account": "Expenses:Groceries", "total": Decimal("100.50")},
            {"account": "Expenses:Utilities", "total": Decimal("75.25")},
        ]
        csv_str = export_csv(data)
        lines = csv_str.strip().split("\n")
        assert len(lines) == 3
        assert "account" in lines[0]
        assert "total" in lines[0]
        assert "Expenses:Groceries" in lines[1]
        assert "100.50" in lines[1]

    def test_export_csv_empty(self):
        assert export_csv([]) == ""


class TestExportJson:
    def test_export_json(self):
        data = [
            {"account": "Expenses:Groceries", "total": Decimal("100.50")},
        ]
        json_str = export_json(data)
        parsed = json.loads(json_str)
        assert len(parsed) == 1
        assert parsed[0]["account"] == "Expenses:Groceries"
        assert parsed[0]["total"] == "100.50"

    def test_export_json_to_file(self, tmp_path):
        data = {"net_worth": Decimal("50000.00")}
        out_path = tmp_path / "output.json"
        result = export_json(data, file_path=out_path)
        assert result == str(out_path)
        assert out_path.exists()
        parsed = json.loads(out_path.read_text())
        assert parsed["net_worth"] == "50000.00"
