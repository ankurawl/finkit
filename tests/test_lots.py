from __future__ import annotations

import os
from decimal import Decimal

import pytest

from finkit.config import Settings
from finkit.db import Database
from finkit.engine.lots import (
    InsufficientLotsError,
    acquire_lot,
    check_wash_sale,
    classify_holding_period,
    corporate_action,
    dispose_lots,
    get_lots,
    rebuild_lots,
    transfer_lots,
)


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


class TestAcquireLot:
    def test_acquire_lot(self, db):
        acct = _create_account(db, "Assets:Fidelity:Stocks", "Assets", booking_method="FIFO")
        tx = _create_transaction(db, "2024-01-15")

        lot_id = acquire_lot(
            db,
            account_id=acct,
            commodity="AAPL",
            quantity=Decimal("10"),
            cost_price=Decimal("150.00"),
            cost_currency="USD",
            acquired_date="2024-01-15",
            source_transaction_id=tx,
        )

        lots = get_lots(db, acct, "AAPL")
        assert len(lots) == 1
        lot = lots[0]
        assert lot.id == lot_id
        assert lot.quantity == Decimal("10")
        assert lot.original_quantity == Decimal("10")
        assert lot.cost_price == Decimal("150.00")
        assert lot.cost_currency == "USD"
        assert lot.disposed == 0


class TestDispositionOrder:
    @pytest.fixture
    def three_lots(self, db):
        acct = _create_account(
            db, "Assets:Fidelity:Stocks", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx1 = _create_transaction(db, "2023-01-10")
        tx2 = _create_transaction(db, "2023-06-15")
        tx3 = _create_transaction(db, "2023-12-20")

        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("100.00"), "USD", "2023-01-10", tx1)
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("130.00"), "USD", "2023-06-15", tx2)
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("120.00"), "USD", "2023-12-20", tx3)
        db.conn.commit()
        return acct

    def test_fifo_disposition(self, db, three_lots):
        sell_tx = _create_transaction(db, "2024-06-15")
        dispositions = dispose_lots(
            db, three_lots, "AAPL", Decimal("15"),
            Decimal("160.00"), "USD", sell_tx, booking_method="FIFO",
        )

        assert len(dispositions) == 2
        assert dispositions[0].quantity == Decimal("10")
        assert dispositions[0].gain_loss == Decimal("600.00")
        assert dispositions[1].quantity == Decimal("5")
        assert dispositions[1].gain_loss == Decimal("150.00")

    def test_lifo_disposition(self, db, three_lots):
        sell_tx = _create_transaction(db, "2024-06-15")
        dispositions = dispose_lots(
            db, three_lots, "AAPL", Decimal("15"),
            Decimal("160.00"), "USD", sell_tx, booking_method="LIFO",
        )

        assert len(dispositions) == 2
        assert dispositions[0].quantity == Decimal("10")
        assert dispositions[0].gain_loss == Decimal("400.00")
        assert dispositions[1].quantity == Decimal("5")
        assert dispositions[1].gain_loss == Decimal("150.00")

    def test_hifo_disposition(self, db, three_lots):
        sell_tx = _create_transaction(db, "2024-06-15")
        dispositions = dispose_lots(
            db, three_lots, "AAPL", Decimal("15"),
            Decimal("160.00"), "USD", sell_tx, booking_method="HIFO",
        )

        assert len(dispositions) == 2
        assert dispositions[0].quantity == Decimal("10")
        assert dispositions[0].gain_loss == Decimal("300.00")
        assert dispositions[1].quantity == Decimal("5")
        assert dispositions[1].gain_loss == Decimal("200.00")

    def test_same_day_tiebreaker(self, db):
        acct = _create_account(
            db, "Assets:Brokerage", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx1 = _create_transaction(db, "2023-06-15")
        tx2 = _create_transaction(db, "2023-06-15")

        id1 = acquire_lot(db, acct, "MSFT", Decimal("10"), Decimal("300.00"), "USD", "2023-06-15", tx1)
        id2 = acquire_lot(db, acct, "MSFT", Decimal("10"), Decimal("310.00"), "USD", "2023-06-15", tx2)
        db.conn.commit()

        sell_tx = _create_transaction(db, "2024-06-15")
        dispositions = dispose_lots(
            db, acct, "MSFT", Decimal("5"),
            Decimal("350.00"), "USD", sell_tx, booking_method="FIFO",
        )

        assert len(dispositions) == 1
        assert dispositions[0].lot_id == id1


class TestPartialAndFullConsumption:
    def test_partial_consumption(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx = _create_transaction(db, "2023-01-10")
        acquire_lot(db, acct, "AAPL", Decimal("100"), Decimal("150.00"), "USD", "2023-01-10", tx)
        db.conn.commit()

        sell_tx = _create_transaction(db, "2024-06-15")
        dispose_lots(
            db, acct, "AAPL", Decimal("60"),
            Decimal("180.00"), "USD", sell_tx, booking_method="FIFO",
        )

        lots = get_lots(db, acct, "AAPL")
        assert len(lots) == 1
        assert lots[0].quantity == Decimal("40")
        assert lots[0].disposed == 0

    def test_full_consumption(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx = _create_transaction(db, "2023-01-10")
        acquire_lot(db, acct, "AAPL", Decimal("100"), Decimal("150.00"), "USD", "2023-01-10", tx)
        db.conn.commit()

        sell_tx = _create_transaction(db, "2024-06-15")
        dispose_lots(
            db, acct, "AAPL", Decimal("100"),
            Decimal("180.00"), "USD", sell_tx, booking_method="FIFO",
        )

        lots = get_lots(db, acct, "AAPL", include_disposed=True)
        assert len(lots) == 1
        assert lots[0].quantity == Decimal("0")
        assert lots[0].disposed == 1

        active_lots = get_lots(db, acct, "AAPL")
        assert len(active_lots) == 0


class TestInsufficientLots:
    def test_insufficient_lots(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx = _create_transaction(db, "2023-01-10")
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("150.00"), "USD", "2023-01-10", tx)
        db.conn.commit()

        sell_tx = _create_transaction(db, "2024-06-15")
        with pytest.raises(InsufficientLotsError) as exc_info:
            dispose_lots(
                db, acct, "AAPL", Decimal("20"),
                Decimal("180.00"), "USD", sell_tx, booking_method="FIFO",
            )
        assert exc_info.value.commodity == "AAPL"
        assert exc_info.value.requested == Decimal("20")
        assert exc_info.value.available == Decimal("10")


class TestGainLoss:
    def test_gain_calculation(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx = _create_transaction(db, "2023-01-10")
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("100.00"), "USD", "2023-01-10", tx)
        db.conn.commit()

        sell_tx = _create_transaction(db, "2024-06-15")
        dispositions = dispose_lots(
            db, acct, "AAPL", Decimal("10"),
            Decimal("150.00"), "USD", sell_tx, booking_method="FIFO",
        )

        assert len(dispositions) == 1
        assert dispositions[0].gain_loss == Decimal("500.00")

    def test_loss_calculation(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx = _create_transaction(db, "2023-01-10")
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("150.00"), "USD", "2023-01-10", tx)
        db.conn.commit()

        sell_tx = _create_transaction(db, "2024-06-15")
        dispositions = dispose_lots(
            db, acct, "AAPL", Decimal("10"),
            Decimal("100.00"), "USD", sell_tx, booking_method="FIFO",
        )

        assert len(dispositions) == 1
        assert dispositions[0].gain_loss == Decimal("-500.00")


class TestHoldingPeriod:
    def test_short_term_us_equity(self):
        settings = Settings()
        term = classify_holding_period("2024-01-15", "2024-07-15", "US", "equity", settings)
        assert term == "short"

    def test_long_term_us_equity(self):
        settings = Settings()
        term = classify_holding_period("2022-01-15", "2024-06-15", "US", "equity", settings)
        assert term == "long"

    def test_india_debt_short_at_2_years(self):
        settings = Settings()
        term = classify_holding_period("2022-01-15", "2024-01-20", "IN", "debt", settings)
        assert term == "short"

    def test_india_debt_long_at_3_years(self):
        settings = Settings()
        term = classify_holding_period("2021-01-15", "2024-06-15", "IN", "debt", settings)
        assert term == "long"


class TestWashSale:
    def test_wash_sale_detected(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        buy_tx = _create_transaction(db, "2024-06-01")
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("150.00"), "USD", "2024-06-01", buy_tx)

        repurchase_tx = _create_transaction(db, "2024-06-20")
        acquire_lot(db, acct, "AAPL", Decimal("5"), Decimal("140.00"), "USD", "2024-06-20", repurchase_tx)
        db.conn.commit()

        is_wash, adjustment = check_wash_sale(
            db, acct, "AAPL", "2024-06-15", Decimal("-100.00"),
        )
        assert is_wash is True
        assert adjustment == Decimal("100.00")

    def test_no_wash_sale_on_gain(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        buy_tx = _create_transaction(db, "2024-06-01")
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("150.00"), "USD", "2024-06-01", buy_tx)

        repurchase_tx = _create_transaction(db, "2024-06-20")
        acquire_lot(db, acct, "AAPL", Decimal("5"), Decimal("170.00"), "USD", "2024-06-20", repurchase_tx)
        db.conn.commit()

        is_wash, adjustment = check_wash_sale(
            db, acct, "AAPL", "2024-06-15", Decimal("200.00"),
        )
        assert is_wash is False
        assert adjustment is None


class TestCorporateAction:
    def test_split(self, db):
        acct = _create_account(db, "Assets:Fidelity", "Assets", booking_method="FIFO")
        tx = _create_transaction(db, "2023-01-10")
        acquire_lot(db, acct, "AAPL", Decimal("10"), Decimal("400.00"), "USD", "2023-01-10", tx)
        db.conn.commit()

        count = corporate_action(db, "AAPL", "split", Decimal("4"))

        assert count == 1
        lots = get_lots(db, acct, "AAPL")
        assert lots[0].quantity == Decimal("40")
        assert lots[0].original_quantity == Decimal("40")
        assert lots[0].cost_price == Decimal("100.00")


class TestTransferLots:
    def test_lot_transfer(self, db):
        acct_a = _create_account(db, "Assets:Fidelity", "Assets", booking_method="FIFO")
        acct_b = _create_account(db, "Assets:Schwab", "Assets", booking_method="FIFO")
        tx = _create_transaction(db, "2023-01-10")

        acquire_lot(db, acct_a, "AAPL", Decimal("20"), Decimal("150.00"), "USD", "2023-01-10", tx)
        db.conn.commit()

        new_ids = transfer_lots(db, acct_a, acct_b, "AAPL", Decimal("20"))

        assert len(new_ids) == 1
        lots_a = get_lots(db, acct_a, "AAPL")
        lots_b = get_lots(db, acct_b, "AAPL")
        assert len(lots_a) == 0
        assert len(lots_b) == 1
        assert lots_b[0].cost_price == Decimal("150.00")
        assert lots_b[0].quantity == Decimal("20")


class TestRebuild:
    def test_rebuild_idempotent(self, db):
        acct = _create_account(
            db, "Assets:Fidelity", "Assets",
            booking_method="FIFO", jurisdiction="US", asset_class="equity",
        )
        tx1 = _create_transaction(db, "2023-01-10")
        acquire_lot(db, acct, "AAPL", Decimal("20"), Decimal("150.00"), "USD", "2023-01-10", tx1)
        db.conn.commit()

        sell_tx = _create_transaction(db, "2024-06-15")
        dispose_lots(
            db, acct, "AAPL", Decimal("10"),
            Decimal("180.00"), "USD", sell_tx, booking_method="FIFO",
        )
        db.conn.commit()

        lots_before = get_lots(db, acct, "AAPL", include_disposed=True)

        rebuild_lots(db)
        lots_after_1 = get_lots(db, acct, "AAPL", include_disposed=True)

        rebuild_lots(db)
        lots_after_2 = get_lots(db, acct, "AAPL", include_disposed=True)

        for before, after1, after2 in zip(lots_before, lots_after_1, lots_after_2):
            assert before.quantity == after1.quantity == after2.quantity
            assert before.disposed == after1.disposed == after2.disposed
