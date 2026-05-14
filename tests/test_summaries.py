from __future__ import annotations

from decimal import Decimal

import pytest

from finkit.db import Database
from finkit.summaries.registry import registry, RefreshContext

# Import summary builders so they register themselves
import finkit.summaries.daily_balances  # noqa: F401
import finkit.summaries.monthly_spending  # noqa: F401
import finkit.summaries.capital_gains  # noqa: F401
import finkit.summaries.portfolio_holdings  # noqa: F401
import finkit.summaries.monthly_balances  # noqa: F401
import finkit.summaries.net_worth  # noqa: F401


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    database.create_schema()
    database.execute("INSERT INTO currency_tolerances VALUES ('USD', '0.01')")
    database.execute("INSERT INTO currency_tolerances VALUES ('INR', '0.01')")
    database.execute("INSERT INTO currency_tolerances VALUES ('BTC', '0.00000001')")
    database.conn.commit()
    yield database
    database.close()


def _create_account(db, name, type_, currency="USD", **kwargs):
    db.execute(
        "INSERT INTO accounts (name, type, currency, booking_method, institution, asset_class, jurisdiction, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, '2024-01-01')",
        (name, type_, currency, kwargs.get("booking_method"), kwargs.get("institution"), kwargs.get("asset_class"), kwargs.get("jurisdiction")),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_transaction(db, uuid, date, payee=None):
    db.execute(
        "INSERT INTO transactions (uuid, date, payee, status, created_at) VALUES (?, ?, ?, 'cleared', '2024-01-01T00:00:00+00:00')",
        (uuid, date, payee),
    )
    row = db.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


def _insert_posting(db, txn_id, account_id, amount, currency="USD"):
    db.execute(
        "INSERT INTO postings (transaction_id, account_id, amount, currency) VALUES (?, ?, ?, ?)",
        (txn_id, account_id, str(amount), currency),
    )


def test_rebuild_daily_balances(db):
    checking = _create_account(db, "Assets:Chase:Checking", "Assets")
    groceries = _create_account(db, "Expenses:Groceries", "Expenses")

    txn1 = _insert_transaction(db, "aaa00001", "2024-01-15")
    _insert_posting(db, txn1, checking, Decimal("-50.00"))
    _insert_posting(db, txn1, groceries, Decimal("50.00"))

    txn2 = _insert_transaction(db, "aaa00002", "2024-01-20")
    _insert_posting(db, txn2, checking, Decimal("-30.00"))
    _insert_posting(db, txn2, groceries, Decimal("30.00"))

    db.conn.commit()

    registry.rebuild_all(db)
    db.conn.commit()

    rows = db.fetchall(
        "SELECT * FROM s_daily_balances WHERE account_id = ? ORDER BY date",
        (checking,),
    )
    assert len(rows) == 2
    assert Decimal(rows[0]["balance"]) == Decimal("-50.00")
    assert Decimal(rows[1]["balance"]) == Decimal("-80.00")


def test_monthly_spending_keys_by_expense(db):
    checking = _create_account(db, "Assets:Chase:Checking", "Assets")
    groceries = _create_account(db, "Expenses:Groceries", "Expenses")

    txn1 = _insert_transaction(db, "bbb00001", "2024-02-10")
    _insert_posting(db, txn1, checking, Decimal("-100.00"))
    _insert_posting(db, txn1, groceries, Decimal("100.00"))
    db.conn.commit()

    registry.rebuild_all(db)
    db.conn.commit()

    expense_rows = db.fetchall(
        "SELECT * FROM s_monthly_spending WHERE account_id = ?",
        (groceries,),
    )
    assert len(expense_rows) == 1
    assert Decimal(expense_rows[0]["total"]) == Decimal("100.00")
    assert expense_rows[0]["year_month"] == "2024-02"

    bank_rows = db.fetchall(
        "SELECT * FROM s_monthly_spending WHERE account_id = ?",
        (checking,),
    )
    assert len(bank_rows) == 0


def test_refresh_incremental(db):
    checking = _create_account(db, "Assets:Chase:Checking", "Assets")
    groceries = _create_account(db, "Expenses:Groceries", "Expenses")

    txn1 = _insert_transaction(db, "ccc00001", "2024-03-01")
    _insert_posting(db, txn1, checking, Decimal("-25.00"))
    _insert_posting(db, txn1, groceries, Decimal("25.00"))
    db.conn.commit()

    registry.rebuild_all(db)
    db.conn.commit()

    row = db.fetchone(
        "SELECT balance FROM s_daily_balances WHERE account_id = ? AND date = '2024-03-01'",
        (checking,),
    )
    assert Decimal(row["balance"]) == Decimal("-25.00")

    txn2 = _insert_transaction(db, "ccc00002", "2024-03-05")
    _insert_posting(db, txn2, checking, Decimal("-15.00"))
    _insert_posting(db, txn2, groceries, Decimal("15.00"))
    db.conn.commit()

    context = RefreshContext(
        affected_account_ids={checking, groceries},
        affected_date_range=("2024-03-05", "2024-03-05"),
        affected_commodities={"USD"},
    )
    registry.refresh_all(db, context)
    db.conn.commit()

    rows = db.fetchall(
        "SELECT * FROM s_daily_balances WHERE account_id = ? ORDER BY date",
        (checking,),
    )
    assert len(rows) == 2
    assert Decimal(rows[0]["balance"]) == Decimal("-25.00")
    assert Decimal(rows[1]["balance"]) == Decimal("-40.00")


def test_rebuild_idempotent(db):
    checking = _create_account(db, "Assets:Chase:Checking", "Assets")
    groceries = _create_account(db, "Expenses:Groceries", "Expenses")

    txn1 = _insert_transaction(db, "ddd00001", "2024-04-01")
    _insert_posting(db, txn1, checking, Decimal("-200.00"))
    _insert_posting(db, txn1, groceries, Decimal("200.00"))
    db.conn.commit()

    registry.rebuild_all(db)
    db.conn.commit()

    first_balances = db.fetchall("SELECT * FROM s_daily_balances ORDER BY account_id, date")
    first_spending = db.fetchall("SELECT * FROM s_monthly_spending ORDER BY account_id, year_month")

    registry.rebuild_all(db)
    db.conn.commit()

    second_balances = db.fetchall("SELECT * FROM s_daily_balances ORDER BY account_id, date")
    second_spending = db.fetchall("SELECT * FROM s_monthly_spending ORDER BY account_id, year_month")

    assert len(first_balances) == len(second_balances)
    for a, b in zip(first_balances, second_balances):
        assert a["account_id"] == b["account_id"]
        assert a["date"] == b["date"]
        assert a["balance"] == b["balance"]

    assert len(first_spending) == len(second_spending)
    for a, b in zip(first_spending, second_spending):
        assert a["account_id"] == b["account_id"]
        assert a["year_month"] == b["year_month"]
        assert a["total"] == b["total"]


def test_capital_gains_summary(db):
    brokerage = _create_account(
        db, "Assets:Fidelity:Brokerage", "Assets",
        booking_method="FIFO", asset_class="equity", jurisdiction="US",
    )

    txn_buy = _insert_transaction(db, "eee00001", "2024-01-10")
    _insert_posting(db, txn_buy, brokerage, Decimal("10"))

    db.execute(
        "INSERT INTO lots (account_id, commodity, quantity, original_quantity, cost_price, cost_currency, acquired_date, source_transaction_id, disposed) "
        "VALUES (?, 'AAPL', '10', '10', '150.00', 'USD', '2024-01-10', ?, 0)",
        (brokerage, txn_buy),
    )
    lot_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    txn_sell = _insert_transaction(db, "eee00002", "2024-07-15")
    _insert_posting(db, txn_sell, brokerage, Decimal("-10"))

    db.execute(
        "INSERT INTO lot_dispositions (lot_id, sell_transaction_id, quantity, proceeds_per_unit, proceeds_currency, gain_loss, gain_loss_currency, term, wash_sale) "
        "VALUES (?, ?, '10', '170.00', 'USD', '200.00', 'USD', 'long', 0)",
        (lot_id, txn_sell),
    )

    db.execute("UPDATE lots SET quantity = '0', disposed = 1 WHERE id = ?", (lot_id,))
    db.conn.commit()

    registry.rebuild_all(db)
    db.conn.commit()

    rows = db.fetchall("SELECT * FROM s_yearly_capital_gains WHERE year = 2024")
    assert len(rows) >= 1

    cg_row = [r for r in rows if r["term"] == "long"][0]
    assert Decimal(cg_row["total_gain_loss"]) == Decimal("200.00")
    assert cg_row["disposition_count"] == 1


def test_portfolio_holdings(db):
    brokerage = _create_account(
        db, "Assets:Schwab:Brokerage", "Assets",
        booking_method="FIFO", asset_class="equity", jurisdiction="US",
    )

    txn1 = _insert_transaction(db, "fff00001", "2024-01-05")
    _insert_posting(db, txn1, brokerage, Decimal("20"))

    db.execute(
        "INSERT INTO lots (account_id, commodity, quantity, original_quantity, cost_price, cost_currency, acquired_date, source_transaction_id, disposed) "
        "VALUES (?, 'MSFT', '20', '20', '300.00', 'USD', '2024-01-05', ?, 0)",
        (brokerage, txn1),
    )

    db.execute(
        "INSERT INTO prices (commodity, currency, price, date, source) VALUES ('MSFT', 'USD', '350.00', '2024-06-01', 'test')",
    )
    db.conn.commit()

    registry.rebuild_all(db)
    db.conn.commit()

    rows = db.fetchall(
        "SELECT * FROM s_portfolio_holdings WHERE account_id = ? AND commodity = 'MSFT'",
        (brokerage,),
    )
    assert len(rows) == 1

    holding = rows[0]
    assert Decimal(holding["total_quantity"]) == Decimal("20")
    assert Decimal(holding["total_cost_basis"]) == Decimal("6000.00")
    assert Decimal(holding["latest_price"]) == Decimal("350.00")
    assert Decimal(holding["market_value"]) == Decimal("7000.00")
    assert Decimal(holding["unrealized_gain"]) == Decimal("1000.00")
