from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finkit.config import Settings
    from finkit.db import Database

from finkit.models import Lot, LotDisposition


class InsufficientLotsError(Exception):
    def __init__(self, commodity: str, requested: Decimal, available: Decimal):
        self.commodity = commodity
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient lots for {commodity}: requested {requested}, available {available}"
        )


class LotNotFoundError(Exception):
    def __init__(self, lot_id: int):
        self.lot_id = lot_id
        super().__init__(f"Lot {lot_id} not found")


def _row_to_lot(row: dict) -> Lot:
    return Lot(
        id=row["id"],
        account_id=row["account_id"],
        commodity=row["commodity"],
        quantity=Decimal(str(row["quantity"])),
        original_quantity=Decimal(str(row["original_quantity"])),
        cost_price=Decimal(str(row["cost_price"])),
        cost_currency=row["cost_currency"],
        acquired_date=row["acquired_date"],
        label=row["label"],
        lock_until=row["lock_until"],
        source_transaction_id=row["source_transaction_id"],
        disposed=row["disposed"],
    )


def _row_to_disposition(row: dict) -> LotDisposition:
    return LotDisposition(
        id=row["id"],
        lot_id=row["lot_id"],
        sell_transaction_id=row["sell_transaction_id"],
        quantity=Decimal(str(row["quantity"])),
        proceeds_per_unit=Decimal(str(row["proceeds_per_unit"])),
        proceeds_currency=row["proceeds_currency"],
        gain_loss=Decimal(str(row["gain_loss"])),
        gain_loss_currency=row["gain_loss_currency"],
        term=row["term"],
        wash_sale=row["wash_sale"],
        wash_sale_adjustment=(
            Decimal(str(row["wash_sale_adjustment"]))
            if row["wash_sale_adjustment"] is not None
            else None
        ),
    )


_BOOKING_ORDER = {
    "FIFO": "l.acquired_date ASC, l.id ASC",
    "LIFO": "l.acquired_date DESC, l.id DESC",
    "HIFO": "l.cost_price DESC, l.id ASC",
}


def _select_lots_sql(booking_method: str) -> str:
    order = _BOOKING_ORDER.get(booking_method)
    if order is None:
        raise ValueError(f"Unknown booking method: {booking_method}")
    return f"""
        SELECT * FROM lots l
        WHERE l.account_id = ? AND l.commodity = ? AND l.disposed = 0
              AND CAST(l.quantity AS REAL) > 0
        ORDER BY {order}
    """


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------

def acquire_lot(
    db: Database,
    account_id: int,
    commodity: str,
    quantity: Decimal,
    cost_price: Decimal,
    cost_currency: str,
    acquired_date: str,
    source_transaction_id: int,
    label: str | None = None,
    lock_until: str | None = None,
) -> int:
    cursor = db.execute(
        """
        INSERT INTO lots
            (account_id, commodity, quantity, original_quantity, cost_price,
             cost_currency, acquired_date, label, lock_until,
             source_transaction_id, disposed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            account_id,
            commodity,
            str(quantity),
            str(quantity),
            str(cost_price),
            cost_currency,
            acquired_date,
            label,
            lock_until,
            source_transaction_id,
        ),
    )
    return cursor.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Disposition
# ---------------------------------------------------------------------------

def dispose_lots(
    db: Database,
    account_id: int,
    commodity: str,
    quantity: Decimal,
    proceeds_per_unit: Decimal,
    proceeds_currency: str,
    sell_transaction_id: int,
    booking_method: str = "FIFO",
    settings: Settings | None = None,
) -> list[LotDisposition]:
    sql = _select_lots_sql(booking_method)
    rows = db.fetchall(sql, (account_id, commodity))
    lots = [_row_to_lot(r) for r in rows]

    available = sum(lot.quantity for lot in lots)
    if available < quantity:
        raise InsufficientLotsError(commodity, quantity, available)

    account_row = db.fetchone("SELECT * FROM accounts WHERE id = ?", (account_id,))
    jurisdiction = account_row["jurisdiction"] if account_row else None
    asset_class = account_row["asset_class"] if account_row else None

    sell_txn = db.fetchone("SELECT date FROM transactions WHERE id = ?", (sell_transaction_id,))
    sell_date_str = sell_txn["date"] if sell_txn else ""

    remaining = quantity
    dispositions: list[LotDisposition] = []

    for lot in lots:
        if remaining <= Decimal("0"):
            break

        consume = min(lot.quantity, remaining)
        gain_loss = (proceeds_per_unit - lot.cost_price) * consume

        term = classify_holding_period(
            lot.acquired_date, sell_date_str, jurisdiction, asset_class, settings,
        )

        cursor = db.execute(
            """
            INSERT INTO lot_dispositions
                (lot_id, sell_transaction_id, quantity, proceeds_per_unit,
                 proceeds_currency, gain_loss, gain_loss_currency, term,
                 wash_sale, wash_sale_adjustment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
            """,
            (
                lot.id,
                sell_transaction_id,
                str(consume),
                str(proceeds_per_unit),
                proceeds_currency,
                str(gain_loss),
                proceeds_currency,
                term,
            ),
        )
        disp_id = cursor.lastrowid

        new_qty = lot.quantity - consume
        disposed_flag = 1 if new_qty <= Decimal("0") else 0
        db.execute(
            "UPDATE lots SET quantity = ?, disposed = ? WHERE id = ?",
            (str(new_qty), disposed_flag, lot.id),
        )

        disp = LotDisposition(
            id=disp_id,
            lot_id=lot.id,  # type: ignore[arg-type]
            sell_transaction_id=sell_transaction_id,
            quantity=consume,
            proceeds_per_unit=proceeds_per_unit,
            proceeds_currency=proceeds_currency,
            gain_loss=gain_loss,
            gain_loss_currency=proceeds_currency,
            term=term,
            wash_sale=0,
            wash_sale_adjustment=None,
        )

        is_wash, adjustment = check_wash_sale(db, account_id, commodity, sell_date_str, gain_loss)
        if is_wash and adjustment is not None:
            db.execute(
                "UPDATE lot_dispositions SET wash_sale = 1, wash_sale_adjustment = ? WHERE id = ?",
                (str(adjustment), disp_id),
            )
            disp.wash_sale = 1
            disp.wash_sale_adjustment = adjustment

        dispositions.append(disp)
        remaining -= consume

    return dispositions


# ---------------------------------------------------------------------------
# Holding period
# ---------------------------------------------------------------------------

def classify_holding_period(
    acquired_date: str,
    sell_date: str,
    jurisdiction: str | None,
    asset_class: str | None,
    settings: Settings | None,
) -> str:
    acq = date.fromisoformat(acquired_date)
    sell = date.fromisoformat(sell_date)
    held_days = (sell - acq).days

    if settings is not None:
        threshold = settings.holding_period_days(jurisdiction, asset_class)
    else:
        from finkit.config import _DEFAULT_HOLDING_PERIODS
        key = f"{jurisdiction}.{asset_class}" if jurisdiction and asset_class else ""
        threshold = _DEFAULT_HOLDING_PERIODS.get(key, 365)

    return "long" if held_days > threshold else "short"


# ---------------------------------------------------------------------------
# Wash sale detection
# ---------------------------------------------------------------------------

def check_wash_sale(
    db: Database,
    account_id: int,
    commodity: str,
    sell_date: str,
    gain_loss: Decimal,
) -> tuple[bool, Decimal | None]:
    if gain_loss >= Decimal("0"):
        return (False, None)

    sd = date.fromisoformat(sell_date)
    window_start = (sd - timedelta(days=30)).isoformat()
    window_end = (sd + timedelta(days=30)).isoformat()

    rows = db.fetchall(
        """
        SELECT l.id FROM lots l
        JOIN transactions t ON l.source_transaction_id = t.id
        WHERE l.account_id = ?
          AND l.commodity = ?
          AND l.acquired_date >= ?
          AND l.acquired_date <= ?
          AND l.acquired_date != ?
        LIMIT 1
        """,
        (account_id, commodity, window_start, window_end, sell_date),
    )

    if rows:
        adjustment = abs(gain_loss)
        return (True, adjustment)

    return (False, None)


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------

def corporate_action(
    db: Database,
    commodity: str,
    action_type: str,
    ratio: Decimal,
) -> int:
    valid_types = ("split", "reverse_split", "bonus")
    if action_type not in valid_types:
        raise ValueError(f"Invalid action_type: {action_type}. Must be one of {valid_types}")

    if ratio <= Decimal("0"):
        raise ValueError(f"Ratio must be positive, got {ratio}")

    rows = db.fetchall(
        "SELECT * FROM lots WHERE commodity = ? AND disposed = 0",
        (commodity,),
    )
    lots = [_row_to_lot(r) for r in rows]

    for lot in lots:
        if action_type in ("split", "bonus"):
            new_qty = lot.quantity * ratio
            new_orig_qty = lot.original_quantity * ratio
            new_cost = lot.cost_price / ratio
        else:  # reverse_split
            new_qty = lot.quantity / ratio
            new_orig_qty = lot.original_quantity / ratio
            new_cost = lot.cost_price * ratio

        db.execute(
            """
            UPDATE lots
            SET quantity = ?, original_quantity = ?, cost_price = ?
            WHERE id = ?
            """,
            (str(new_qty), str(new_orig_qty), str(new_cost), lot.id),
        )

    return len(lots)


# ---------------------------------------------------------------------------
# Lot transfer
# ---------------------------------------------------------------------------

def transfer_lots(
    db: Database,
    from_account_id: int,
    to_account_id: int,
    commodity: str,
    quantity: Decimal,
    booking_method: str = "FIFO",
) -> list[int]:
    sql = _select_lots_sql(booking_method)
    rows = db.fetchall(sql, (from_account_id, commodity))
    lots = [_row_to_lot(r) for r in rows]

    available = sum(lot.quantity for lot in lots)
    if available < quantity:
        raise InsufficientLotsError(commodity, quantity, available)

    remaining = quantity
    new_lot_ids: list[int] = []

    for lot in lots:
        if remaining <= Decimal("0"):
            break

        transfer_qty = min(lot.quantity, remaining)

        if transfer_qty == lot.quantity:
            # Transfer the entire lot by updating the account
            db.execute(
                "UPDATE lots SET account_id = ? WHERE id = ?",
                (to_account_id, lot.id),
            )
            new_lot_ids.append(lot.id)  # type: ignore[arg-type]
        else:
            # Partial transfer: reduce source lot, create new lot in destination
            new_source_qty = lot.quantity - transfer_qty
            db.execute(
                "UPDATE lots SET quantity = ? WHERE id = ?",
                (str(new_source_qty), lot.id),
            )

            cursor = db.execute(
                """
                INSERT INTO lots
                    (account_id, commodity, quantity, original_quantity, cost_price,
                     cost_currency, acquired_date, label, lock_until,
                     source_transaction_id, disposed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    to_account_id,
                    lot.commodity,
                    str(transfer_qty),
                    str(transfer_qty),
                    str(lot.cost_price),
                    lot.cost_currency,
                    lot.acquired_date,
                    lot.label,
                    lot.lock_until,
                    lot.source_transaction_id,
                ),
            )
            new_lot_ids.append(cursor.lastrowid)  # type: ignore[arg-type]

        remaining -= transfer_qty

    return new_lot_ids


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

def rebuild_lots(db: Database) -> None:
    db.execute("UPDATE lots SET quantity = original_quantity, disposed = 0")

    dispositions = db.fetchall(
        """
        SELECT ld.* FROM lot_dispositions ld
        JOIN transactions t ON ld.sell_transaction_id = t.id
        ORDER BY t.date ASC, ld.id ASC
        """
    )

    for row in dispositions:
        lot_id = row["lot_id"]
        disp_qty = Decimal(str(row["quantity"]))

        lot_row = db.fetchone("SELECT * FROM lots WHERE id = ?", (lot_id,))
        if lot_row is None:
            continue

        current_qty = Decimal(str(lot_row["quantity"]))
        new_qty = current_qty - disp_qty
        disposed_flag = 1 if new_qty <= Decimal("0") else 0

        db.execute(
            "UPDATE lots SET quantity = ?, disposed = ? WHERE id = ?",
            (str(new_qty), disposed_flag, lot_id),
        )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_lots(
    db: Database,
    account_id: int,
    commodity: str,
    include_disposed: bool = False,
) -> list[Lot]:
    if include_disposed:
        rows = db.fetchall(
            "SELECT * FROM lots WHERE account_id = ? AND commodity = ? ORDER BY acquired_date, id",
            (account_id, commodity),
        )
    else:
        rows = db.fetchall(
            """
            SELECT * FROM lots
            WHERE account_id = ? AND commodity = ? AND disposed = 0
            ORDER BY acquired_date, id
            """,
            (account_id, commodity),
        )
    return [_row_to_lot(r) for r in rows]


def get_lot_dispositions(
    db: Database,
    sell_transaction_id: int | None = None,
    lot_id: int | None = None,
) -> list[LotDisposition]:
    if sell_transaction_id is not None and lot_id is not None:
        rows = db.fetchall(
            "SELECT * FROM lot_dispositions WHERE sell_transaction_id = ? AND lot_id = ? ORDER BY id",
            (sell_transaction_id, lot_id),
        )
    elif sell_transaction_id is not None:
        rows = db.fetchall(
            "SELECT * FROM lot_dispositions WHERE sell_transaction_id = ? ORDER BY id",
            (sell_transaction_id,),
        )
    elif lot_id is not None:
        rows = db.fetchall(
            "SELECT * FROM lot_dispositions WHERE lot_id = ? ORDER BY id",
            (lot_id,),
        )
    else:
        rows = db.fetchall("SELECT * FROM lot_dispositions ORDER BY id")

    return [_row_to_disposition(r) for r in rows]
