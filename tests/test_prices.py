from __future__ import annotations

import os
from decimal import Decimal

import pytest

from finkit.db import Database
from finkit.engine.prices import (
    convert_amount,
    get_best_price,
    get_latest_prices,
    get_price,
    get_price_history,
    get_price_inverse,
    record_prices_from_postings,
    store_price,
)
from finkit.models import Posting


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


def _create_transaction(db, date="2024-06-15"):
    db.execute(
        "INSERT INTO transactions (uuid, date, created_at) VALUES (?, ?, ?)",
        (os.urandom(4).hex(), date, "2024-01-01T00:00:00"),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


class TestStoreAndRetrieve:
    def test_store_and_retrieve(self, db):
        store_price(db, "AAPL", "USD", Decimal("185.50"), "2024-06-15")
        db.conn.commit()

        result = get_price(db, "AAPL", "USD", "2024-06-15")
        assert result == Decimal("185.50")

    def test_date_lookup(self, db):
        store_price(db, "AAPL", "USD", Decimal("180.00"), "2024-06-10")
        store_price(db, "AAPL", "USD", Decimal("185.50"), "2024-06-15")
        store_price(db, "AAPL", "USD", Decimal("190.00"), "2024-06-20")
        db.conn.commit()

        result = get_price(db, "AAPL", "USD", "2024-06-17")
        assert result == Decimal("185.50")


class TestInverse:
    def test_inverse_pair(self, db):
        store_price(db, "USD", "INR", Decimal("83.50"), "2024-06-15")
        db.conn.commit()

        result = get_price_inverse(db, "INR", "USD", "2024-06-15")
        assert result is not None
        expected = Decimal("1") / Decimal("83.50")
        assert result == expected


class TestBestPrice:
    def test_best_price_direct(self, db):
        store_price(db, "AAPL", "USD", Decimal("185.50"), "2024-06-15")
        db.conn.commit()

        result = get_best_price(db, "AAPL", "USD", "2024-06-15")
        assert result == Decimal("185.50")

    def test_best_price_inverse_fallback(self, db):
        store_price(db, "USD", "INR", Decimal("83.50"), "2024-06-15")
        db.conn.commit()

        result = get_best_price(db, "INR", "USD", "2024-06-15")
        assert result is not None
        expected = Decimal("1") / Decimal("83.50")
        assert result == expected


class TestConvertAmount:
    def test_convert_amount(self, db):
        store_price(db, "USD", "INR", Decimal("83.50"), "2024-06-15")
        db.conn.commit()

        result = convert_amount(db, Decimal("1000"), "USD", "INR", "2024-06-15")
        assert result == Decimal("83500.00")

    def test_convert_same_currency(self, db):
        result = convert_amount(db, Decimal("1000"), "USD", "USD", "2024-06-15")
        assert result == Decimal("1000")

    def test_missing_price(self, db):
        result = convert_amount(db, Decimal("1000"), "USD", "JPY", "2024-06-15")
        assert result is None


class TestRecordFromPostings:
    def test_record_from_postings(self, db):
        tx_id = _create_transaction(db, "2024-06-15")
        db.conn.commit()

        postings = [
            Posting(
                transaction_id=tx_id,
                account_id=1,
                amount=Decimal("-1000"),
                currency="USD",
                price=Decimal("83.50"),
                price_currency="INR",
            ),
        ]
        record_prices_from_postings(db, postings)
        db.conn.commit()

        result = get_price(db, "USD", "INR", "2024-06-15")
        assert result == Decimal("83.50")


class TestLatestPrices:
    def test_latest_prices(self, db):
        store_price(db, "AAPL", "USD", Decimal("180.00"), "2024-06-10")
        store_price(db, "AAPL", "USD", Decimal("185.50"), "2024-06-15")
        store_price(db, "AAPL", "USD", Decimal("190.00"), "2024-06-20")
        db.conn.commit()

        latest = get_latest_prices(db, "AAPL")
        assert len(latest) == 1
        assert latest[0].price == Decimal("190.00")
        assert latest[0].date == "2024-06-20"


class TestPriceHistory:
    def test_price_history(self, db):
        store_price(db, "AAPL", "USD", Decimal("180.00"), "2024-06-10")
        store_price(db, "AAPL", "USD", Decimal("185.50"), "2024-06-15")
        store_price(db, "AAPL", "USD", Decimal("190.00"), "2024-06-20")
        store_price(db, "AAPL", "USD", Decimal("188.00"), "2024-06-25")
        db.conn.commit()

        history = get_price_history(db, "AAPL", "USD", start_date="2024-06-12", end_date="2024-06-22")
        assert len(history) == 2
        assert history[0].date == "2024-06-15"
        assert history[0].price == Decimal("185.50")
        assert history[1].date == "2024-06-20"
        assert history[1].price == Decimal("190.00")
