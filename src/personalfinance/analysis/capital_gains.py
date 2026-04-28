"""Capital gains reporting — realized gains from lot dispositions."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from beancount.core import data as bc_data

from personalfinance.ledger import load_file


LONG_TERM_DAYS = 365


def report_capital_gains(
    year: int | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Report realized capital gains/losses.

    Groups by short-term vs long-term (1-year holding period).
    Lists each lot disposition with full detail.
    """
    entries, errors, options = load_file(ledger_path)
    if year is None:
        year = date.today().year

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    lots_by_account: dict[tuple[str, str], list[dict]] = defaultdict(list)
    dispositions: list[dict] = []

    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
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
            cost_per = posting.cost.number if posting.cost.number else Decimal(0)
            cost_date = posting.cost.date or entry.date

            if qty > 0:
                lots_by_account[key].append({
                    "quantity": qty,
                    "cost_per_unit": cost_per,
                    "buy_date": cost_date,
                })
            elif qty < 0 and year_start <= entry.date <= year_end:
                sell_qty = abs(qty)
                sell_price = _find_sell_price(entry, posting)

                sold_lots = _sell_lots(lots_by_account[key], sell_qty)

                for lot in sold_lots:
                    proceeds = lot["quantity"] * sell_price
                    cost_basis = lot["quantity"] * lot["cost_per_unit"]
                    gain = proceeds - cost_basis
                    holding_days = (entry.date - lot["buy_date"]).days
                    term = "long_term" if holding_days > LONG_TERM_DAYS else "short_term"

                    dispositions.append({
                        "commodity": posting.units.currency,
                        "account": posting.account,
                        "quantity": str(lot["quantity"]),
                        "buy_date": lot["buy_date"].isoformat(),
                        "sell_date": entry.date.isoformat(),
                        "holding_days": holding_days,
                        "cost_per_unit": str(lot["cost_per_unit"]),
                        "sell_price": str(sell_price),
                        "proceeds": str(round(proceeds, 2)),
                        "cost_basis": str(round(cost_basis, 2)),
                        "gain_loss": str(round(gain, 2)),
                        "term": term,
                        "payee": entry.payee,
                    })

    short_term = [d for d in dispositions if d["term"] == "short_term"]
    long_term = [d for d in dispositions if d["term"] == "long_term"]

    st_total = sum(Decimal(d["gain_loss"]) for d in short_term)
    lt_total = sum(Decimal(d["gain_loss"]) for d in long_term)

    return {
        "status": "ok",
        "year": year,
        "short_term": {
            "dispositions": short_term,
            "total_gain_loss": str(st_total),
            "count": len(short_term),
        },
        "long_term": {
            "dispositions": long_term,
            "total_gain_loss": str(lt_total),
            "count": len(long_term),
        },
        "total_gain_loss": str(st_total + lt_total),
        "total_dispositions": len(dispositions),
    }


def _find_sell_price(entry: bc_data.Transaction, sell_posting: Any) -> Decimal:
    """Find the effective sell price from the transaction."""
    if sell_posting.price and sell_posting.price.number:
        return sell_posting.price.number

    qty = abs(sell_posting.units.number)
    for p in entry.postings:
        if p is sell_posting:
            continue
        if p.units and p.units.number and p.units.number > 0:
            if not p.account.startswith("Assets:") or p.units.currency != sell_posting.units.currency:
                return abs(p.units.number) / qty if qty else Decimal(0)

    if sell_posting.cost and sell_posting.cost.number:
        return sell_posting.cost.number

    return Decimal(0)


def _sell_lots(lots: list[dict], qty_to_sell: Decimal) -> list[dict]:
    """Sell lots in FIFO order, returning the lots consumed."""
    remaining = qty_to_sell
    sold = []

    while remaining > 0 and lots:
        lot = lots[0]
        if lot["quantity"] <= remaining:
            remaining -= lot["quantity"]
            sold.append(lots.pop(0))
        else:
            sold.append({
                "quantity": remaining,
                "cost_per_unit": lot["cost_per_unit"],
                "buy_date": lot["buy_date"],
            })
            lot["quantity"] -= remaining
            remaining = Decimal(0)

    return sold
