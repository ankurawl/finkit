from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from finkit.config import Settings
from finkit.db import Database
from finkit.matching import resolve_account


_BOOKING_ORDER = {
    "FIFO": "acquired_date ASC, id ASC",
    "LIFO": "acquired_date DESC, id DESC",
    "HIFO": "cost_price DESC, id ASC",
}


def what_if_sell(
    db: Database,
    account_name: str,
    commodity: str,
    quantity: str,
    booking_method: str = "FIFO",
    sell_price: str | None = None,
    sell_date: str | None = None,
    settings: Settings | None = None,
) -> dict:
    account_id = resolve_account(db, account_name)

    sell_qty = Decimal(quantity)
    if sell_qty <= 0:
        return {
            "lots_to_sell": [],
            "total_gain_loss": "0",
            "total_proceeds": "0",
            "warnings": ["Quantity must be positive"],
        }

    order = _BOOKING_ORDER.get(booking_method)
    if order is None:
        raise ValueError(f"Unknown booking method: {booking_method}")

    rows = db.fetchall(
        f"""
        SELECT * FROM lots
        WHERE account_id = ? AND commodity = ? AND disposed = 0
              AND CAST(quantity AS REAL) > 0
        ORDER BY {order}
        """,
        (account_id, commodity),
    )

    if sell_price is not None:
        price = Decimal(sell_price)
    else:
        price_row = db.fetchone(
            """
            SELECT price FROM prices
            WHERE commodity = ? AND currency = (
                SELECT currency FROM accounts WHERE id = ?
            )
            ORDER BY date DESC LIMIT 1
            """,
            (commodity, account_id),
        )
        if price_row is None:
            return {
                "lots_to_sell": [],
                "total_gain_loss": "0",
                "total_proceeds": "0",
                "warnings": [
                    f"No price found for {commodity}. Provide sell_price explicitly."
                ],
            }
        price = Decimal(str(price_row["price"]))

    effective_sell_date = sell_date or str(date.today())
    sell_date_obj = date.fromisoformat(effective_sell_date)

    if settings is None:
        settings = Settings()

    account_row = db.fetchone(
        "SELECT jurisdiction, asset_class FROM accounts WHERE id = ?",
        (account_id,),
    )
    jurisdiction = account_row["jurisdiction"] if account_row else None
    asset_class = account_row["asset_class"] if account_row else None
    lt_threshold_days = settings.holding_period_days(jurisdiction, asset_class)

    remaining = sell_qty
    lots_to_sell: list[dict] = []
    total_gain_loss = Decimal("0")
    total_proceeds = Decimal("0")
    warnings: list[str] = []

    for row in rows:
        if remaining <= 0:
            break

        lot_qty = Decimal(str(row["quantity"]))
        consume = min(remaining, lot_qty)
        cost_price = Decimal(str(row["cost_price"]))

        proceeds = consume * price
        cost = consume * cost_price
        gain_loss = proceeds - cost

        acquired = date.fromisoformat(row["acquired_date"])
        holding_days = (sell_date_obj - acquired).days
        term = "long" if holding_days >= lt_threshold_days else "short"

        if row["lock_until"] and sell_date_obj < date.fromisoformat(row["lock_until"]):
            warnings.append(
                f"Lot {row['id']} (acquired {row['acquired_date']}) "
                f"is locked until {row['lock_until']}"
            )

        lots_to_sell.append({
            "lot_id": row["id"],
            "acquired_date": row["acquired_date"],
            "quantity_from_lot": str(consume),
            "cost_price": str(cost_price),
            "cost_currency": row["cost_currency"],
            "sell_price": str(price),
            "gain_loss": str(gain_loss),
            "term": term,
            "holding_days": holding_days,
        })

        total_gain_loss += gain_loss
        total_proceeds += proceeds
        remaining -= consume

    if remaining > 0:
        warnings.append(
            f"Insufficient lots: requested {sell_qty}, "
            f"available {sell_qty - remaining}"
        )

    return {
        "lots_to_sell": lots_to_sell,
        "total_gain_loss": str(total_gain_loss),
        "total_proceeds": str(total_proceeds),
        "warnings": warnings,
    }
