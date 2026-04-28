"""Spending and income analysis — breakdowns by category, month, or payee."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import mean, stdev
from typing import Any

from beancount.core import data as bc_data

from personalfinance.ledger import load_file


def analyze_spending(
    date_from: date | None = None,
    date_to: date | None = None,
    group_by: str = "category",
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Analyze spending and income with breakdowns.

    group_by: "category" (expense accounts), "month", or "payee".
    """
    entries, errors, options = load_file(ledger_path)

    expense_totals: dict[str, Decimal] = defaultdict(Decimal)
    income_totals: dict[str, Decimal] = defaultdict(Decimal)
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    by_payee: dict[str, Decimal] = defaultdict(Decimal)

    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
            continue
        if date_from and entry.date < date_from:
            continue
        if date_to and entry.date > date_to:
            continue

        month_key = entry.date.strftime("%Y-%m")

        for posting in entry.postings:
            if not posting.units or posting.units.number is None:
                continue
            amount = posting.units.number
            account = posting.account

            if account.startswith("Expenses:"):
                category = _simplify_category(account)
                expense_totals[category] += amount
                monthly[month_key][category] += amount

                if entry.payee:
                    by_payee[entry.payee] += amount

            elif account.startswith("Income:"):
                category = _simplify_category(account)
                income_totals[category] += abs(amount)

    if group_by == "category":
        breakdown = _format_category_breakdown(expense_totals, income_totals)
    elif group_by == "month":
        breakdown = _format_monthly_breakdown(monthly)
    elif group_by == "payee":
        breakdown = _format_payee_breakdown(by_payee)
    else:
        breakdown = _format_category_breakdown(expense_totals, income_totals)

    total_expenses = sum(expense_totals.values())
    total_income = sum(income_totals.values())

    trends = _compute_trends(monthly)
    anomalies = _detect_anomalies(monthly)

    return {
        "status": "ok",
        "total_expenses": str(total_expenses),
        "total_income": str(total_income),
        "net": str(total_income - total_expenses),
        "breakdown": breakdown,
        "trends": trends,
        "anomalies": anomalies if anomalies else None,
        "period": {
            "from": date_from.isoformat() if date_from else "all",
            "to": date_to.isoformat() if date_to else "all",
        },
    }


def _simplify_category(account: str) -> str:
    """Simplify an account path for display."""
    parts = account.split(":")
    if len(parts) > 2:
        return ":".join(parts[:3])
    return account


def _format_category_breakdown(
    expenses: dict[str, Decimal],
    income: dict[str, Decimal],
) -> dict[str, Any]:
    """Format spending/income by category."""
    expense_list = sorted(
        [{"category": k, "amount": str(v)} for k, v in expenses.items()],
        key=lambda x: Decimal(x["amount"]),
        reverse=True,
    )
    income_list = sorted(
        [{"category": k, "amount": str(v)} for k, v in income.items()],
        key=lambda x: Decimal(x["amount"]),
        reverse=True,
    )
    return {"expenses": expense_list, "income": income_list}


def _format_monthly_breakdown(monthly: dict[str, dict[str, Decimal]]) -> list[dict]:
    """Format spending by month."""
    result = []
    for month in sorted(monthly.keys()):
        categories = monthly[month]
        total = sum(categories.values())
        top = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
        result.append({
            "month": month,
            "total": str(total),
            "top_categories": [{"category": k, "amount": str(v)} for k, v in top],
        })
    return result


def _format_payee_breakdown(by_payee: dict[str, Decimal]) -> list[dict]:
    """Format spending by payee."""
    return sorted(
        [{"payee": k, "amount": str(v)} for k, v in by_payee.items()],
        key=lambda x: Decimal(x["amount"]),
        reverse=True,
    )[:20]


def _compute_trends(monthly: dict[str, dict[str, Decimal]]) -> list[dict] | None:
    """Compute month-over-month spending trends."""
    months = sorted(monthly.keys())
    if len(months) < 2:
        return None

    trends = []
    for i in range(1, len(months)):
        prev_total = sum(monthly[months[i - 1]].values())
        curr_total = sum(monthly[months[i]].values())
        change = curr_total - prev_total
        pct = (change / prev_total * 100) if prev_total else Decimal(0)
        trends.append({
            "month": months[i],
            "total": str(curr_total),
            "change": str(change),
            "change_pct": str(round(pct, 1)),
        })

    return trends


def _detect_anomalies(monthly: dict[str, dict[str, Decimal]]) -> list[dict]:
    """Detect spending anomalies (categories with spikes > 2 std dev from mean)."""
    all_categories: dict[str, list[float]] = defaultdict(list)
    months = sorted(monthly.keys())

    for month in months:
        for cat, amt in monthly[month].items():
            all_categories[cat].append(float(amt))

    anomalies = []
    if len(months) < 3:
        return anomalies

    for cat, values in all_categories.items():
        if len(values) < 3:
            continue
        avg = mean(values)
        sd = stdev(values)
        if sd == 0:
            continue

        latest = values[-1]
        if abs(latest - avg) > 2 * sd:
            anomalies.append({
                "category": cat,
                "month": months[-1],
                "amount": str(round(latest, 2)),
                "average": str(round(avg, 2)),
                "deviation": str(round((latest - avg) / sd, 1)),
            })

    return anomalies
