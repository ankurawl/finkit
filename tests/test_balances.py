from __future__ import annotations

import os
from decimal import Decimal

import pytest

from finkit.db import Database
from finkit.engine.balances import (
    assert_balance,
    compute_all_balances,
    compute_balance,
    compute_subtree_balance,
)
from finkit.models import BalanceAssertion


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    database.create_schema()
    database.execute("INSERT INTO currency_tolerances VALUES ('USD', '0.01')")
    database.execute("INSERT INTO currency_tolerances VALUES ('INR', '0.01')")
    database.execute("INSERT INTO currency_tolerances VALUES ('EUR', '0.01')")
    database.execute("INSERT INTO currency_tolerances VALUES ('BTC', '0.00000001')")
    database.conn.commit()
    yield database
    database.close()


def _create_account(db, name, type_, currency="USD", booking_method=None, jurisdiction=None, asset_class=None):
    db.execute(
        "INSERT INTO accounts (name, type, currency, booking_method, jurisdiction, asset_class, opened_at) VALUES (?, ?, ?, ?, ?, ?, '2024-01-01')",
        (name, type_, currency, booking_method, jurisdiction, asset_class),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _create_transaction(db, date="2024-06-15"):
    db.execute(
        "INSERT INTO transactions (uuid, date, created_at) VALUES (?, ?, ?)",
        (os.urandom(4).hex(), date, "2024-01-01T00:00:00"),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_posting(db, account_id, amount, currency="USD", date="2024-06-15"):
    tx_id = _create_transaction(db, date)
    db.execute(
        "INSERT INTO postings (transaction_id, account_id, amount, currency) VALUES (?, ?, ?, ?)",
        (tx_id, account_id, str(amount), currency),
    )
    db.conn.commit()
    return tx_id


class TestComputeBalance:
    def test_account_balance(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")

        _insert_posting(db, checking, Decimal("1000.00"))
        _insert_posting(db, checking, Decimal("-250.00"))
        _insert_posting(db, checking, Decimal("500.00"))

        balances = compute_balance(db, checking)
        assert balances["USD"] == Decimal("1250.00")

    def test_account_balance_as_of_date(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")

        _insert_posting(db, checking, Decimal("1000.00"), date="2024-06-01")
        _insert_posting(db, checking, Decimal("500.00"), date="2024-06-10")
        _insert_posting(db, checking, Decimal("-200.00"), date="2024-06-20")

        balances = compute_balance(db, checking, as_of_date="2024-06-15")
        assert balances["USD"] == Decimal("1500.00")


class TestSubtreeBalance:
    def test_subtree_balance(self, db):
        chase_checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        chase_savings = _create_account(db, "Assets:Chase:Savings", "Assets")

        _insert_posting(db, chase_checking, Decimal("1000.00"))
        _insert_posting(db, chase_savings, Decimal("5000.00"))

        balances = compute_subtree_balance(db, "Assets:Chase")
        assert balances["USD"] == Decimal("6000.00")

    def test_subtree_excludes_non_matching(self, db):
        chase_checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        hdfc_savings = _create_account(db, "Assets:HDFC:Savings", "Assets", currency="INR")

        _insert_posting(db, chase_checking, Decimal("1000.00"))
        _insert_posting(db, hdfc_savings, Decimal("50000.00"), currency="INR")

        balances = compute_subtree_balance(db, "Assets:Chase")
        assert balances.get("USD") == Decimal("1000.00")
        assert "INR" not in balances


class TestBalanceAssertion:
    def test_balance_assertion_match(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        _insert_posting(db, checking, Decimal("1000.00"), date="2024-06-01")

        assertion = assert_balance(
            db, checking, "2024-06-15", Decimal("1000.00"), "USD",
        )
        assert assertion.matches is True
        assert assertion.actual_amount == Decimal("1000.00")
        assert assertion.difference == Decimal("0")

    def test_balance_assertion_mismatch(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        _insert_posting(db, checking, Decimal("1000.00"), date="2024-06-01")

        assertion = assert_balance(
            db, checking, "2024-06-15", Decimal("1500.00"), "USD",
        )
        assert assertion.matches is False
        assert assertion.actual_amount == Decimal("1000.00")
        assert assertion.difference == Decimal("-500.00")


class TestMultiCurrencyBalance:
    def test_multi_currency_balance(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            currency="USD", booking_method="FIFO",
        )

        _insert_posting(db, acct, Decimal("1000.00"), currency="USD")
        _insert_posting(db, acct, Decimal("50000.00"), currency="INR")

        balances = compute_balance(db, acct)
        assert balances["USD"] == Decimal("1000.00")
        assert balances["INR"] == Decimal("50000.00")


class TestComputeAllBalances:
    def test_all_balances_by_type(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        savings = _create_account(db, "Assets:Chase:Savings", "Assets")
        groceries = _create_account(db, "Expenses:Groceries", "Expenses")

        _insert_posting(db, checking, Decimal("5000.00"))
        _insert_posting(db, savings, Decimal("10000.00"))
        _insert_posting(db, groceries, Decimal("200.00"))

        all_assets = compute_all_balances(db, account_type="Assets")
        assert checking in all_assets
        assert savings in all_assets
        assert groceries not in all_assets
        assert all_assets[checking]["USD"] == Decimal("5000.00")
        assert all_assets[savings]["USD"] == Decimal("10000.00")
