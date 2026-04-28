"""Portfolio analysis — net worth, holdings, allocation, unrealized gains."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from beancount.core import data as bc_data

from personalfinance.ledger import load_file


def analyze_portfolio(
    date_: date | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Analyze investment portfolio: net worth, holdings, allocation, unrealized gains.

    Uses latest available prices for market valuation.
    """
    entries, errors, options = load_file(ledger_path)
    if date_ is None:
        date_ = date.today()

    prices = _collect_prices(entries, date_)
    holdings = _compute_holdings(entries, date_)
    balances = _compute_balances(entries, date_)

    base_currency = options.get("operating_currency", ["USD"])[0] if options.get("operating_currency") else "USD"

    total_assets = Decimal(0)
    total_liabilities = Decimal(0)
    holdings_detail = []

    for (account, commodity), lots in holdings.items():
        total_qty = sum(lot["quantity"] for lot in lots)
        if total_qty == 0:
            continue

        market_price = prices.get(commodity, Decimal(1))
        total_cost = sum(lot["quantity"] * lot["cost_per_unit"] for lot in lots)
        market_value = total_qty * market_price
        unrealized = market_value - total_cost

        holding = {
            "account": account,
            "commodity": commodity,
            "quantity": str(total_qty),
            "cost_basis": str(round(total_cost, 2)),
            "market_price": str(market_price),
            "market_value": str(round(market_value, 2)),
            "unrealized_gain": str(round(unrealized, 2)),
            "unrealized_pct": str(round(unrealized / total_cost * 100, 2)) if total_cost else "0",
            "lots": [
                {
                    "quantity": str(lot["quantity"]),
                    "cost_per_unit": str(lot["cost_per_unit"]),
                    "date": lot["date"].isoformat() if lot["date"] else None,
                }
                for lot in lots
            ],
        }
        holdings_detail.append(holding)
        total_assets += market_value

    for account, amounts in balances.items():
        if not account.startswith("Assets:"):
            continue
        for currency, amount in amounts.items():
            if currency == base_currency:
                already_counted = any(
                    h["account"] == account and h["commodity"] == currency
                    for h in holdings_detail
                )
                if not already_counted:
                    total_assets += amount

    for account, amounts in balances.items():
        if account.startswith("Liabilities:"):
            for currency, amount in amounts.items():
                total_liabilities += abs(amount)

    net_worth = total_assets - total_liabilities

    allocation = []
    if holdings_detail:
        total_invested = sum(Decimal(h["market_value"]) for h in holdings_detail)
        if total_invested > 0:
            for h in holdings_detail:
                mv = Decimal(h["market_value"])
                allocation.append({
                    "commodity": h["commodity"],
                    "account": h["account"],
                    "allocation_pct": str(round(mv / total_invested * 100, 2)),
                    "market_value": h["market_value"],
                })

    return {
        "status": "ok",
        "net_worth": str(round(net_worth, 2)),
        "total_assets": str(round(total_assets, 2)),
        "total_liabilities": str(round(total_liabilities, 2)),
        "holdings": holdings_detail,
        "allocation": allocation,
        "currency": base_currency,
        "as_of": date_.isoformat(),
    }


def _collect_prices(entries: list, as_of: date) -> dict[str, Decimal]:
    """Collect latest prices for each commodity from Price directives."""
    prices: dict[str, tuple[date, Decimal]] = {}

    for entry in entries:
        if isinstance(entry, bc_data.Price):
            if entry.date <= as_of:
                existing = prices.get(entry.currency)
                if existing is None or entry.date > existing[0]:
                    prices[entry.currency] = (entry.date, entry.amount.number)

    return {k: v[1] for k, v in prices.items()}


def _compute_holdings(entries: list, as_of: date) -> dict[tuple[str, str], list[dict]]:
    """Compute lot-level holdings from transactions."""
    holdings: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
            continue
        if entry.date > as_of:
            continue

        for posting in entry.postings:
            if not posting.units or posting.units.number is None:
                continue
            if not posting.account.startswith("Assets:"):
                continue
            if not posting.cost:
                continue

            key = (posting.account, posting.units.currency)
            qty = posting.units.number
            cost = posting.cost.number if posting.cost.number else Decimal(0)
            cost_date = posting.cost.date

            if qty > 0:
                holdings[key].append({
                    "quantity": qty,
                    "cost_per_unit": cost,
                    "date": cost_date or entry.date,
                })
            elif qty < 0:
                _reduce_lots(holdings[key], abs(qty))

    return dict(holdings)


def _reduce_lots(lots: list[dict], qty_to_sell: Decimal) -> list[dict]:
    """Reduce lots by sold quantity (FIFO order — lots are already chronological)."""
    remaining = qty_to_sell
    removed = []
    while remaining > 0 and lots:
        lot = lots[0]
        if lot["quantity"] <= remaining:
            remaining -= lot["quantity"]
            removed.append(lots.pop(0))
        else:
            removed.append({"quantity": remaining, "cost_per_unit": lot["cost_per_unit"], "date": lot["date"]})
            lot["quantity"] -= remaining
            remaining = Decimal(0)
    return removed


def _compute_balances(entries: list, as_of: date) -> dict[str, dict[str, Decimal]]:
    """Compute cash balances (non-cost-basis postings) per account."""
    balances: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
            continue
        if entry.date > as_of:
            continue

        for posting in entry.postings:
            if not posting.units or posting.units.number is None:
                continue
            if posting.cost:
                continue
            balances[posting.account][posting.units.currency] += posting.units.number

    return dict(balances)
