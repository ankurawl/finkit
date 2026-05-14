from __future__ import annotations

from decimal import Decimal

from finkit.db import Database


def analyze_portfolio(
    db: Database,
    currency: str | None = None,
) -> dict:
    currency_filter = ""
    params: tuple = ()
    if currency:
        currency_filter = "WHERE cost_currency = ?"
        params = (currency,)

    holdings_rows = db.fetchall(
        f"""
        SELECT h.commodity, h.total_quantity, h.total_cost_basis,
               h.cost_currency, h.latest_price, h.latest_price_date,
               h.market_value, h.unrealized_gain, h.asset_class,
               a.name AS account_name
        FROM s_portfolio_holdings h
        JOIN accounts a ON a.id = h.account_id
        {currency_filter}
        ORDER BY a.name, h.commodity
        """,
        params,
    )

    holdings: list[dict] = []
    for row in holdings_rows:
        holdings.append({
            "account": row["account_name"],
            "commodity": row["commodity"],
            "quantity": str(row["total_quantity"]),
            "cost_basis": str(row["total_cost_basis"]),
            "cost_currency": row["cost_currency"],
            "latest_price": str(row["latest_price"]) if row["latest_price"] else None,
            "latest_price_date": row["latest_price_date"],
            "market_value": str(row["market_value"]) if row["market_value"] else None,
            "unrealized_gain": str(row["unrealized_gain"]) if row["unrealized_gain"] else None,
            "asset_class": row["asset_class"],
        })

    nw_filter = ""
    nw_params: tuple = ()
    if currency:
        nw_filter = "WHERE currency = ?"
        nw_params = (currency,)

    net_worth_rows = db.fetchall(
        f"""
        SELECT year_month, currency, total_assets, total_liabilities, net_worth
        FROM s_net_worth
        {nw_filter}
        ORDER BY year_month
        """,
        nw_params,
    )

    latest_nw: dict[str, str] = {}
    historical_trend: list[dict] = []
    for row in net_worth_rows:
        latest_nw[row["currency"]] = str(row["net_worth"])
        historical_trend.append({
            "year_month": row["year_month"],
            "currency": row["currency"],
            "net_worth": str(row["net_worth"]),
            "total_assets": str(row["total_assets"]),
            "total_liabilities": str(row["total_liabilities"]),
        })

    allocation = get_asset_allocation(db)

    return {
        "total_net_worth": latest_nw,
        "asset_allocation": allocation,
        "holdings": holdings,
        "historical_trend": historical_trend,
    }


def get_asset_allocation(db: Database) -> list[dict]:
    rows = db.fetchall(
        """
        SELECT asset_class, SUM(CAST(market_value AS REAL)) AS total_value
        FROM s_portfolio_holdings
        WHERE market_value IS NOT NULL
        GROUP BY asset_class
        ORDER BY total_value DESC
        """,
    )

    grand_total = Decimal("0")
    classes: list[tuple[str | None, Decimal]] = []
    for row in rows:
        val = Decimal(str(row["total_value"]))
        classes.append((row["asset_class"], val))
        grand_total += val

    results: list[dict] = []
    for asset_class, value in classes:
        pct = (
            (value / grand_total * 100).quantize(Decimal("0.01"))
            if grand_total != 0
            else Decimal("0")
        )
        results.append({
            "asset_class": asset_class or "Unclassified",
            "value": str(value),
            "percentage": str(pct),
        })

    return results
