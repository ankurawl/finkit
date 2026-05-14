from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.summaries.registry import SummaryBuilder, RefreshContext, registry


@registry.register("s_yearly_capital_gains")
class YearlyCapitalGainsBuilder(SummaryBuilder):
    table_name = "s_yearly_capital_gains"

    def get_create_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS s_yearly_capital_gains (
            year INTEGER NOT NULL,
            term TEXT NOT NULL,
            currency TEXT NOT NULL,
            total_proceeds TEXT NOT NULL,
            total_cost_basis TEXT NOT NULL,
            total_gain_loss TEXT NOT NULL,
            disposition_count INTEGER,
            PRIMARY KEY (year, term, currency)
        )
        """

    def rebuild(self, db: Database) -> None:
        db.execute("DELETE FROM s_yearly_capital_gains")
        self._compute_all(db)

    def refresh(self, db: Database, context: RefreshContext) -> None:
        if not context.affected_date_range:
            return

        start_year = int(context.affected_date_range[0][:4])
        end_year = int(context.affected_date_range[1][:4])

        db.execute(
            "DELETE FROM s_yearly_capital_gains WHERE year >= ? AND year <= ?",
            (start_year, end_year),
        )
        self._compute_all(db, start_year=start_year, end_year=end_year)

    def _compute_all(
        self, db: Database, start_year: int | None = None, end_year: int | None = None
    ) -> None:
        where_clause = ""
        params: list = []
        if start_year is not None and end_year is not None:
            where_clause = "WHERE CAST(SUBSTR(t.date, 1, 4) AS INTEGER) >= ? AND CAST(SUBSTR(t.date, 1, 4) AS INTEGER) <= ?"
            params = [start_year, end_year]

        rows = db.fetchall(f"""
            SELECT CAST(SUBSTR(t.date, 1, 4) AS INTEGER) AS year,
                   ld.term,
                   ld.gain_loss_currency AS currency,
                   SUM(CAST(ld.proceeds_per_unit AS REAL) * CAST(ld.quantity AS REAL)) AS total_proceeds,
                   SUM(CAST(l.cost_price AS REAL) * CAST(ld.quantity AS REAL)) AS total_cost_basis,
                   SUM(CAST(ld.gain_loss AS REAL)) AS total_gain_loss,
                   COUNT(*) AS disposition_count
            FROM lot_dispositions ld
            JOIN transactions t ON t.id = ld.sell_transaction_id
            JOIN lots l ON l.id = ld.lot_id
            {where_clause}
            GROUP BY year, ld.term, ld.gain_loss_currency
        """, params)

        for row in rows:
            db.execute(
                """INSERT INTO s_yearly_capital_gains
                   (year, term, currency, total_proceeds, total_cost_basis,
                    total_gain_loss, disposition_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (row["year"], row["term"], row["currency"],
                 str(Decimal(str(row["total_proceeds"]))),
                 str(Decimal(str(row["total_cost_basis"]))),
                 str(Decimal(str(row["total_gain_loss"]))),
                 row["disposition_count"]),
            )
