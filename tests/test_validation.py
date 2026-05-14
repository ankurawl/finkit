from __future__ import annotations

import os
from decimal import Decimal

import pytest

from finkit.db import Database
from finkit.engine.validation import (
    AccountClosedError,
    AccountNotFoundError,
    CurrencyMismatchError,
    UnbalancedTransactionError,
    check_balance,
    get_tolerances,
    validate_transaction,
)
from finkit.models import Posting, Transaction


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


def _make_txn(postings, date="2024-06-15"):
    return Transaction(
        uuid=os.urandom(4).hex(),
        date=date,
        payee="Test",
        created_at="2024-01-01T00:00:00",
        postings=postings,
    )


class TestBalancedTransaction:
    def test_balanced_transaction(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        groceries = _create_account(db, "Expenses:Groceries", "Expenses")

        txn = _make_txn([
            Posting(account_id=checking, amount=Decimal("-50.00"), currency="USD"),
            Posting(account_id=groceries, amount=Decimal("50.00"), currency="USD"),
        ])
        validate_transaction(db, txn)

    def test_unbalanced_transaction(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        groceries = _create_account(db, "Expenses:Groceries", "Expenses")

        txn = _make_txn([
            Posting(account_id=checking, amount=Decimal("-50.00"), currency="USD"),
            Posting(account_id=groceries, amount=Decimal("45.00"), currency="USD"),
        ])
        with pytest.raises(UnbalancedTransactionError):
            validate_transaction(db, txn)

    def test_within_tolerance(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        groceries = _create_account(db, "Expenses:Groceries", "Expenses")

        txn = _make_txn([
            Posting(account_id=checking, amount=Decimal("-50.00"), currency="USD"),
            Posting(account_id=groceries, amount=Decimal("49.995"), currency="USD"),
        ])
        validate_transaction(db, txn)

    def test_outside_tolerance(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        groceries = _create_account(db, "Expenses:Groceries", "Expenses")

        txn = _make_txn([
            Posting(account_id=checking, amount=Decimal("-50.00"), currency="USD"),
            Posting(account_id=groceries, amount=Decimal("49.97"), currency="USD"),
        ])
        with pytest.raises(UnbalancedTransactionError):
            validate_transaction(db, txn)


class TestCryptoTolerance:
    def test_crypto_within_tolerance(self, db):
        wallet = _create_account(db, "Assets:Coinbase:BTC", "Assets", currency="BTC", booking_method="FIFO")
        income = _create_account(db, "Income:Mining", "Income", currency="BTC")

        txn = _make_txn([
            Posting(account_id=wallet, amount=Decimal("1.00000000"), currency="BTC"),
            Posting(account_id=income, amount=Decimal("-0.999999995"), currency="BTC"),
        ])
        validate_transaction(db, txn)

    def test_crypto_outside_tolerance(self, db):
        wallet = _create_account(db, "Assets:Coinbase:BTC", "Assets", currency="BTC", booking_method="FIFO")
        income = _create_account(db, "Income:Mining", "Income", currency="BTC")

        txn = _make_txn([
            Posting(account_id=wallet, amount=Decimal("1.00000000"), currency="BTC"),
            Posting(account_id=income, amount=Decimal("-0.9999999"), currency="BTC"),
        ])
        with pytest.raises(UnbalancedTransactionError):
            validate_transaction(db, txn)


class TestMultiCurrency:
    def test_multi_currency_price_weighted(self, db):
        usd_acct = _create_account(db, "Assets:US:Bank", "Assets", currency="USD", booking_method="FIFO")
        inr_acct = _create_account(db, "Assets:IN:Bank", "Assets", currency="INR")

        txn = _make_txn([
            Posting(
                account_id=usd_acct,
                amount=Decimal("-1000"),
                currency="USD",
                price=Decimal("83.50"),
                price_currency="INR",
            ),
            Posting(account_id=inr_acct, amount=Decimal("83500"), currency="INR"),
        ])
        validate_transaction(db, txn)

    def test_multi_currency_unbalanced(self, db):
        usd_acct = _create_account(db, "Assets:US:Bank", "Assets", currency="USD", booking_method="FIFO")
        inr_acct = _create_account(db, "Assets:IN:Bank", "Assets", currency="INR")

        txn = _make_txn([
            Posting(
                account_id=usd_acct,
                amount=Decimal("-1000"),
                currency="USD",
                price=Decimal("83.50"),
                price_currency="INR",
            ),
            Posting(account_id=inr_acct, amount=Decimal("80000"), currency="INR"),
        ])
        with pytest.raises(UnbalancedTransactionError):
            validate_transaction(db, txn)


class TestAccountChecks:
    def test_account_not_found(self, db):
        txn = _make_txn([
            Posting(account_id=9999, amount=Decimal("-50.00"), currency="USD"),
            Posting(account_id=9998, amount=Decimal("50.00"), currency="USD"),
        ])
        with pytest.raises(AccountNotFoundError):
            validate_transaction(db, txn)

    def test_account_closed(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets")
        db.execute("UPDATE accounts SET closed_at = '2024-06-01' WHERE id = ?", (checking,))
        groceries = _create_account(db, "Expenses:Groceries", "Expenses")

        txn = _make_txn([
            Posting(account_id=checking, amount=Decimal("-50.00"), currency="USD"),
            Posting(account_id=groceries, amount=Decimal("50.00"), currency="USD"),
        ])
        with pytest.raises(AccountClosedError):
            validate_transaction(db, txn)

    def test_currency_mismatch(self, db):
        checking = _create_account(db, "Assets:Chase:Checking", "Assets", currency="USD")
        groceries = _create_account(db, "Expenses:Groceries", "Expenses", currency="USD")

        txn = _make_txn([
            Posting(account_id=checking, amount=Decimal("-50.00"), currency="EUR"),
            Posting(account_id=groceries, amount=Decimal("50.00"), currency="EUR"),
        ])
        with pytest.raises(CurrencyMismatchError):
            validate_transaction(db, txn)

    def test_investment_account_allows_commodity(self, db):
        brokerage = _create_account(
            db, "Assets:Fidelity:Stocks", "Assets",
            currency="USD", booking_method="FIFO",
        )
        cash = _create_account(db, "Assets:Fidelity:Cash", "Assets", currency="USD")

        txn = _make_txn([
            Posting(
                account_id=brokerage,
                amount=Decimal("10"),
                currency="AAPL",
                price=Decimal("150.00"),
                price_currency="USD",
            ),
            Posting(account_id=cash, amount=Decimal("-1500.00"), currency="USD"),
        ])
        validate_transaction(db, txn)


class TestGetTolerances:
    def test_returns_seeded_tolerances(self, db):
        tolerances = get_tolerances(db)
        assert tolerances["USD"] == Decimal("0.01")
        assert tolerances["INR"] == Decimal("0.01")
        assert tolerances["BTC"] == Decimal("0.00000001")


class TestCheckBalance:
    def test_no_postings_passes(self, db):
        tolerances = get_tolerances(db)
        check_balance([], tolerances)

    def test_empty_raises_from_validate(self, db):
        txn = _make_txn([])
        with pytest.raises(UnbalancedTransactionError, match="no postings"):
            validate_transaction(db, txn)
