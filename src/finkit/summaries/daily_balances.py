from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.summaries.registry import SummaryBuilder, RefreshContext, registry


@registry.register("s_daily_balances")
class DailyBalancesBuilder(SummaryBuilder):
    table_name = "s_daily_balances"

    def get_create_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS s_daily_balances (
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            balance TEXT NOT NULL,
            currency TEXT NOT NULL,
            transaction_count INTEGER,
            PRIMARY KEY (account_id, date, currency)
        )
        """

    def rebuild(self, db: Database) -> None:
        db.execute("DELETE FROM s_daily_balances")

        rows = db.fetchall("""
            SELECT p.account_id, t.date, p.currency,
                   SUM(CAST(p.amount AS REAL)) AS day_total,
                   COUNT(DISTINCT t.id) AS txn_count
            FROM postings p
            JOIN transactions t ON t.id = p.transaction_id
            GROUP BY p.account_id, t.date, p.currency
            ORDER BY p.account_id, p.currency, t.date
        """)

        running: dict[tuple[int, str], Decimal] = {}
        for row in rows:
            key = (row["account_id"], row["currency"])
            day_total = Decimal(str(row["day_total"]))
            balance = running.get(key, Decimal("0")) + day_total
            running[key] = balance
            db.execute(
                """INSERT INTO s_daily_balances
                   (account_id, date, balance, currency, transaction_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["account_id"], row["date"], str(balance),
                 row["currency"], row["txn_count"]),
            )

    def refresh(self, db: Database, context: RefreshContext) -> None:
        if not context.affected_account_ids:
            return

        earliest_date = context.affected_date_range[0]
        placeholders = ",".join("?" for _ in context.affected_account_ids)
        account_ids = list(context.affected_account_ids)

        db.execute(
            f"""DELETE FROM s_daily_balances
                WHERE account_id IN ({placeholders}) AND date >= ?""",
            (*account_ids, earliest_date),
        )

        for account_id in context.affected_account_ids:
            prior_rows = db.fetchall(
                """SELECT currency, balance
                   FROM s_daily_balances
                   WHERE account_id = ? AND date < ?
                   ORDER BY date DESC""",
                (account_id, earliest_date),
            )
            running: dict[str, Decimal] = {}
            for pr in prior_rows:
                if pr["currency"] not in running:
                    running[pr["currency"]] = Decimal(str(pr["balance"]))

            rows = db.fetchall(
                """SELECT t.date, p.currency,
                          SUM(CAST(p.amount AS REAL)) AS day_total,
                          COUNT(DISTINCT t.id) AS txn_count
                   FROM postings p
                   JOIN transactions t ON t.id = p.transaction_id
                   WHERE p.account_id = ? AND t.date >= ?
                   GROUP BY t.date, p.currency
                   ORDER BY p.currency, t.date""",
                (account_id, earliest_date),
            )

            for row in rows:
                currency = row["currency"]
                day_total = Decimal(str(row["day_total"]))
                balance = running.get(currency, Decimal("0")) + day_total
                running[currency] = balance
                db.execute(
                    """INSERT INTO s_daily_balances
                       (account_id, date, balance, currency, transaction_count)
                       VALUES (?, ?, ?, ?, ?)""",
                    (account_id, row["date"], str(balance),
                     currency, row["txn_count"]),
                )
