from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from finkit.config import Settings
from finkit.db import Database
from finkit.operations import init_ledger, open_account, submit_transaction
from finkit.queries import (
    budget_vs_actual,
    get_balances,
    get_transactions,
    list_accounts,
    run_query,
)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def ledger_db(settings):
    db = init_ledger(settings)
    yield db
    db.close()


def _setup_basic_accounts(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    open_account(ledger_db, name="Expenses:Dining", type="Expenses")
    open_account(ledger_db, name="Income:Salary", type="Income")
    ledger_db.conn.commit()


def test_get_balances(ledger_db):
    _setup_basic_accounts(ledger_db)

    submit_transaction(
        ledger_db,
        date="2024-01-01",
        narration="Opening",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Equity:OpeningBalances", "amount": "-5000.00", "currency": "USD"},
        ],
    )

    submit_transaction(
        ledger_db,
        date="2024-01-15",
        payee="Grocery Store",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-200.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "200.00", "currency": "USD"},
        ],
    )

    balances = get_balances(ledger_db, account_name="Assets:Chase:Checking")
    assert len(balances) >= 1

    checking_balance = balances[0]
    assert Decimal(checking_balance["balance"]) == Decimal("4800.00")


def test_get_transactions_filter_payee(ledger_db):
    _setup_basic_accounts(ledger_db)

    submit_transaction(
        ledger_db,
        date="2024-02-01",
        payee="Whole Foods",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-75.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "75.00", "currency": "USD"},
        ],
    )

    submit_transaction(
        ledger_db,
        date="2024-02-05",
        payee="Chipotle",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-15.00", "currency": "USD"},
            {"account": "Expenses:Dining", "amount": "15.00", "currency": "USD"},
        ],
    )

    results = get_transactions(ledger_db, payee="Whole")
    assert len(results) == 1
    assert results[0]["payee"] == "Whole Foods"


def test_get_transactions_filter_date(ledger_db):
    _setup_basic_accounts(ledger_db)

    submit_transaction(
        ledger_db,
        date="2024-01-10",
        payee="January Purchase",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "50.00", "currency": "USD"},
        ],
    )

    submit_transaction(
        ledger_db,
        date="2024-03-10",
        payee="March Purchase",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-30.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "30.00", "currency": "USD"},
        ],
    )

    results = get_transactions(ledger_db, date_from="2024-02-01", date_to="2024-04-01")
    assert len(results) == 1
    assert results[0]["payee"] == "March Purchase"


def test_run_query_readonly(ledger_db):
    _setup_basic_accounts(ledger_db)

    results = run_query(ledger_db, "SELECT name FROM accounts ORDER BY name")
    assert len(results) >= 1
    account_names = [r["name"] for r in results]
    assert "Assets:Chase:Checking" in account_names

    with pytest.raises(sqlite3.OperationalError):
        run_query(
            ledger_db,
            "INSERT INTO accounts (name, type, currency, opened_at) VALUES ('Assets:Hack', 'Assets', 'USD', '2024-01-01')",
        )


def test_budget_vs_actual(ledger_db):
    _setup_basic_accounts(ledger_db)

    groceries_id = ledger_db.fetchone(
        "SELECT id FROM accounts WHERE name = 'Expenses:Groceries'"
    )["id"]

    ledger_db.execute(
        "INSERT INTO budgets (account_id, year_month, amount, currency) VALUES (?, ?, ?, ?)",
        (groceries_id, "2024-03", "500.00", "USD"),
    )
    ledger_db.conn.commit()

    submit_transaction(
        ledger_db,
        date="2024-03-05",
        payee="Grocery Run",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-350.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "350.00", "currency": "USD"},
        ],
    )

    results = budget_vs_actual(ledger_db, "2024-03", currency="USD")

    grocery_row = [r for r in results if r["account"] == "Expenses:Groceries"]
    assert len(grocery_row) == 1
    assert Decimal(grocery_row[0]["budget"]) == Decimal("500.00")
    assert Decimal(grocery_row[0]["actual"]) == Decimal("350.00")
    assert Decimal(grocery_row[0]["difference"]) == Decimal("150.00")


def test_list_accounts(ledger_db):
    _setup_basic_accounts(ledger_db)

    all_accounts = list_accounts(ledger_db)
    all_names = {a["name"] for a in all_accounts}
    assert "Assets:Chase:Checking" in all_names
    assert "Expenses:Groceries" in all_names
    assert "Income:Salary" in all_names

    asset_accounts = list_accounts(ledger_db, account_type="Assets")
    asset_names = {a["name"] for a in asset_accounts}
    assert "Assets:Chase:Checking" in asset_names
    assert "Expenses:Groceries" not in asset_names

    expense_accounts = list_accounts(ledger_db, account_type="Expenses")
    expense_names = {a["name"] for a in expense_accounts}
    assert "Expenses:Groceries" in expense_names
    assert "Expenses:Dining" in expense_names
    assert "Assets:Chase:Checking" not in expense_names
