from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.summaries.registry import SummaryBuilder, RefreshContext, registry


@registry.register("s_portfolio_holdings")
class PortfolioHoldingsBuilder(SummaryBuilder):
    table_name = "s_portfolio_holdings"

    def get_create_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS s_portfolio_holdings (
            account_id INTEGER NOT NULL,
            commodity TEXT NOT NULL,
            total_quantity TEXT NOT NULL,
            total_cost_basis TEXT NOT NULL,
            cost_currency TEXT NOT NULL,
            latest_price TEXT,
            latest_price_date TEXT,
            market_value TEXT,
            unrealized_gain TEXT,
            asset_class TEXT,
            PRIMARY KEY (account_id, commodity)
        )
        """

    def rebuild(self, db: Database) -> None:
        db.execute("DELETE FROM s_portfolio_holdings")
        self._compute_all(db)

    def refresh(self, db: Database, context: RefreshContext) -> None:
        if not context.affected_commodities and not context.prices_updated and not context.affected_account_ids:
            return

        conditions = []
        params: list = []

        if context.affected_commodities:
            placeholders = ",".join("?" for _ in context.affected_commodities)
            conditions.append(f"commodity IN ({placeholders})")
            params.extend(context.affected_commodities)

        if context.affected_account_ids:
            placeholders = ",".join("?" for _ in context.affected_account_ids)
            conditions.append(f"account_id IN ({placeholders})")
            params.extend(context.affected_account_ids)

        if conditions:
            where = " OR ".join(conditions)
            db.execute(f"DELETE FROM s_portfolio_holdings WHERE {where}", params)
        else:
            db.execute("DELETE FROM s_portfolio_holdings")

        self._compute_all(db, context)

    def _compute_all(self, db: Database, context: RefreshContext | None = None) -> None:
        where_clause = ""
        params: list = []

        if context:
            conditions = []
            if context.affected_commodities:
                placeholders = ",".join("?" for _ in context.affected_commodities)
                conditions.append(f"l.commodity IN ({placeholders})")
                params.extend(context.affected_commodities)
            if context.affected_account_ids:
                placeholders = ",".join("?" for _ in context.affected_account_ids)
                conditions.append(f"l.account_id IN ({placeholders})")
                params.extend(context.affected_account_ids)
            if conditions:
                where_clause = "AND (" + " OR ".join(conditions) + ")"

        rows = db.fetchall(f"""
            SELECT l.account_id, l.commodity, l.cost_currency,
                   SUM(CAST(l.quantity AS REAL)) AS total_qty,
                   SUM(CAST(l.quantity AS REAL) * CAST(l.cost_price AS REAL)) AS total_cost,
                   a.asset_class
            FROM lots l
            JOIN accounts a ON a.id = l.account_id
            WHERE l.disposed = 0 AND CAST(l.quantity AS REAL) > 0
                  {where_clause}
            GROUP BY l.account_id, l.commodity, l.cost_currency
        """, params)

        for row in rows:
            total_quantity = Decimal(str(row["total_qty"]))
            total_cost_basis = Decimal(str(row["total_cost"]))
            commodity = row["commodity"]
            cost_currency = row["cost_currency"]

            price_row = db.fetchone(
                """SELECT price, date FROM prices
                   WHERE commodity = ? AND currency = ?
                   ORDER BY date DESC LIMIT 1""",
                (commodity, cost_currency),
            )

            latest_price: Decimal | None = None
            latest_price_date: str | None = None
            market_value: Decimal | None = None
            unrealized_gain: Decimal | None = None

            if price_row:
                latest_price = Decimal(str(price_row["price"]))
                latest_price_date = price_row["date"]
                market_value = total_quantity * latest_price
                unrealized_gain = market_value - total_cost_basis

            db.execute(
                """INSERT INTO s_portfolio_holdings
                   (account_id, commodity, total_quantity, total_cost_basis,
                    cost_currency, latest_price, latest_price_date,
                    market_value, unrealized_gain, asset_class)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["account_id"], commodity,
                 str(total_quantity), str(total_cost_basis), cost_currency,
                 str(latest_price) if latest_price is not None else None,
                 latest_price_date,
                 str(market_value) if market_value is not None else None,
                 str(unrealized_gain) if unrealized_gain is not None else None,
                 row["asset_class"]),
            )
