from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from finkit.db import Database
from finkit.models import BalanceAssertion

_DEFAULT_TOLERANCE = Decimal("0.01")


def _get_tolerance(db: Database, currency: str) -> Decimal:
    row = db.fetchone(
        "SELECT tolerance FROM currency_tolerances WHERE currency = ?",
        (currency,),
    )
    if row is None:
        return _DEFAULT_TOLERANCE
    return Decimal(str(row["tolerance"]))


def _sum_by_currency(rows: list[dict]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        cur = row["currency"]
        amt = Decimal(str(row["amount"]))
        totals[cur] = totals.get(cur, Decimal("0")) + amt
    return totals


def compute_balance(
    db: Database,
    account_id: int,
    as_of_date: str | None = None,
    currency: str | None = None,
) -> dict[str, Decimal]:
    conditions = ["p.account_id = ?"]
    params: list = [account_id]

    if as_of_date is not None:
        conditions.append("t.date <= ?")
        params.append(as_of_date)

    if currency is not None:
        conditions.append("p.currency = ?")
        params.append(currency)

    where = " AND ".join(conditions)
    rows = db.fetchall(
        f"""
        SELECT p.amount, p.currency
        FROM postings p
        JOIN transactions t ON p.transaction_id = t.id
        WHERE {where}
        """,
        tuple(params),
    )

    return _sum_by_currency(rows)


def compute_subtree_balance(
    db: Database,
    account_prefix: str,
    as_of_date: str | None = None,
) -> dict[str, Decimal]:
    like_pattern = account_prefix + ":%"
    conditions = ["(a.name = ? OR a.name LIKE ?)"]
    params: list = [account_prefix, like_pattern]

    if as_of_date is not None:
        conditions.append("t.date <= ?")
        params.append(as_of_date)

    where = " AND ".join(conditions)
    rows = db.fetchall(
        f"""
        SELECT p.amount, p.currency
        FROM postings p
        JOIN transactions t ON p.transaction_id = t.id
        JOIN accounts a ON p.account_id = a.id
        WHERE {where}
        """,
        tuple(params),
    )

    return _sum_by_currency(rows)


def assert_balance(
    db: Database,
    account_id: int,
    date: str,
    expected_amount: Decimal,
    currency: str,
) -> BalanceAssertion:
    balances = compute_balance(db, account_id, as_of_date=date, currency=currency)
    actual = balances.get(currency, Decimal("0"))

    difference = actual - expected_amount
    tolerance = _get_tolerance(db, currency)
    matches = abs(difference) <= tolerance

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db.execute(
        """
        INSERT INTO balance_assertions
            (account_id, date, expected_amount, actual_amount, currency, matches, difference, asserted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (account_id, date, str(expected_amount), str(actual), currency, int(matches), str(difference), now),
    )

    row = db.fetchone("SELECT last_insert_rowid() AS id")
    assertion_id = row["id"] if row else None

    return BalanceAssertion(
        id=assertion_id,
        account_id=account_id,
        date=date,
        expected_amount=expected_amount,
        actual_amount=actual,
        currency=currency,
        matches=matches,
        difference=difference,
        asserted_at=now,
    )


def compute_all_balances(
    db: Database,
    account_type: str | None = None,
    as_of_date: str | None = None,
) -> dict[int, dict[str, Decimal]]:
    conditions: list[str] = []
    params: list = []

    if account_type is not None:
        conditions.append("a.type = ?")
        params.append(account_type)

    if as_of_date is not None:
        conditions.append("t.date <= ?")
        params.append(as_of_date)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    rows = db.fetchall(
        f"""
        SELECT p.account_id, p.amount, p.currency
        FROM postings p
        JOIN transactions t ON p.transaction_id = t.id
        JOIN accounts a ON p.account_id = a.id
        {where_clause}
        """,
        tuple(params),
    )

    result: dict[int, dict[str, Decimal]] = {}
    for row in rows:
        acct_id = row["account_id"]
        cur = row["currency"]
        amt = Decimal(str(row["amount"]))
        if acct_id not in result:
            result[acct_id] = {}
        result[acct_id][cur] = result[acct_id].get(cur, Decimal("0")) + amt

    return result
