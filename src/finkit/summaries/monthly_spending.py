from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.summaries.registry import SummaryBuilder, RefreshContext, registry


@registry.register("s_monthly_spending")
class MonthlySpendingBuilder(SummaryBuilder):
    table_name = "s_monthly_spending"

    def get_create_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS s_monthly_spending (
            account_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            total TEXT NOT NULL,
            currency TEXT NOT NULL,
            transaction_count INTEGER,
            PRIMARY KEY (account_id, year_month, currency)
        )
        """

    def rebuild(self, db: Database) -> None:
        db.execute("DELETE FROM s_monthly_spending")

        rows = db.fetchall("""
            SELECT p.account_id,
                   SUBSTR(t.date, 1, 7) AS year_month,
                   p.currency,
                   SUM(CAST(p.amount AS REAL)) AS total,
                   COUNT(DISTINCT t.id) AS txn_count
            FROM postings p
            JOIN transactions t ON t.id = p.transaction_id
            JOIN accounts a ON a.id = p.account_id
            WHERE a.type IN ('Expenses', 'Income')
            GROUP BY p.account_id, year_month, p.currency
        """)

        for row in rows:
            db.execute(
                """INSERT INTO s_monthly_spending
                   (account_id, year_month, total, currency, transaction_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["account_id"], row["year_month"],
                 str(Decimal(str(row["total"]))),
                 row["currency"], row["txn_count"]),
            )

    def refresh(self, db: Database, context: RefreshContext) -> None:
        if not context.affected_account_ids and not context.affected_date_range:
            return

        start_month = context.affected_date_range[0][:7]
        end_month = context.affected_date_range[1][:7]

        db.execute(
            """DELETE FROM s_monthly_spending
               WHERE year_month >= ? AND year_month <= ?""",
            (start_month, end_month),
        )

        rows = db.fetchall(
            """SELECT p.account_id,
                      SUBSTR(t.date, 1, 7) AS year_month,
                      p.currency,
                      SUM(CAST(p.amount AS REAL)) AS total,
                      COUNT(DISTINCT t.id) AS txn_count
               FROM postings p
               JOIN transactions t ON t.id = p.transaction_id
               JOIN accounts a ON a.id = p.account_id
               WHERE a.type IN ('Expenses', 'Income')
                 AND SUBSTR(t.date, 1, 7) >= ?
                 AND SUBSTR(t.date, 1, 7) <= ?
               GROUP BY p.account_id, year_month, p.currency""",
            (start_month, end_month),
        )

        for row in rows:
            db.execute(
                """INSERT INTO s_monthly_spending
                   (account_id, year_month, total, currency, transaction_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["account_id"], row["year_month"],
                 str(Decimal(str(row["total"]))),
                 row["currency"], row["txn_count"]),
            )
