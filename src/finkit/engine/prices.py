from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.models import Posting, Price


def store_price(
    db: Database,
    commodity: str,
    currency: str,
    price: Decimal,
    date: str,
    source: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO prices (commodity, currency, price, date, source)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(commodity, currency, date) DO UPDATE SET
            price = excluded.price,
            source = excluded.source
        """,
        (commodity, currency, str(price), date, source),
    )


def get_price(
    db: Database, commodity: str, currency: str, date: str
) -> Decimal | None:
    row = db.fetchone(
        """
        SELECT price FROM prices
        WHERE commodity = ? AND currency = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (commodity, currency, date),
    )
    if row is None:
        return None
    return Decimal(str(row["price"]))


def get_price_inverse(
    db: Database, commodity: str, currency: str, date: str
) -> Decimal | None:
    direct = get_price(db, currency, commodity, date)
    if direct is None:
        return None
    return Decimal("1") / direct


def get_best_price(
    db: Database, commodity: str, currency: str, date: str
) -> Decimal | None:
    price = get_price(db, commodity, currency, date)
    if price is not None:
        return price
    return get_price_inverse(db, commodity, currency, date)


def convert_amount(
    db: Database,
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    date: str,
) -> Decimal | None:
    if from_currency == to_currency:
        return amount
    rate = get_best_price(db, from_currency, to_currency, date)
    if rate is None:
        return None
    return amount * rate


def record_prices_from_postings(db: Database, postings: list[Posting]) -> None:
    for posting in postings:
        if posting.price is not None and posting.price_currency is not None:
            store_price(
                db,
                commodity=posting.currency,
                currency=posting.price_currency,
                price=posting.price,
                date=_get_posting_date(db, posting),
                source="transaction",
            )


def _get_posting_date(db: Database, posting: Posting) -> str:
    if posting.transaction_id is None:
        return ""
    row = db.fetchone(
        "SELECT date FROM transactions WHERE id = ?",
        (posting.transaction_id,),
    )
    if row is None:
        return ""
    return row["date"]


def get_latest_prices(
    db: Database, commodity: str | None = None
) -> list[Price]:
    if commodity is not None:
        rows = db.fetchall(
            """
            SELECT p.* FROM prices p
            INNER JOIN (
                SELECT commodity, currency, MAX(date) AS max_date
                FROM prices
                WHERE commodity = ?
                GROUP BY commodity, currency
            ) latest
            ON p.commodity = latest.commodity
                AND p.currency = latest.currency
                AND p.date = latest.max_date
            ORDER BY p.commodity, p.currency
            """,
            (commodity,),
        )
    else:
        rows = db.fetchall(
            """
            SELECT p.* FROM prices p
            INNER JOIN (
                SELECT commodity, currency, MAX(date) AS max_date
                FROM prices
                GROUP BY commodity, currency
            ) latest
            ON p.commodity = latest.commodity
                AND p.currency = latest.currency
                AND p.date = latest.max_date
            ORDER BY p.commodity, p.currency
            """,
        )
    return [_row_to_price(row) for row in rows]


def get_price_history(
    db: Database,
    commodity: str,
    currency: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Price]:
    conditions = ["commodity = ?", "currency = ?"]
    params: list[str] = [commodity, currency]

    if start_date is not None:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date is not None:
        conditions.append("date <= ?")
        params.append(end_date)

    rows = db.fetchall(
        f"SELECT * FROM prices WHERE {' AND '.join(conditions)} ORDER BY date",
        tuple(params),
    )
    return [_row_to_price(row) for row in rows]


def _row_to_price(row: dict) -> Price:
    return Price(
        id=row["id"],
        commodity=row["commodity"],
        currency=row["currency"],
        price=Decimal(str(row["price"])),
        date=row["date"],
        source=row.get("source"),
    )
