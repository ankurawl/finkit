from __future__ import annotations

from decimal import Decimal
from math import sqrt

from finkit.db import Database


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values) / len(values)


def _stddev(values: list[Decimal], mean: Decimal) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return Decimal(str(sqrt(float(variance))))


def analyze_spending(
    db: Database,
    year_month: str | None = None,
    months: int = 6,
    category: str | None = None,
    currency: str = "USD",
) -> dict:
    if year_month is not None:
        y, m = int(year_month[:4]), int(year_month[5:7])
    else:
        latest = db.fetchone(
            "SELECT MAX(year_month) AS ym FROM s_monthly_spending WHERE currency = ?",
            (currency,),
        )
        if latest and latest["ym"]:
            y, m = int(latest["ym"][:4]), int(latest["ym"][5:7])
        else:
            return {
                "total_expenses": "0",
                "total_income": "0",
                "net": "0",
                "by_category": [],
                "monthly_trend": [],
                "anomalies": [],
            }

    month_keys: list[str] = []
    cy, cm = y, m
    for _ in range(months):
        month_keys.append(f"{cy:04d}-{cm:02d}")
        cm -= 1
        if cm < 1:
            cm = 12
            cy -= 1
    month_keys.reverse()

    placeholders = ",".join("?" for _ in month_keys)

    base_filter = (
        f"s.year_month IN ({placeholders}) AND s.currency = ? AND a.type IN ('Expenses', 'Income')"
    )
    params: list = list(month_keys) + [currency]

    if category:
        base_filter += " AND a.name LIKE ?"
        params.append(f"%{category}%")

    rows = db.fetchall(
        f"""
        SELECT a.name, a.type, s.year_month, s.total
        FROM s_monthly_spending s
        JOIN accounts a ON a.id = s.account_id
        WHERE {base_filter}
        ORDER BY s.year_month, a.name
        """,
        tuple(params),
    )

    total_expenses = Decimal("0")
    total_income = Decimal("0")
    category_totals: dict[str, Decimal] = {}
    monthly_expenses: dict[str, Decimal] = {mk: Decimal("0") for mk in month_keys}
    monthly_income: dict[str, Decimal] = {mk: Decimal("0") for mk in month_keys}

    for row in rows:
        amount = Decimal(str(row["total"]))
        acct_type = row["type"]
        acct_name = row["name"]
        ym = row["year_month"]

        if acct_type == "Expenses":
            total_expenses += amount
            category_totals[acct_name] = category_totals.get(acct_name, Decimal("0")) + amount
            monthly_expenses[ym] = monthly_expenses.get(ym, Decimal("0")) + amount
        elif acct_type == "Income":
            total_income += amount
            category_totals[acct_name] = category_totals.get(acct_name, Decimal("0")) + amount
            monthly_income[ym] = monthly_income.get(ym, Decimal("0")) + amount

    by_category = sorted(
        [{"account": k, "total": str(v)} for k, v in category_totals.items()],
        key=lambda x: Decimal(x["total"]),
        reverse=True,
    )

    monthly_trend = [
        {
            "year_month": mk,
            "expenses": str(monthly_expenses[mk]),
            "income": str(monthly_income[mk]),
        }
        for mk in month_keys
    ]

    expense_values = [monthly_expenses[mk] for mk in month_keys]
    mean_exp = _mean(expense_values)
    std_exp = _stddev(expense_values, mean_exp)

    anomalies: list[dict] = []
    if std_exp > 0:
        threshold = mean_exp + 2 * std_exp
        for mk in month_keys:
            if monthly_expenses[mk] > threshold:
                anomalies.append({
                    "year_month": mk,
                    "amount": str(monthly_expenses[mk]),
                    "mean": str(mean_exp),
                    "std_dev": str(std_exp),
                })

    return {
        "total_expenses": str(total_expenses),
        "total_income": str(total_income),
        "net": str(total_income - total_expenses),
        "by_category": by_category,
        "monthly_trend": monthly_trend,
        "anomalies": anomalies,
    }


def compare_budget(
    db: Database,
    year_month: str,
    currency: str = "USD",
) -> list[dict]:
    rows = db.fetchall(
        """
        SELECT a.name AS account, b.amount AS budget,
               COALESCE(s.total, '0') AS actual
        FROM budgets b
        JOIN accounts a ON a.id = b.account_id
        LEFT JOIN s_monthly_spending s
            ON s.account_id = b.account_id
            AND s.year_month = b.year_month
            AND s.currency = b.currency
        WHERE b.year_month = ? AND b.currency = ?
        ORDER BY a.name
        """,
        (year_month, currency),
    )

    results: list[dict] = []
    for row in rows:
        budget = Decimal(str(row["budget"]))
        actual = Decimal(str(row["actual"]))
        difference = budget - actual
        percent_used = (
            str((actual / budget * 100).quantize(Decimal("0.01")))
            if budget != 0
            else "0"
        )
        results.append({
            "account": row["account"],
            "budget": str(budget),
            "actual": str(actual),
            "difference": str(difference),
            "percent_used": percent_used,
        })

    return results
