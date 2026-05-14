from __future__ import annotations

from decimal import Decimal

import pytest

from finkit.config import Settings
from finkit.db import Database
from finkit.engine.validation import UnbalancedTransactionError
from finkit.operations import (
    amend_transaction,
    assert_balance,
    init_ledger,
    open_account,
    submit_transaction,
    undo_import,
)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def ledger_db(settings):
    db = init_ledger(settings)
    yield db
    db.close()


def test_init_creates_db(settings):
    db = init_ledger(settings)
    try:
        assert settings.db_path.exists()
        tables = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {r["name"] for r in tables}
        assert "accounts" in table_names
        assert "transactions" in table_names
        assert "postings" in table_names
    finally:
        db.close()


def test_init_existing_db(settings):
    db1 = init_ledger(settings)
    db1.close()

    db2 = init_ledger(settings)
    try:
        assert settings.db_path.exists()
        row = db2.fetchone("SELECT name FROM accounts WHERE name = 'Equity:OpeningBalances'")
        assert row is not None
    finally:
        db2.close()


def test_open_account(ledger_db):
    acct_id = open_account(
        ledger_db,
        name="Assets:Chase:Checking",
        type="Assets",
        currency="USD",
        institution="Chase",
    )
    assert acct_id is not None

    row = ledger_db.fetchone("SELECT * FROM accounts WHERE id = ?", (acct_id,))
    assert row["name"] == "Assets:Chase:Checking"
    assert row["type"] == "Assets"
    assert row["currency"] == "USD"
    assert row["institution"] == "Chase"


def test_open_account_invalid_hierarchy(ledger_db):
    with pytest.raises(ValueError, match="First segment must be one of"):
        open_account(ledger_db, name="Invalid:Account", type="Invalid")


def test_submit_simple_transaction(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-03-15",
        payee="Whole Foods",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "50.00", "currency": "USD"},
        ],
    )

    assert uuid is not None
    assert len(uuid) == 8

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn is not None
    assert txn["payee"] == "Whole Foods"
    assert txn["date"] == "2024-03-15"


def test_submit_opening_balance(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-01-01",
        narration="Opening balance",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Equity:OpeningBalances", "amount": "-5000.00", "currency": "USD"},
        ],
    )

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn is not None

    postings = ledger_db.fetchall(
        "SELECT p.*, a.name AS account_name FROM postings p JOIN accounts a ON p.account_id = a.id WHERE p.transaction_id = ?",
        (txn["id"],),
    )
    assert len(postings) == 2

    account_names = {p["account_name"] for p in postings}
    assert "Equity:OpeningBalances" in account_names
    assert "Assets:Chase:Checking" in account_names


def test_submit_investment_buy(ledger_db):
    open_account(
        ledger_db,
        name="Assets:Fidelity:Brokerage",
        type="Assets",
        currency="USD",
        booking_method="FIFO",
    )
    open_account(ledger_db, name="Assets:Fidelity:Cash", type="Assets")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-02-01",
        narration="Buy AAPL",
        postings=[
            {
                "account": "Assets:Fidelity:Brokerage",
                "amount": "10",
                "currency": "AAPL",
                "price": "150.00",
                "price_currency": "USD",
            },
            {
                "account": "Assets:Fidelity:Cash",
                "amount": "-1500.00",
                "currency": "USD",
            },
        ],
    )

    assert uuid is not None

    lots = ledger_db.fetchall("SELECT * FROM lots")
    assert len(lots) == 1
    assert lots[0]["commodity"] == "AAPL"
    assert Decimal(lots[0]["quantity"]) == Decimal("10")
    assert Decimal(lots[0]["cost_price"]) == Decimal("150.00")


def test_amend_transaction(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-04-01",
        payee="Trader Joes",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-60.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "60.00", "currency": "USD"},
        ],
    )

    amend_transaction(ledger_db, uuid, updates={"payee": "Trader Joe's"})

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn["payee"] == "Trader Joe's"


def test_amend_delete(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Dining", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-04-10",
        payee="Restaurant",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-45.00", "currency": "USD"},
            {"account": "Expenses:Dining", "amount": "45.00", "currency": "USD"},
        ],
    )

    txn_before = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn_before is not None

    amend_transaction(ledger_db, uuid, delete=True)

    txn_after = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn_after is None


def test_assert_balance_match(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    submit_transaction(
        ledger_db,
        date="2024-01-01",
        narration="Opening",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "1000.00", "currency": "USD"},
            {"account": "Equity:OpeningBalances", "amount": "-1000.00", "currency": "USD"},
        ],
    )

    submit_transaction(
        ledger_db,
        date="2024-01-15",
        payee="Grocery Store",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-150.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "150.00", "currency": "USD"},
        ],
    )

    result = assert_balance(
        ledger_db,
        account_name="Assets:Chase:Checking",
        date="2024-01-31",
        expected_amount="850.00",
        currency="USD",
    )

    assert result["matches"] is True
    assert Decimal(result["actual_amount"]) == Decimal("850.00")
    assert Decimal(result["expected_amount"]) == Decimal("850.00")


def test_atomic_rollback(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    with pytest.raises(UnbalancedTransactionError):
        submit_transaction(
            ledger_db,
            date="2024-05-01",
            payee="Bad Transaction",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-100.00", "currency": "USD"},
                {"account": "Expenses:Groceries", "amount": "99.00", "currency": "USD"},
            ],
        )

    txns = ledger_db.fetchall("SELECT * FROM transactions WHERE payee = 'Bad Transaction'")
    assert len(txns) == 0

    postings = ledger_db.fetchall("SELECT * FROM postings")
    assert len(postings) == 0
