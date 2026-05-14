from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from finkit.analysis.capital_gains import report_capital_gains
from finkit.analysis.portfolio import analyze_portfolio
from finkit.analysis.spending import analyze_spending
from finkit.config import Settings
from finkit.db import Database
from finkit.engine.lots import get_lots
from finkit.engine.prices import store_price
from finkit.importers.file_importer import import_file, save_column_mapping
from finkit.operations import (
    corporate_action,
    init_ledger,
    open_account,
    submit_transaction,
    undo_import,
)
from finkit.queries import get_balances, get_transactions, run_query
from finkit.summaries.registry import SummaryRegistry

# Import summary builders so they register themselves
import finkit.summaries.daily_balances  # noqa: F401
import finkit.summaries.monthly_spending  # noqa: F401
import finkit.summaries.monthly_balances  # noqa: F401
import finkit.summaries.portfolio_holdings  # noqa: F401
import finkit.summaries.capital_gains  # noqa: F401
import finkit.summaries.net_worth  # noqa: F401

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CHASE_MAPPING = {
    "date_col": "Posting Date",
    "payee_col": "Description",
    "amount_col": "Amount",
    "amount_sign": "negative_is_debit",
    "date_format": "%m/%d/%Y",
    "default_currency": "USD",
}


# ---------------------------------------------------------------------------
# Test 1: init -> spending analysis
# ---------------------------------------------------------------------------


class TestInitToSpendingAnalysis:
    def test_init_to_spending_analysis(self, ledger_db, settings):
        checking_id = open_account(
            ledger_db, "Assets:Chase:Checking", "Assets", currency="USD",
        )
        open_account(ledger_db, "Expenses:Groceries", "Expenses", currency="USD")
        open_account(ledger_db, "Expenses:Rent", "Expenses", currency="USD")
        open_account(ledger_db, "Income:Salary", "Income", currency="USD")
        ledger_db.conn.commit()

        submit_transaction(
            ledger_db, "2024-01-01",
            postings=[
                {"account": "Equity:OpeningBalances", "amount": "-10000.00", "currency": "USD"},
                {"account": "Assets:Chase:Checking", "amount": "10000.00", "currency": "USD"},
            ],
            narration="Opening balance",
            settings=settings,
        )

        submit_transaction(
            ledger_db, "2024-01-05",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
                {"account": "Income:Salary", "amount": "-5000.00", "currency": "USD"},
            ],
            payee="Employer",
            settings=settings,
        )

        submit_transaction(
            ledger_db, "2024-01-10",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-200.00", "currency": "USD"},
                {"account": "Expenses:Groceries", "amount": "200.00", "currency": "USD"},
            ],
            payee="Whole Foods",
            settings=settings,
        )
        submit_transaction(
            ledger_db, "2024-01-15",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-2000.00", "currency": "USD"},
                {"account": "Expenses:Rent", "amount": "2000.00", "currency": "USD"},
            ],
            payee="Landlord",
            settings=settings,
        )

        spending = analyze_spending(
            ledger_db, year_month="2024-01", months=1, currency="USD",
        )
        assert Decimal(spending["total_expenses"]) == Decimal("2200")
        assert Decimal(spending["total_income"]) == Decimal("-5000")

        balances = get_balances(ledger_db, account_name="Assets:Chase:Checking")
        assert len(balances) >= 1
        checking_balance = Decimal(balances[0]["balance"])
        assert checking_balance == Decimal("12800")


# ---------------------------------------------------------------------------
# Test 2: multi-currency net worth
# ---------------------------------------------------------------------------


class TestMultiCurrencyNetWorth:
    def test_multi_currency_net_worth(self, ledger_db, settings):
        open_account(ledger_db, "Assets:Chase:Checking", "Assets", currency="USD")
        open_account(ledger_db, "Assets:HDFC:Savings", "Assets", currency="INR")
        open_account(ledger_db, "Income:Salary:US", "Income", currency="USD")
        open_account(ledger_db, "Income:Salary:IN", "Income", currency="INR")
        ledger_db.conn.commit()

        submit_transaction(
            ledger_db, "2024-01-01",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "50000.00", "currency": "USD"},
                {"account": "Income:Salary:US", "amount": "-50000.00", "currency": "USD"},
            ],
            payee="US Employer",
            settings=settings,
        )

        submit_transaction(
            ledger_db, "2024-01-01",
            postings=[
                {"account": "Assets:HDFC:Savings", "amount": "1000000.00", "currency": "INR"},
                {"account": "Income:Salary:IN", "amount": "-1000000.00", "currency": "INR"},
            ],
            payee="IN Employer",
            settings=settings,
        )

        store_price(ledger_db, "INR", "USD", Decimal("0.012"), "2024-01-01")
        ledger_db.conn.commit()

        usd_balances = get_balances(
            ledger_db, account_name="Assets:Chase:Checking",
        )
        assert len(usd_balances) >= 1
        assert Decimal(usd_balances[0]["balance"]) == Decimal("50000")

        inr_balances = get_balances(
            ledger_db, account_name="Assets:HDFC:Savings",
        )
        assert len(inr_balances) >= 1
        assert Decimal(inr_balances[0]["balance"]) == Decimal("1000000")

        readonly_result = run_query(
            ledger_db,
            "SELECT COUNT(*) AS cnt FROM accounts WHERE currency = 'INR'",
        )
        assert readonly_result[0]["cnt"] >= 1


# ---------------------------------------------------------------------------
# Test 3: investment SIP flow with FIFO capital gains
# ---------------------------------------------------------------------------


class TestInvestmentSipFlow:
    def test_investment_sip_flow(self, ledger_db, settings):
        open_account(
            ledger_db, "Assets:Schwab:Stocks", "Assets",
            currency="USD", booking_method="FIFO",
            asset_class="equity", jurisdiction="US",
        )
        open_account(ledger_db, "Assets:Schwab:Cash", "Assets", currency="USD")
        open_account(ledger_db, "Income:CapitalGains", "Income", currency="USD")
        ledger_db.conn.commit()

        sip_dates_prices = [
            ("2024-01-10", "100.00"),
            ("2024-02-10", "105.00"),
            ("2024-03-10", "110.00"),
        ]
        for date, price in sip_dates_prices:
            total = Decimal(price) * Decimal("10")
            submit_transaction(
                ledger_db, date,
                postings=[
                    {
                        "account": "Assets:Schwab:Stocks",
                        "amount": "10",
                        "currency": "VTSAX",
                        "price": price,
                        "price_currency": "USD",
                    },
                    {"account": "Assets:Schwab:Cash", "amount": str(-total), "currency": "USD"},
                ],
                payee="SIP Buy",
                settings=settings,
            )

        lots = get_lots(ledger_db, account_id=_get_account_id(ledger_db, "Assets:Schwab:Stocks"), commodity="VTSAX")
        assert len(lots) == 3
        total_qty = sum(lot.quantity for lot in lots)
        assert total_qty == Decimal("30")

        submit_transaction(
            ledger_db, "2024-04-15",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "-15",
                    "currency": "VTSAX",
                    "price": "120.00",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "1800.00", "currency": "USD"},
            ],
            payee="Partial Redeem",
            settings=settings,
        )

        lots_after = get_lots(
            ledger_db,
            account_id=_get_account_id(ledger_db, "Assets:Schwab:Stocks"),
            commodity="VTSAX",
        )
        remaining_qty = sum(lot.quantity for lot in lots_after)
        assert remaining_qty == Decimal("15")

        cg_report = report_capital_gains(ledger_db, year=2024)

        assert len(cg_report["detail"]) >= 1

        total_gain = sum(Decimal(d["gain_loss"]) for d in cg_report["detail"])
        first_lot_gain = Decimal("10") * (Decimal("120") - Decimal("100"))
        second_lot_gain = Decimal("5") * (Decimal("120") - Decimal("105"))
        expected_total = first_lot_gain + second_lot_gain
        assert total_gain == expected_total

        for d in cg_report["detail"]:
            assert d["term"] == "short"


# ---------------------------------------------------------------------------
# Test 4: corporate action flow (stock split)
# ---------------------------------------------------------------------------


class TestCorporateActionFlow:
    def test_corporate_action_flow(self, ledger_db, settings):
        open_account(
            ledger_db, "Assets:Schwab:Stocks", "Assets",
            currency="USD", booking_method="FIFO",
            asset_class="equity", jurisdiction="US",
        )
        open_account(ledger_db, "Assets:Schwab:Cash", "Assets", currency="USD")
        open_account(ledger_db, "Income:CapitalGains", "Income", currency="USD")
        ledger_db.conn.commit()

        submit_transaction(
            ledger_db, "2024-01-10",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "10",
                    "currency": "AAPL",
                    "price": "400.00",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "-4000.00", "currency": "USD"},
            ],
            payee="Buy AAPL pre-split",
            settings=settings,
        )

        lots_before = get_lots(
            ledger_db,
            account_id=_get_account_id(ledger_db, "Assets:Schwab:Stocks"),
            commodity="AAPL",
        )
        assert len(lots_before) == 1
        assert lots_before[0].quantity == Decimal("10")
        assert lots_before[0].cost_price == Decimal("400")

        corporate_action(
            ledger_db,
            commodity="AAPL",
            action_type="split",
            ratio="4",
            date="2024-06-01",
            narration="AAPL 4:1 split",
        )

        lots_after = get_lots(
            ledger_db,
            account_id=_get_account_id(ledger_db, "Assets:Schwab:Stocks"),
            commodity="AAPL",
        )
        assert len(lots_after) == 1
        assert lots_after[0].quantity == Decimal("40")
        assert lots_after[0].cost_price == Decimal("100")
        total_cost_after = lots_after[0].quantity * lots_after[0].cost_price
        assert total_cost_after == Decimal("4000")

        submit_transaction(
            ledger_db, "2024-07-15",
            postings=[
                {
                    "account": "Assets:Schwab:Stocks",
                    "amount": "-20",
                    "currency": "AAPL",
                    "price": "120.00",
                    "price_currency": "USD",
                },
                {"account": "Assets:Schwab:Cash", "amount": "2400.00", "currency": "USD"},
            ],
            payee="Sell AAPL post-split",
            settings=settings,
        )

        cg = report_capital_gains(ledger_db, year=2024)
        assert len(cg["detail"]) >= 1
        gain = Decimal(cg["detail"][0]["gain_loss"])
        expected = Decimal("20") * (Decimal("120") - Decimal("100"))
        assert gain == expected


# ---------------------------------------------------------------------------
# Test 5: undo import
# ---------------------------------------------------------------------------


class TestUndoImport:
    def test_undo_import(self, ledger_db, settings):
        open_account(
            ledger_db, "Assets:Chase:Checking", "Assets",
            currency="USD", institution="chase",
        )
        open_account(ledger_db, "Expenses:Uncategorized", "Expenses", currency="USD")
        open_account(ledger_db, "Income:Uncategorized", "Income", currency="USD")
        ledger_db.conn.commit()

        save_column_mapping(ledger_db, "chase_checking", CHASE_MAPPING, institution="chase")
        ledger_db.conn.commit()

        chase_csv = FIXTURES_DIR / "chase_checking.csv"
        result = import_file(
            ledger_db,
            file_path=chase_csv,
            account_name="Assets:Chase:Checking",
            mapping_name="chase_checking",
            institution="chase",
            settings=settings,
        )

        source_file_id = result["source_file_id"]
        assert result["imported"] > 0

        txn_count_before = ledger_db.fetchone(
            "SELECT COUNT(*) AS cnt FROM transactions WHERE source_file_id = ?",
            (source_file_id,),
        )
        assert txn_count_before["cnt"] > 0

        raw_count_before = ledger_db.fetchone(
            "SELECT COUNT(*) AS cnt FROM raw_extractions WHERE source_file_id = ?",
            (source_file_id,),
        )
        assert raw_count_before["cnt"] > 0

        undo_result = undo_import(ledger_db, source_file_id)
        assert undo_result["deleted_transactions"] > 0

        txn_count_after = ledger_db.fetchone(
            "SELECT COUNT(*) AS cnt FROM transactions WHERE source_file_id = ?",
            (source_file_id,),
        )
        assert txn_count_after["cnt"] == 0

        raw_count_after = ledger_db.fetchone(
            "SELECT COUNT(*) AS cnt FROM raw_extractions WHERE source_file_id = ?",
            (source_file_id,),
        )
        assert raw_count_after["cnt"] == 0

        posting_count = ledger_db.fetchone(
            """SELECT COUNT(*) AS cnt FROM postings p
               JOIN transactions t ON p.transaction_id = t.id
               WHERE t.source_file_id = ?""",
            (source_file_id,),
        )
        assert posting_count["cnt"] == 0


# ---------------------------------------------------------------------------
# Test 6: summary rebuild consistency
# ---------------------------------------------------------------------------


class TestSummaryRebuildConsistency:
    def test_summary_rebuild_consistency(self, ledger_db, settings):
        open_account(ledger_db, "Assets:Chase:Checking", "Assets", currency="USD")
        open_account(ledger_db, "Expenses:Groceries", "Expenses", currency="USD")
        open_account(ledger_db, "Income:Salary", "Income", currency="USD")
        open_account(
            ledger_db, "Assets:Schwab:Stocks", "Assets",
            currency="USD", booking_method="FIFO",
            asset_class="equity", jurisdiction="US",
        )
        open_account(ledger_db, "Assets:Schwab:Cash", "Assets", currency="USD")
        open_account(ledger_db, "Income:CapitalGains", "Income", currency="USD")
        ledger_db.conn.commit()

        submit_transaction(
            ledger_db, "2024-01-05",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
                {"account": "Income:Salary", "amount": "-5000.00", "currency": "USD"},
            ],
            payee="Salary",
            settings=settings,
        )
        submit_transaction(
            ledger_db, "2024-01-10",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-200.00", "currency": "USD"},
                {"account": "Expenses:Groceries", "amount": "200.00", "currency": "USD"},
            ],
            payee="Groceries",
            settings=settings,
        )
        submit_transaction(
            ledger_db, "2024-02-05",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
                {"account": "Income:Salary", "amount": "-5000.00", "currency": "USD"},
            ],
            payee="Salary Feb",
            settings=settings,
        )
        submit_transaction(
            ledger_db, "2024-01-15",
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

        def _snapshot_summaries(db: Database) -> dict:
            snapshot = {}
            order_keys = {
                "s_daily_balances": "account_id, date, currency",
                "s_monthly_spending": "account_id, year_month, currency",
                "s_account_monthly_balances": "account_id, year_month, currency",
                "s_portfolio_holdings": "account_id, commodity",
                "s_yearly_capital_gains": "year, term, currency",
            }
            for table in order_keys:
                rows = db.fetchall(f"SELECT * FROM {table} ORDER BY {order_keys[table]}")
                snapshot[table] = rows
            return snapshot

        incremental_snapshot = _snapshot_summaries(ledger_db)

        with ledger_db.transaction():
            SummaryRegistry.rebuild_all(ledger_db)

        rebuilt_snapshot = _snapshot_summaries(ledger_db)

        for table in incremental_snapshot:
            inc_rows = incremental_snapshot[table]
            reb_rows = rebuilt_snapshot[table]
            assert len(inc_rows) == len(reb_rows), (
                f"{table}: row count mismatch "
                f"(incremental={len(inc_rows)}, rebuilt={len(reb_rows)})"
            )

            for i, (inc, reb) in enumerate(zip(inc_rows, reb_rows)):
                for key in inc:
                    if key in ("transaction_count",):
                        continue
                    assert inc[key] == reb[key], (
                        f"{table} row {i} field '{key}': "
                        f"incremental={inc[key]} != rebuilt={reb[key]}"
                    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _get_account_id(db: Database, name: str) -> int:
    row = db.fetchone("SELECT id FROM accounts WHERE name = ?", (name,))
    assert row is not None, f"Account {name} not found"
    return row["id"]
