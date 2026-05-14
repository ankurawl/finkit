from __future__ import annotations

from decimal import Decimal

from finkit.db import Database


def report_capital_gains(
    db: Database,
    year: int | None = None,
    currency: str | None = None,
) -> dict:
    summary_filter_parts: list[str] = []
    summary_params: list = []
    if year is not None:
        summary_filter_parts.append("year = ?")
        summary_params.append(year)
    if currency is not None:
        summary_filter_parts.append("currency = ?")
        summary_params.append(currency)

    summary_where = (
        "WHERE " + " AND ".join(summary_filter_parts) if summary_filter_parts else ""
    )

    summary_rows = db.fetchall(
        f"""
        SELECT year, term, currency, total_proceeds, total_cost_basis,
               total_gain_loss, disposition_count
        FROM s_yearly_capital_gains
        {summary_where}
        ORDER BY year, term, currency
        """,
        tuple(summary_params),
    )

    summary: list[dict] = []
    for row in summary_rows:
        summary.append({
            "year": row["year"],
            "term": row["term"],
            "currency": row["currency"],
            "total_proceeds": str(row["total_proceeds"]),
            "total_cost_basis": str(row["total_cost_basis"]),
            "total_gain_loss": str(row["total_gain_loss"]),
            "disposition_count": row["disposition_count"],
        })

    detail_filter_parts: list[str] = []
    detail_params: list = []
    if year is not None:
        detail_filter_parts.append("strftime('%Y', t.date) = ?")
        detail_params.append(str(year))
    if currency is not None:
        detail_filter_parts.append("ld.proceeds_currency = ?")
        detail_params.append(currency)

    detail_where = (
        "WHERE " + " AND ".join(detail_filter_parts) if detail_filter_parts else ""
    )

    detail_rows = db.fetchall(
        f"""
        SELECT ld.id, ld.lot_id, ld.quantity, ld.proceeds_per_unit,
               ld.proceeds_currency, ld.gain_loss, ld.gain_loss_currency,
               ld.term, ld.wash_sale, ld.wash_sale_adjustment,
               l.commodity, l.cost_price, l.cost_currency, l.acquired_date,
               t.date AS sell_date,
               a.name AS account_name, a.jurisdiction
        FROM lot_dispositions ld
        JOIN lots l ON l.id = ld.lot_id
        JOIN transactions t ON t.id = ld.sell_transaction_id
        JOIN accounts a ON a.id = l.account_id
        {detail_where}
        ORDER BY t.date, ld.id
        """,
        tuple(detail_params),
    )

    detail: list[dict] = []
    wash_sales: list[dict] = []

    for row in detail_rows:
        entry = {
            "disposition_id": row["id"],
            "lot_id": row["lot_id"],
            "account": row["account_name"],
            "commodity": row["commodity"],
            "quantity": str(row["quantity"]),
            "cost_price": str(row["cost_price"]),
            "cost_currency": row["cost_currency"],
            "acquired_date": row["acquired_date"],
            "sell_date": row["sell_date"],
            "proceeds_per_unit": str(row["proceeds_per_unit"]),
            "proceeds_currency": row["proceeds_currency"],
            "gain_loss": str(row["gain_loss"]),
            "gain_loss_currency": row["gain_loss_currency"],
            "term": row["term"],
            "jurisdiction": row["jurisdiction"],
            "wash_sale": bool(row["wash_sale"]),
            "wash_sale_adjustment": (
                str(row["wash_sale_adjustment"])
                if row["wash_sale_adjustment"] is not None
                else None
            ),
        }
        detail.append(entry)

        if row["wash_sale"]:
            wash_sales.append(entry)

    return {
        "summary": summary,
        "detail": detail,
        "wash_sales": wash_sales,
    }
