from __future__ import annotations

from decimal import Decimal

from finkit.db import Database
from finkit.summaries.registry import SummaryBuilder, RefreshContext, registry

_ASSET_CLASS_MAP = {
    None: "cash",
    "cash": "cash",
    "equity": "equity",
    "debt": "debt",
    "crypto": "crypto",
}


@registry.register("s_net_worth")
class NetWorthBuilder(SummaryBuilder):
    table_name = "s_net_worth"

    def get_create_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS s_net_worth (
            year_month TEXT NOT NULL,
            currency TEXT NOT NULL,
            total_assets TEXT NOT NULL,
            total_liabilities TEXT NOT NULL,
            net_worth TEXT NOT NULL,
            assets_cash TEXT,
            assets_equity TEXT,
            assets_debt TEXT,
            assets_crypto TEXT,
            assets_other TEXT,
            exchange_rate_to_base TEXT,
            PRIMARY KEY (year_month, currency)
        )
        """

    def rebuild(self, db: Database) -> None:
        db.execute("DELETE FROM s_net_worth")
        self._compute_all(db)

    def refresh(self, db: Database, context: RefreshContext) -> None:
        earliest_month = context.affected_date_range[0][:7]
        db.execute("DELETE FROM s_net_worth WHERE year_month >= ?", (earliest_month,))
        self._compute_all(db, from_month=earliest_month)

    def _compute_all(self, db: Database, from_month: str | None = None) -> None:
        where_clause = ""
        params: list = []
        if from_month:
            where_clause = "WHERE mb.year_month >= ?"
            params.append(from_month)

        rows = db.fetchall(f"""
            SELECT mb.year_month, mb.currency, a.type, a.asset_class,
                   SUM(CAST(mb.closing_balance AS REAL)) AS total
            FROM s_account_monthly_balances mb
            JOIN accounts a ON a.id = mb.account_id
            WHERE a.type IN ('Assets', 'Liabilities')
            {"AND mb.year_month >= ?" if from_month else ""}
            GROUP BY mb.year_month, mb.currency, a.type, a.asset_class
        """, params)

        agg: dict[tuple[str, str], dict] = {}
        for row in rows:
            key = (row["year_month"], row["currency"])
            if key not in agg:
                agg[key] = {
                    "total_assets": Decimal("0"),
                    "total_liabilities": Decimal("0"),
                    "assets_cash": Decimal("0"),
                    "assets_equity": Decimal("0"),
                    "assets_debt": Decimal("0"),
                    "assets_crypto": Decimal("0"),
                    "assets_other": Decimal("0"),
                }

            total = Decimal(str(row["total"]))
            entry = agg[key]

            if row["type"] == "Assets":
                entry["total_assets"] += total
                bucket = _ASSET_CLASS_MAP.get(row["asset_class"], "other")
                entry[f"assets_{bucket}"] += total
            else:
                entry["total_liabilities"] += total

        for (year_month, currency), entry in agg.items():
            net_worth = entry["total_assets"] + entry["total_liabilities"]
            db.execute(
                """INSERT INTO s_net_worth
                   (year_month, currency, total_assets, total_liabilities,
                    net_worth, assets_cash, assets_equity, assets_debt,
                    assets_crypto, assets_other, exchange_rate_to_base)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (year_month, currency,
                 str(entry["total_assets"]),
                 str(entry["total_liabilities"]),
                 str(net_worth),
                 str(entry["assets_cash"]),
                 str(entry["assets_equity"]),
                 str(entry["assets_debt"]),
                 str(entry["assets_crypto"]),
                 str(entry["assets_other"]),
                 None),
            )

        self._compute_consolidated(db, from_month)

    def _compute_consolidated(self, db: Database, from_month: str | None = None) -> None:
        where_clause = ""
        params: list = []
        if from_month:
            where_clause = "AND year_month >= ?"
            params.append(from_month)

        months = db.fetchall(f"""
            SELECT DISTINCT year_month FROM s_net_worth
            WHERE currency != 'CONSOLIDATED' {where_clause}
            ORDER BY year_month
        """, params)

        for month_row in months:
            year_month = month_row["year_month"]

            currency_rows = db.fetchall(
                """SELECT currency, total_assets, total_liabilities, net_worth,
                          assets_cash, assets_equity, assets_debt,
                          assets_crypto, assets_other
                   FROM s_net_worth
                   WHERE year_month = ? AND currency != 'CONSOLIDATED'""",
                (year_month,),
            )

            totals = {
                "total_assets": Decimal("0"),
                "total_liabilities": Decimal("0"),
                "net_worth": Decimal("0"),
                "assets_cash": Decimal("0"),
                "assets_equity": Decimal("0"),
                "assets_debt": Decimal("0"),
                "assets_crypto": Decimal("0"),
                "assets_other": Decimal("0"),
            }

            for cr in currency_rows:
                currency = cr["currency"]
                rate = self._get_exchange_rate(db, currency, year_month)

                for field in totals:
                    val = cr[field]
                    if val is not None:
                        totals[field] += Decimal(str(val)) * rate

            db.execute(
                """INSERT OR REPLACE INTO s_net_worth
                   (year_month, currency, total_assets, total_liabilities,
                    net_worth, assets_cash, assets_equity, assets_debt,
                    assets_crypto, assets_other, exchange_rate_to_base)
                   VALUES (?, 'CONSOLIDATED', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (year_month,
                 str(totals["total_assets"]),
                 str(totals["total_liabilities"]),
                 str(totals["net_worth"]),
                 str(totals["assets_cash"]),
                 str(totals["assets_equity"]),
                 str(totals["assets_debt"]),
                 str(totals["assets_crypto"]),
                 str(totals["assets_other"]),
                 "1"),
            )

    def _get_exchange_rate(self, db: Database, currency: str, year_month: str) -> Decimal:
        from finkit.config import load_settings
        settings = load_settings()
        base = settings.base_currency

        if currency == base:
            return Decimal("1")

        end_of_month = year_month + "-31"
        price_row = db.fetchone(
            """SELECT price FROM prices
               WHERE commodity = ? AND currency = ? AND date <= ?
               ORDER BY date DESC LIMIT 1""",
            (currency, base, end_of_month),
        )
        if price_row:
            return Decimal(str(price_row["price"]))

        inverse_row = db.fetchone(
            """SELECT price FROM prices
               WHERE commodity = ? AND currency = ? AND date <= ?
               ORDER BY date DESC LIMIT 1""",
            (base, currency, end_of_month),
        )
        if inverse_row:
            inverse = Decimal(str(inverse_row["price"]))
            if inverse != Decimal("0"):
                return Decimal("1") / inverse

        return Decimal("1")
