from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.summaries.registry import SummaryBuilder, RefreshContext, registry


@registry.register("s_account_monthly_balances")
class MonthlyBalancesBuilder(SummaryBuilder):
    table_name = "s_account_monthly_balances"

    def get_create_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS s_account_monthly_balances (
            account_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            closing_balance TEXT NOT NULL,
            currency TEXT NOT NULL,
            PRIMARY KEY (account_id, year_month, currency)
        )
        """

    def rebuild(self, db: Database) -> None:
        db.execute("DELETE FROM s_account_monthly_balances")

        rows = db.fetchall("""
            SELECT p.account_id, SUBSTR(t.date, 1, 7) AS year_month,
                   p.currency,
                   SUM(CAST(p.amount AS REAL)) AS month_total
            FROM postings p
            JOIN transactions t ON t.id = p.transaction_id
            GROUP BY p.account_id, year_month, p.currency
            ORDER BY p.account_id, p.currency, year_month
        """)

        running: dict[tuple[int, str], Decimal] = {}
        for row in rows:
            key = (row["account_id"], row["currency"])
            month_total = Decimal(str(row["month_total"]))
            balance = running.get(key, Decimal("0")) + month_total
            running[key] = balance
            db.execute(
                """INSERT INTO s_account_monthly_balances
                   (account_id, year_month, closing_balance, currency)
                   VALUES (?, ?, ?, ?)""",
                (row["account_id"], row["year_month"],
                 str(balance), row["currency"]),
            )

    def refresh(self, db: Database, context: RefreshContext) -> None:
        if not context.affected_account_ids:
            return

        earliest_month = context.affected_date_range[0][:7]
        placeholders = ",".join("?" for _ in context.affected_account_ids)
        account_ids = list(context.affected_account_ids)

        db.execute(
            f"""DELETE FROM s_account_monthly_balances
                WHERE account_id IN ({placeholders}) AND year_month >= ?""",
            (*account_ids, earliest_month),
        )

        for account_id in context.affected_account_ids:
            prior_rows = db.fetchall(
                """SELECT currency, closing_balance
                   FROM s_account_monthly_balances
                   WHERE account_id = ? AND year_month < ?
                   ORDER BY year_month DESC""",
                (account_id, earliest_month),
            )
            running: dict[str, Decimal] = {}
            for pr in prior_rows:
                if pr["currency"] not in running:
                    running[pr["currency"]] = Decimal(str(pr["closing_balance"]))

            rows = db.fetchall(
                """SELECT SUBSTR(t.date, 1, 7) AS year_month,
                          p.currency,
                          SUM(CAST(p.amount AS REAL)) AS month_total
                   FROM postings p
                   JOIN transactions t ON t.id = p.transaction_id
                   WHERE p.account_id = ? AND SUBSTR(t.date, 1, 7) >= ?
                   GROUP BY year_month, p.currency
                   ORDER BY p.currency, year_month""",
                (account_id, earliest_month),
            )

            for row in rows:
                currency = row["currency"]
                month_total = Decimal(str(row["month_total"]))
                balance = running.get(currency, Decimal("0")) + month_total
                running[currency] = balance
                db.execute(
                    """INSERT INTO s_account_monthly_balances
                       (account_id, year_month, closing_balance, currency)
                       VALUES (?, ?, ?, ?)""",
                    (account_id, row["year_month"],
                     str(balance), currency),
                )
