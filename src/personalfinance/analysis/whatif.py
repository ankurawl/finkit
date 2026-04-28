"""What-if sell simulation — compute tax impact without modifying the ledger."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from beancount.core import data as bc_data

from personalfinance.ledger import load_file


LONG_TERM_DAYS = 365


def what_if_sell(
    commodity: str,
    quantity: Decimal,
    price: Decimal,
    currency: str | None = None,
    account: str | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Simulate selling shares/crypto and compute tax impact.

    Does NOT modify the ledger. Shows which lots would be sold
    (per account's booking method), realized gain/loss, and
    short vs long term split.
    """
    entries, errors, options = load_file(ledger_path)
    if currency is None:
        currency = options.get("operating_currency", ["USD"])[0] if options.get("operating_currency") else "USD"

    today = date.today()

    lots = _collect_lots(entries, commodity, account)

    if not lots:
        return {
            "status": "error",
            "message": f"No holdings found for {commodity}" + (f" in {account}" if account else ""),
        }

    total_held = sum(lot["quantity"] for lot in lots)
    if quantity > total_held:
        return {
            "status": "error",
            "message": f"Insufficient holdings: you hold {total_held} {commodity}, tried to sell {quantity}",
            "holdings": str(total_held),
        }

    lots_to_sell = _select_lots_fifo(lots, quantity)

    dispositions = []
    total_proceeds = Decimal(0)
    total_cost = Decimal(0)
    short_term_gain = Decimal(0)
    long_term_gain = Decimal(0)

    for lot in lots_to_sell:
        proceeds = lot["sell_quantity"] * price
        cost_basis = lot["sell_quantity"] * lot["cost_per_unit"]
        gain = proceeds - cost_basis
        holding_days = (today - lot["buy_date"]).days
        term = "long_term" if holding_days > LONG_TERM_DAYS else "short_term"

        total_proceeds += proceeds
        total_cost += cost_basis

        if term == "short_term":
            short_term_gain += gain
        else:
            long_term_gain += gain

        dispositions.append({
            "account": lot["account"],
            "quantity": str(lot["sell_quantity"]),
            "buy_date": lot["buy_date"].isoformat(),
            "holding_days": holding_days,
            "cost_per_unit": str(lot["cost_per_unit"]),
            "cost_basis": str(round(cost_basis, 2)),
            "sell_price": str(price),
            "proceeds": str(round(proceeds, 2)),
            "gain_loss": str(round(gain, 2)),
            "term": term,
        })

    remaining = total_held - quantity

    return {
        "status": "ok",
        "commodity": commodity,
        "quantity_sold": str(quantity),
        "sell_price": str(price),
        "currency": currency,
        "total_proceeds": str(round(total_proceeds, 2)),
        "total_cost_basis": str(round(total_cost, 2)),
        "total_gain_loss": str(round(short_term_gain + long_term_gain, 2)),
        "short_term_gain": str(round(short_term_gain, 2)),
        "long_term_gain": str(round(long_term_gain, 2)),
        "dispositions": dispositions,
        "remaining_holdings": str(remaining),
        "note": "This is a simulation. No changes were made to the ledger.",
    }


def _collect_lots(entries: list, commodity: str, account: str | None) -> list[dict]:
    """Collect all open lots for a commodity."""
    lots_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
            continue

        for posting in entry.postings:
            if not posting.units or posting.units.number is None:
                continue
            if posting.units.currency != commodity:
                continue
            if not posting.account.startswith("Assets:"):
                continue
            if account and account.lower() not in posting.account.lower():
                continue
            if not posting.cost:
                continue

            key = (posting.account, commodity)
            qty = posting.units.number
            cost_per = posting.cost.number if posting.cost.number else Decimal(0)
            cost_date = posting.cost.date or entry.date

            if qty > 0:
                lots_by_key[key].append({
                    "account": posting.account,
                    "quantity": qty,
                    "cost_per_unit": cost_per,
                    "buy_date": cost_date,
                })
            elif qty < 0:
                _reduce_lots(lots_by_key[key], abs(qty))

    all_lots = []
    for key, lots in lots_by_key.items():
        all_lots.extend(lots)

    all_lots.sort(key=lambda l: l["buy_date"])
    return all_lots


def _reduce_lots(lots: list[dict], qty_to_sell: Decimal) -> None:
    """Reduce lots by sold quantity (FIFO)."""
    remaining = qty_to_sell
    while remaining > 0 and lots:
        if lots[0]["quantity"] <= remaining:
            remaining -= lots[0]["quantity"]
            lots.pop(0)
        else:
            lots[0]["quantity"] -= remaining
            remaining = Decimal(0)


def _select_lots_fifo(lots: list[dict], quantity: Decimal) -> list[dict]:
    """Select lots to sell in FIFO order."""
    remaining = quantity
    selected = []

    for lot in lots:
        if remaining <= 0:
            break
        sell_qty = min(lot["quantity"], remaining)
        selected.append({
            **lot,
            "sell_quantity": sell_qty,
        })
        remaining -= sell_qty

    return selected
