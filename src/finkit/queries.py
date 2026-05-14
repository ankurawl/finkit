from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.engine.balances import compute_balance, compute_all_balances
from finkit.matching import resolve_account


def get_account(db: Database, name: str | None = None, account_id: int | None = None) -> dict | None:
    if account_id is not None:
        return db.fetchone("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if name is not None:
        return db.fetchone("SELECT * FROM accounts WHERE name = ?", (name,))
    return None


def list_accounts(db: Database, account_type: str | None = None) -> list[dict]:
    if account_type is not None:
        return db.fetchall(
            "SELECT * FROM accounts WHERE type = ? ORDER BY name",
            (account_type,),
        )
    return db.fetchall("SELECT * FROM accounts ORDER BY name")


def get_balances(
    db: Database,
    account_name: str | None = None,
    account_type: str | None = None,
    as_of_date: str | None = None,
) -> list[dict]:
    results: list[dict] = []

    if account_name is not None:
        account_id = resolve_account(db, account_name)
        acct = db.fetchone("SELECT name FROM accounts WHERE id = ?", (account_id,))
        resolved_name = acct["name"] if acct else account_name

        row = _latest_summary_balance(db, account_id, as_of_date)
        if row is not None:
            results.append({
                "account": resolved_name,
                "balance": row["balance"],
                "currency": row["currency"],
            })
            return results

        balances = compute_balance(db, account_id, as_of_date=as_of_date)
        for currency, amount in balances.items():
            results.append({
                "account": resolved_name,
                "balance": str(amount),
                "currency": currency,
            })
        return results

    if account_type is not None:
        accounts = db.fetchall(
            "SELECT id, name FROM accounts WHERE type = ?", (account_type,),
        )
    else:
        accounts = db.fetchall("SELECT id, name FROM accounts")

    for acct in accounts:
        row = _latest_summary_balance(db, acct["id"], as_of_date)
        if row is not None:
            results.append({
                "account": acct["name"],
                "balance": row["balance"],
                "currency": row["currency"],
            })
        else:
            balances = compute_balance(db, acct["id"], as_of_date=as_of_date)
            for currency, amount in balances.items():
                results.append({
                    "account": acct["name"],
                    "balance": str(amount),
                    "currency": currency,
                })

    return results


def _latest_summary_balance(
    db: Database, account_id: int, as_of_date: str | None,
) -> dict | None:
    if as_of_date is not None:
        return db.fetchone(
            """
            SELECT balance, currency FROM s_daily_balances
            WHERE account_id = ? AND date <= ?
            ORDER BY date DESC LIMIT 1
            """,
            (account_id, as_of_date),
        )
    return db.fetchone(
        """
        SELECT balance, currency FROM s_daily_balances
        WHERE account_id = ?
        ORDER BY date DESC LIMIT 1
        """,
        (account_id,),
    )


def get_transactions(
    db: Database,
    date_from: str | None = None,
    date_to: str | None = None,
    payee: str | None = None,
    account_name: str | None = None,
    tags: list[str] | None = None,
    amount_min: str | None = None,
    amount_max: str | None = None,
    uuid: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    conditions: list[str] = []
    params: list = []
    joins: list[str] = []

    if date_from is not None:
        conditions.append("t.date >= ?")
        params.append(date_from)
    if date_to is not None:
        conditions.append("t.date <= ?")
        params.append(date_to)
    if payee is not None:
        conditions.append("t.payee LIKE ?")
        params.append(f"%{payee}%")
    if uuid is not None:
        conditions.append("t.uuid = ?")
        params.append(uuid)
    if status is not None:
        conditions.append("t.status = ?")
        params.append(status)

    if account_name is not None:
        account_id = resolve_account(db, account_name)
        joins.append("JOIN postings pf ON pf.transaction_id = t.id")
        conditions.append("pf.account_id = ?")
        params.append(account_id)

    if amount_min is not None or amount_max is not None:
        if "JOIN postings pf ON pf.transaction_id = t.id" not in joins:
            joins.append("JOIN postings pf ON pf.transaction_id = t.id")
        if amount_min is not None:
            conditions.append("ABS(CAST(pf.amount AS REAL)) >= ?")
            params.append(float(amount_min))
        if amount_max is not None:
            conditions.append("ABS(CAST(pf.amount AS REAL)) <= ?")
            params.append(float(amount_max))

    if tags:
        for i, tag in enumerate(tags):
            alias = f"tt{i}"
            joins.append(
                f"JOIN transaction_tags {alias} ON {alias}.transaction_id = t.id"
            )
            conditions.append(f"{alias}.tag = ?")
            params.append(tag)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    join_clause = " ".join(joins)

    sql = f"""
        SELECT DISTINCT t.id, t.uuid, t.date, t.payee, t.narration,
               t.status, t.source_file_id, t.created_at, t.modified_at
        FROM transactions t
        {join_clause}
        {where_clause}
        ORDER BY t.date DESC, t.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    txn_rows = db.fetchall(sql, tuple(params))

    results: list[dict] = []
    for txn_row in txn_rows:
        txn_id = txn_row["id"]

        posting_rows = db.fetchall(
            """
            SELECT p.id, p.account_id, a.name AS account_name,
                   p.amount, p.currency,
                   p.cost_amount, p.cost_currency, p.cost_date,
                   p.price, p.price_currency, p.lot_id
            FROM postings p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.transaction_id = ?
            ORDER BY p.id
            """,
            (txn_id,),
        )
        postings = [
            {
                "id": pr["id"],
                "account_id": pr["account_id"],
                "account_name": pr["account_name"],
                "amount": pr["amount"],
                "currency": pr["currency"],
                "cost_amount": pr["cost_amount"],
                "cost_currency": pr["cost_currency"],
                "cost_date": pr["cost_date"],
                "price": pr["price"],
                "price_currency": pr["price_currency"],
                "lot_id": pr["lot_id"],
            }
            for pr in posting_rows
        ]

        tag_rows = db.fetchall(
            "SELECT tag FROM transaction_tags WHERE transaction_id = ?",
            (txn_id,),
        )
        tag_list = [tr["tag"] for tr in tag_rows]

        results.append({
            "id": txn_row["id"],
            "uuid": txn_row["uuid"],
            "date": txn_row["date"],
            "payee": txn_row["payee"],
            "narration": txn_row["narration"],
            "status": txn_row["status"],
            "source_file_id": txn_row["source_file_id"],
            "created_at": txn_row["created_at"],
            "modified_at": txn_row["modified_at"],
            "postings": postings,
            "tags": tag_list,
        })

    return results


def run_query(db: Database, sql: str, params: tuple | dict = ()) -> list[dict]:
    return db.query_readonly(sql, params)


def budget_vs_actual(
    db: Database, year_month: str, currency: str = "USD",
) -> list[dict]:
    rows = db.fetchall(
        """
        SELECT
            a.name AS account,
            b.amount AS budget,
            COALESCE(s.total, '0') AS actual,
            b.account_id,
            b.currency
        FROM budgets b
        JOIN accounts a ON b.account_id = a.id
        LEFT JOIN s_monthly_spending s
            ON s.account_id = b.account_id
            AND s.year_month = b.year_month
            AND s.currency = b.currency
        WHERE b.year_month = ? AND b.currency = ?
        """,
        (year_month, currency),
    )

    budget_account_ids = {r["account_id"] for r in rows}

    spending_only = db.fetchall(
        """
        SELECT a.name AS account, s.total AS actual, s.account_id, s.currency
        FROM s_monthly_spending s
        JOIN accounts a ON s.account_id = a.id
        WHERE s.year_month = ? AND s.currency = ?
        """,
        (year_month, currency),
    )

    results: list[dict] = []

    for r in rows:
        budget_dec = Decimal(str(r["budget"]))
        actual_dec = Decimal(str(r["actual"]))
        difference = budget_dec - actual_dec
        results.append({
            "account": r["account"],
            "budget": str(budget_dec),
            "actual": str(actual_dec),
            "difference": str(difference),
            "currency": r["currency"],
        })

    for sr in spending_only:
        if sr["account_id"] in budget_account_ids:
            continue
        actual_dec = Decimal(str(sr["actual"]))
        results.append({
            "account": sr["account"],
            "budget": "0",
            "actual": str(actual_dec),
            "difference": str(-actual_dec),
            "currency": sr["currency"],
        })

    return results
