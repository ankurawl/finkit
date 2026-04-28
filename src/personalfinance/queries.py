"""Query operations — beanquery SQL, structured balance and transaction queries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from beancount.core import data as bc_data

from personalfinance.ledger import load_file


def run_query(query_string: str, ledger_path: str | None = None) -> list[dict]:
    """
    Execute a beanquery SQL query against the ledger.

    Returns a list of dicts (one per row).
    """
    from beanquery import query as bq

    entries, errors, options = load_file(ledger_path)
    result_types, result_rows = bq.run_query(entries, options, query_string)

    if result_rows is None:
        return []

    columns = [col[0] for col in result_types]
    results = []
    for row in result_rows:
        row_dict = {}
        for i, col_name in enumerate(columns):
            val = row[i]
            row_dict[col_name] = _serialize_value(val)
        results.append(row_dict)
    return results


def get_balances(
    account_filter: str | None = None,
    date_: date | None = None,
    currency: str | None = None,
    ledger_path: str | None = None,
) -> list[dict]:
    """
    Get account balances, optionally filtered.

    account_filter supports wildcards (e.g., "Assets:*").
    """
    where_clauses = []
    if account_filter:
        pattern = account_filter.replace("*", "%")
        where_clauses.append(f"account ~ '{pattern}'")
    if currency:
        where_clauses.append(f"currency = '{currency}'")

    where = ""
    if where_clauses:
        where = " WHERE " + " AND ".join(where_clauses)

    if date_:
        query = f"BALANCES AT cost FROM CLOSE ON {date_.isoformat()}{where}"
    else:
        query = f"SELECT account, sum(position) as balance{where} GROUP BY account ORDER BY account"

    try:
        return run_query(query, ledger_path)
    except Exception:
        query_simple = "SELECT account, sum(position) as balance GROUP BY account ORDER BY account"
        results = run_query(query_simple, ledger_path)
        if account_filter:
            pattern = account_filter.replace("*", "")
            results = [r for r in results if pattern.lower() in r.get("account", "").lower()]
        return results


def get_transactions(
    date_from: date | None = None,
    date_to: date | None = None,
    payee: str | None = None,
    account: str | None = None,
    tags: list[str] | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    uuid: str | None = None,
    ledger_path: str | None = None,
) -> list[dict]:
    """Search transactions with structured filters."""
    entries, errors, options = load_file(ledger_path)

    results = []
    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
            continue

        if date_from and entry.date < date_from:
            continue
        if date_to and entry.date > date_to:
            continue

        if payee and entry.payee and payee.lower() not in entry.payee.lower():
            continue
        if payee and not entry.payee:
            continue

        if account:
            acct_match = any(account.lower() in p.account.lower() for p in entry.postings)
            if not acct_match:
                continue

        if tags:
            entry_tags = entry.tags or frozenset()
            if not all(t in entry_tags for t in tags):
                continue

        if uuid:
            from personalfinance.uuids import TAG_PREFIX
            target = f"{TAG_PREFIX}{uuid}"
            entry_tags = entry.tags or frozenset()
            if target not in entry_tags:
                continue

        if amount_min is not None or amount_max is not None:
            amounts = [abs(p.units.number) for p in entry.postings if p.units and p.units.number]
            if not amounts:
                continue
            max_amt = max(amounts)
            if amount_min is not None and max_amt < amount_min:
                continue
            if amount_max is not None and max_amt > amount_max:
                continue

        results.append(_format_transaction(entry))

    return results


def _format_transaction(entry: bc_data.Transaction) -> dict:
    """Convert a Transaction entry to a dict."""
    postings = []
    for p in entry.postings:
        posting_dict: dict[str, Any] = {"account": p.account}
        if p.units:
            posting_dict["amount"] = str(p.units.number) if p.units.number else None
            posting_dict["currency"] = p.units.currency
        if p.cost:
            posting_dict["cost"] = {
                "number": str(p.cost.number) if p.cost.number else None,
                "currency": p.cost.currency,
                "date": p.cost.date.isoformat() if p.cost.date else None,
            }
        postings.append(posting_dict)

    uuid_tag = None
    if entry.tags:
        from personalfinance.uuids import TAG_PREFIX
        for t in entry.tags:
            if t.startswith(TAG_PREFIX):
                uuid_tag = t[len(TAG_PREFIX):]
                break

    return {
        "date": entry.date.isoformat(),
        "payee": entry.payee,
        "narration": entry.narration,
        "tags": sorted(entry.tags) if entry.tags else [],
        "links": sorted(entry.links) if entry.links else [],
        "uuid": uuid_tag,
        "postings": postings,
    }


def _serialize_value(val: Any) -> Any:
    """Convert beancount types to JSON-serializable values."""
    if val is None:
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    if isinstance(val, Decimal):
        return str(val)
    if isinstance(val, date):
        return val.isoformat()
    if hasattr(val, "number") and hasattr(val, "currency"):
        return {"number": str(val.number) if val.number else None, "currency": val.currency}
    if hasattr(val, "__iter__"):
        return [_serialize_value(v) for v in val]
    return str(val)
