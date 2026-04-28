"""Tests for analysis tools — spending, portfolio, capital gains, what-if, export."""

import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from personalfinance.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def simple_env(tmp_path):
    ledger = tmp_path / "main.beancount"
    shutil.copy(FIXTURES / "simple.beancount", ledger)
    load_config(tmp_path)
    return tmp_path


@pytest.fixture
def invest_env(tmp_path):
    ledger = tmp_path / "main.beancount"
    shutil.copy(FIXTURES / "investments.beancount", ledger)
    load_config(tmp_path)
    return tmp_path


class TestSpendingAnalysis:
    def test_spending_by_category(self, simple_env):
        from personalfinance.analysis.spending import analyze_spending
        result = analyze_spending(ledger_path=str(simple_env / "main.beancount"))
        assert result["status"] == "ok"
        assert Decimal(result["total_expenses"]) > 0
        assert "breakdown" in result

    def test_spending_by_month(self, simple_env):
        from personalfinance.analysis.spending import analyze_spending
        result = analyze_spending(
            group_by="month",
            ledger_path=str(simple_env / "main.beancount"),
        )
        assert result["status"] == "ok"
        breakdown = result["breakdown"]
        assert isinstance(breakdown, list)
        assert len(breakdown) >= 1

    def test_spending_by_payee(self, simple_env):
        from personalfinance.analysis.spending import analyze_spending
        result = analyze_spending(
            group_by="payee",
            ledger_path=str(simple_env / "main.beancount"),
        )
        assert result["status"] == "ok"

    def test_spending_date_filter(self, simple_env):
        from personalfinance.analysis.spending import analyze_spending
        result = analyze_spending(
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 31),
            ledger_path=str(simple_env / "main.beancount"),
        )
        assert result["status"] == "ok"


class TestPortfolioAnalysis:
    def test_portfolio_basic(self, invest_env):
        from personalfinance.analysis.portfolio import analyze_portfolio
        result = analyze_portfolio(
            date_=date(2025, 3, 31),
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "ok"
        assert "net_worth" in result
        assert "holdings" in result

    def test_portfolio_holdings_detail(self, invest_env):
        from personalfinance.analysis.portfolio import analyze_portfolio
        result = analyze_portfolio(
            date_=date(2025, 3, 31),
            ledger_path=str(invest_env / "main.beancount"),
        )
        holdings = result["holdings"]
        if holdings:
            h = holdings[0]
            assert "commodity" in h
            assert "quantity" in h
            assert "market_value" in h
            assert "unrealized_gain" in h


class TestCapitalGains:
    def test_capital_gains_report(self, invest_env):
        from personalfinance.analysis.capital_gains import report_capital_gains
        result = report_capital_gains(year=2025, ledger_path=str(invest_env / "main.beancount"))
        assert result["status"] == "ok"
        assert result["year"] == 2025
        total = Decimal(result["total_gain_loss"])
        assert total != 0

    def test_capital_gains_lot_detail(self, invest_env):
        from personalfinance.analysis.capital_gains import report_capital_gains
        result = report_capital_gains(year=2025, ledger_path=str(invest_env / "main.beancount"))
        all_dispositions = (
            result["short_term"]["dispositions"] +
            result["long_term"]["dispositions"]
        )
        if all_dispositions:
            d = all_dispositions[0]
            assert "buy_date" in d
            assert "sell_date" in d
            assert "cost_basis" in d
            assert "gain_loss" in d
            assert "term" in d


class TestWhatIfSell:
    def test_whatif_basic(self, invest_env):
        from personalfinance.analysis.whatif import what_if_sell
        result = what_if_sell(
            commodity="AAPL",
            quantity=Decimal("30"),
            price=Decimal("210"),
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "ok"
        assert result["commodity"] == "AAPL"
        assert "note" in result
        assert "simulation" in result["note"].lower()

    def test_whatif_insufficient(self, invest_env):
        from personalfinance.analysis.whatif import what_if_sell
        result = what_if_sell(
            commodity="AAPL",
            quantity=Decimal("999"),
            price=Decimal("200"),
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "error"
        assert "insufficient" in result["message"].lower()

    def test_whatif_no_holdings(self, invest_env):
        from personalfinance.analysis.whatif import what_if_sell
        result = what_if_sell(
            commodity="GOOG",
            quantity=Decimal("10"),
            price=Decimal("100"),
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "error"

    def test_whatif_does_not_modify_ledger(self, invest_env):
        from personalfinance.analysis.whatif import what_if_sell
        ledger = invest_env / "main.beancount"
        content_before = ledger.read_text()
        what_if_sell(
            commodity="AAPL",
            quantity=Decimal("30"),
            price=Decimal("210"),
            ledger_path=str(ledger),
        )
        content_after = ledger.read_text()
        assert content_before == content_after


class TestExport:
    def test_export_json(self, simple_env):
        from personalfinance.analysis.export import export_output
        result = export_output(
            tool_name="get_balances",
            format="json",
        )
        assert result["status"] == "ok"
        data = json.loads(result["content"])
        assert "balances" in data

    def test_export_csv(self, simple_env):
        from personalfinance.analysis.export import export_output
        result = export_output(
            tool_name="get_balances",
            format="csv",
        )
        assert result["status"] == "ok"

    def test_export_to_file(self, simple_env):
        from personalfinance.analysis.export import export_output
        out = simple_env / "export.json"
        result = export_output(
            tool_name="get_balances",
            format="json",
            output_path=str(out),
        )
        assert result["status"] == "ok"
        assert out.exists()

    def test_export_unknown_tool(self, simple_env):
        from personalfinance.analysis.export import export_output
        result = export_output(tool_name="nonexistent_tool", format="json")
        assert result["status"] == "error"
