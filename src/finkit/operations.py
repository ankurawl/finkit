from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from finkit.config import Settings
from finkit.db import Database
from finkit.engine.balances import assert_balance as _assert_balance
from finkit.engine.lots import acquire_lot, corporate_action as _corporate_action, dispose_lots
from finkit.engine.prices import record_prices_from_postings
from finkit.engine.validation import AccountNotFoundError, validate_transaction
from finkit.matching import resolve_account
from finkit.models import Posting, Transaction
from finkit.summaries.registry import RefreshContext, registry

_VALID_ROOT_TYPES = frozenset({"Assets", "Liabilities", "Income", "Expenses", "Equity"})

_DEFAULT_TOLERANCES = {
    "USD": "0.01",
    "INR": "0.01",
    "EUR": "0.01",
    "GBP": "0.01",
    "BTC": "0.00000001",
    "ETH": "0.00000001",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _generate_uuid() -> str:
    return os.urandom(4).hex()


# ---------------------------------------------------------------------------
# init_ledger
# ---------------------------------------------------------------------------

def init_ledger(settings: Settings) -> Database:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.statements_dir.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)

    db = Database(settings.db_path)

    if settings.db_path.exists():
        db.connect()
        return db

    db.connect()
    db.create_schema()

    with db.transaction():
        for currency, tolerance in _DEFAULT_TOLERANCES.items():
            db.execute(
                "INSERT OR IGNORE INTO currency_tolerances (currency, tolerance) VALUES (?, ?)",
                (currency, tolerance),
            )

        now = _now_iso()
        db.execute(
            "INSERT OR IGNORE INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
            ("Equity:OpeningBalances", "Equity", "USD", now),
        )

        registry.create_tables(db)

    return db


# ---------------------------------------------------------------------------
# open_account
# ---------------------------------------------------------------------------

def open_account(
    db: Database,
    name: str,
    type: str,
    currency: str = "USD",
    booking_method: str | None = None,
    institution: str | None = None,
    asset_class: str | None = None,
    jurisdiction: str | None = None,
    opened_at: str | None = None,
) -> int:
    segments = name.split(":")
    if len(segments) < 2:
        raise ValueError(f"Account name must be colon-separated with at least two segments: {name}")

    root = segments[0]
    if root not in _VALID_ROOT_TYPES:
        raise ValueError(
            f"First segment must be one of {sorted(_VALID_ROOT_TYPES)}, got '{root}'"
        )

    if type != root:
        raise ValueError(
            f"Account type '{type}' does not match first segment '{root}'"
        )

    if opened_at is None:
        opened_at = _now_iso()

    cursor = db.execute(
        """
        INSERT INTO accounts (name, type, currency, booking_method, institution,
                              asset_class, jurisdiction, opened_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, type, currency, booking_method, institution, asset_class, jurisdiction, opened_at),
    )
    return cursor.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# submit_transaction
# ---------------------------------------------------------------------------

def submit_transaction(
    db: Database,
    date: str,
    postings: list[dict],
    payee: str | None = None,
    narration: str | None = None,
    tags: list[str] | None = None,
    status: str = "cleared",
    settings: Settings | None = None,
) -> str:
    uuid = _generate_uuid()
    now = _now_iso()

    posting_objs: list[Posting] = []
    for p in postings:
        account_id = resolve_account(db, p["account"])
        amount = Decimal(str(p["amount"]))
        currency = p.get("currency", "USD")

        price = Decimal(str(p["price"])) if p.get("price") is not None else None
        price_currency = p.get("price_currency")
        cost_amount = Decimal(str(p["cost_amount"])) if p.get("cost_amount") is not None else None
        cost_currency = p.get("cost_currency")
        cost_date = p.get("cost_date")

        posting_objs.append(Posting(
            account_id=account_id,
            account_name=p["account"],
            amount=amount,
            currency=currency,
            price=price,
            price_currency=price_currency,
            cost_amount=cost_amount,
            cost_currency=cost_currency,
            cost_date=cost_date,
        ))

    txn = Transaction(
        uuid=uuid,
        date=date,
        payee=payee,
        narration=narration,
        status=status,
        created_at=now,
        postings=posting_objs,
        tags=tags or [],
    )

    validate_transaction(db, txn)

    with db.transaction():
        cursor = db.execute(
            """
            INSERT INTO transactions (uuid, date, payee, narration, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uuid, date, payee, narration, status, now),
        )
        txn_id = cursor.lastrowid

        affected_account_ids: set[int] = set()

        for i, posting in enumerate(posting_objs):
            posting.transaction_id = txn_id
            lot_id = None

            acct_row = db.fetchone(
                "SELECT booking_method, jurisdiction, asset_class FROM accounts WHERE id = ?",
                (posting.account_id,),
            )
            booking_method = acct_row["booking_method"] if acct_row else None

            if booking_method and posting.amount > Decimal("0"):
                cost_price = posting.cost_amount or posting.price or Decimal("0")
                cost_cur = posting.cost_currency or posting.price_currency or "USD"
                lot_id = acquire_lot(
                    db,
                    account_id=posting.account_id,
                    commodity=posting.currency,
                    quantity=posting.amount,
                    cost_price=cost_price,
                    cost_currency=cost_cur,
                    acquired_date=date,
                    source_transaction_id=txn_id,
                    label=postings[i].get("lot_label"),
                    lock_until=postings[i].get("lock_until"),
                )

            cursor = db.execute(
                """
                INSERT INTO postings
                    (transaction_id, account_id, amount, currency,
                     cost_amount, cost_currency, cost_date,
                     price, price_currency, lot_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    txn_id,
                    posting.account_id,
                    str(posting.amount),
                    posting.currency,
                    str(posting.cost_amount) if posting.cost_amount is not None else None,
                    posting.cost_currency,
                    posting.cost_date,
                    str(posting.price) if posting.price is not None else None,
                    posting.price_currency,
                    lot_id,
                ),
            )
            posting.id = cursor.lastrowid

            if booking_method and posting.amount < Decimal("0"):
                sell_qty = abs(posting.amount)
                proceeds = posting.price or Decimal("0")
                proceeds_cur = posting.price_currency or "USD"
                dispose_lots(
                    db,
                    account_id=posting.account_id,
                    commodity=posting.currency,
                    quantity=sell_qty,
                    proceeds_per_unit=proceeds,
                    proceeds_currency=proceeds_cur,
                    sell_transaction_id=txn_id,
                    booking_method=booking_method,
                    settings=settings,
                )

            affected_account_ids.add(posting.account_id)

        record_prices_from_postings(db, posting_objs)

        if tags:
            for tag in tags:
                db.execute(
                    "INSERT INTO transaction_tags (transaction_id, tag) VALUES (?, ?)",
                    (txn_id, tag),
                )

        context = RefreshContext(
            affected_account_ids=affected_account_ids,
            affected_date_range=(date, date),
            affected_commodities={p.currency for p in posting_objs},
        )
        registry.refresh_all(db, context)

    return uuid


# ---------------------------------------------------------------------------
# amend_transaction
# ---------------------------------------------------------------------------

def amend_transaction(
    db: Database,
    uuid: str,
    updates: dict | None = None,
    delete: bool = False,
    settings: Settings | None = None,
) -> None:
    txn_row = db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    if txn_row is None:
        raise ValueError(f"Transaction with uuid '{uuid}' not found")

    txn_id = txn_row["id"]

    existing_postings = db.fetchall(
        "SELECT * FROM postings WHERE transaction_id = ?", (txn_id,)
    )
    affected_account_ids = {p["account_id"] for p in existing_postings}
    affected_commodities = {p["currency"] for p in existing_postings}
    old_date = txn_row["date"]

    with db.transaction():
        _undo_lot_effects(db, txn_id)

        if delete:
            db.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))

            context = RefreshContext(
                affected_account_ids=affected_account_ids,
                affected_date_range=(old_date, old_date),
                affected_commodities=affected_commodities,
            )
            registry.refresh_all(db, context)
            return

        if updates is None:
            return

        now = _now_iso()
        new_date = updates.get("date", old_date)

        if "date" in updates:
            db.execute("UPDATE transactions SET date = ?, modified_at = ? WHERE id = ?",
                       (updates["date"], now, txn_id))
        if "payee" in updates:
            db.execute("UPDATE transactions SET payee = ?, modified_at = ? WHERE id = ?",
                       (updates["payee"], now, txn_id))
        if "narration" in updates:
            db.execute("UPDATE transactions SET narration = ?, modified_at = ? WHERE id = ?",
                       (updates["narration"], now, txn_id))
        if "status" in updates:
            db.execute("UPDATE transactions SET status = ?, modified_at = ? WHERE id = ?",
                       (updates["status"], now, txn_id))

        if "postings" in updates:
            db.execute("DELETE FROM postings WHERE transaction_id = ?", (txn_id,))

            new_posting_objs: list[Posting] = []
            for p in updates["postings"]:
                account_id = resolve_account(db, p["account"])
                amount = Decimal(str(p["amount"]))
                currency = p.get("currency", "USD")
                price = Decimal(str(p["price"])) if p.get("price") is not None else None
                price_currency = p.get("price_currency")
                cost_amount = Decimal(str(p["cost_amount"])) if p.get("cost_amount") is not None else None
                cost_currency = p.get("cost_currency")
                cost_date = p.get("cost_date")

                new_posting_objs.append(Posting(
                    account_id=account_id,
                    account_name=p["account"],
                    amount=amount,
                    currency=currency,
                    price=price,
                    price_currency=price_currency,
                    cost_amount=cost_amount,
                    cost_currency=cost_currency,
                    cost_date=cost_date,
                ))

            new_txn = Transaction(
                uuid=uuid,
                date=new_date,
                postings=new_posting_objs,
            )
            validate_transaction(db, new_txn)

            for i, posting in enumerate(new_posting_objs):
                posting.transaction_id = txn_id
                lot_id = None

                acct_row = db.fetchone(
                    "SELECT booking_method FROM accounts WHERE id = ?",
                    (posting.account_id,),
                )
                booking_method = acct_row["booking_method"] if acct_row else None

                if booking_method and posting.amount > Decimal("0"):
                    cost_price = posting.cost_amount or posting.price or Decimal("0")
                    cost_cur = posting.cost_currency or posting.price_currency or "USD"
                    lot_id = acquire_lot(
                        db,
                        account_id=posting.account_id,
                        commodity=posting.currency,
                        quantity=posting.amount,
                        cost_price=cost_price,
                        cost_currency=cost_cur,
                        acquired_date=new_date,
                        source_transaction_id=txn_id,
                        label=updates["postings"][i].get("lot_label"),
                        lock_until=updates["postings"][i].get("lock_until"),
                    )

                db.execute(
                    """
                    INSERT INTO postings
                        (transaction_id, account_id, amount, currency,
                         cost_amount, cost_currency, cost_date,
                         price, price_currency, lot_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        txn_id,
                        posting.account_id,
                        str(posting.amount),
                        posting.currency,
                        str(posting.cost_amount) if posting.cost_amount is not None else None,
                        posting.cost_currency,
                        posting.cost_date,
                        str(posting.price) if posting.price is not None else None,
                        posting.price_currency,
                        lot_id,
                    ),
                )

                if booking_method and posting.amount < Decimal("0"):
                    sell_qty = abs(posting.amount)
                    proceeds = posting.price or Decimal("0")
                    proceeds_cur = posting.price_currency or "USD"
                    dispose_lots(
                        db,
                        account_id=posting.account_id,
                        commodity=posting.currency,
                        quantity=sell_qty,
                        proceeds_per_unit=proceeds,
                        proceeds_currency=proceeds_cur,
                        sell_transaction_id=txn_id,
                        booking_method=booking_method,
                        settings=settings,
                    )

                affected_account_ids.add(posting.account_id)
                affected_commodities.add(posting.currency)

            record_prices_from_postings(db, new_posting_objs)

        min_date = min(old_date, new_date)
        max_date = max(old_date, new_date)

        context = RefreshContext(
            affected_account_ids=affected_account_ids,
            affected_date_range=(min_date, max_date),
            affected_commodities=affected_commodities,
        )
        registry.refresh_all(db, context)


def _undo_lot_effects(db: Database, txn_id: int) -> None:
    dispositions = db.fetchall(
        "SELECT * FROM lot_dispositions WHERE sell_transaction_id = ?",
        (txn_id,),
    )
    for disp in dispositions:
        lot_row = db.fetchone("SELECT * FROM lots WHERE id = ?", (disp["lot_id"],))
        if lot_row is not None:
            restored_qty = Decimal(str(lot_row["quantity"])) + Decimal(str(disp["quantity"]))
            db.execute(
                "UPDATE lots SET quantity = ?, disposed = 0 WHERE id = ?",
                (str(restored_qty), disp["lot_id"]),
            )
    db.execute(
        "DELETE FROM lot_dispositions WHERE sell_transaction_id = ?",
        (txn_id,),
    )

    db.execute(
        "DELETE FROM lots WHERE source_transaction_id = ?",
        (txn_id,),
    )


# ---------------------------------------------------------------------------
# assert_balance
# ---------------------------------------------------------------------------

def assert_balance(
    db: Database,
    account_name: str,
    date: str,
    expected_amount: str,
    currency: str = "USD",
) -> dict:
    account_id = resolve_account(db, account_name)
    result = _assert_balance(
        db,
        account_id=account_id,
        date=date,
        expected_amount=Decimal(expected_amount),
        currency=currency,
    )
    return {
        "id": result.id,
        "account_id": result.account_id,
        "date": result.date,
        "expected_amount": str(result.expected_amount),
        "actual_amount": str(result.actual_amount),
        "currency": result.currency,
        "matches": result.matches,
        "difference": str(result.difference) if result.difference is not None else None,
        "asserted_at": result.asserted_at,
    }


# ---------------------------------------------------------------------------
# corporate_action
# ---------------------------------------------------------------------------

def corporate_action(
    db: Database,
    commodity: str,
    action_type: str,
    ratio: str,
    date: str | None = None,
    narration: str | None = None,
) -> dict:
    ratio_dec = Decimal(ratio)

    with db.transaction():
        affected_count = _corporate_action(db, commodity, action_type, ratio_dec)

        if date is not None:
            uuid = _generate_uuid()
            now = _now_iso()
            desc = narration or f"{action_type} {commodity} ratio {ratio}"
            db.execute(
                """
                INSERT INTO transactions (uuid, date, payee, narration, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uuid, date, None, desc, "cleared", now),
            )

        context = RefreshContext(
            affected_commodities={commodity},
        )
        registry.refresh_all(db, context)

    return {"affected_lots": affected_count}


# ---------------------------------------------------------------------------
# undo_import
# ---------------------------------------------------------------------------

def undo_import(db: Database, source_file_id: int) -> dict:
    txn_rows = db.fetchall(
        "SELECT * FROM transactions WHERE source_file_id = ?",
        (source_file_id,),
    )

    if not txn_rows:
        db.execute("DELETE FROM raw_extractions WHERE source_file_id = ?", (source_file_id,))
        return {"deleted_transactions": 0}

    txn_ids = [r["id"] for r in txn_rows]

    affected_account_ids: set[int] = set()
    affected_commodities: set[str] = set()
    dates: list[str] = []

    for txn_row in txn_rows:
        dates.append(txn_row["date"])
        posting_rows = db.fetchall(
            "SELECT account_id, currency FROM postings WHERE transaction_id = ?",
            (txn_row["id"],),
        )
        for pr in posting_rows:
            affected_account_ids.add(pr["account_id"])
            affected_commodities.add(pr["currency"])

    min_date = min(dates)
    max_date = max(dates)

    with db.transaction():
        for txn_id in txn_ids:
            _undo_lot_effects(db, txn_id)

        for txn_id in txn_ids:
            db.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))

        db.execute(
            "DELETE FROM raw_extractions WHERE source_file_id = ?",
            (source_file_id,),
        )

        context = RefreshContext(
            affected_account_ids=affected_account_ids,
            affected_date_range=(min_date, max_date),
            affected_commodities=affected_commodities,
        )
        registry.refresh_all(db, context)

    return {"deleted_transactions": len(txn_ids)}
