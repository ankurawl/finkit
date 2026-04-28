"""Export tool outputs as CSV or JSON."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any


def export_output(
    tool_name: str,
    format: str = "csv",
    output_path: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """
    Export any tool's output as CSV or JSON.

    Runs the specified tool, then serializes the result.
    """
    tool_map = {
        "analyze_spending": _run_spending,
        "analyze_portfolio": _run_portfolio,
        "report_capital_gains": _run_capital_gains,
        "get_transactions": _run_transactions,
        "get_balances": _run_balances,
    }

    runner = tool_map.get(tool_name)
    if runner is None:
        return {
            "status": "error",
            "message": f"Unknown tool: {tool_name}. Available: {', '.join(tool_map.keys())}",
        }

    data = runner(**kwargs)

    if format == "json":
        output = json.dumps(data, indent=2, default=str)
    elif format == "csv":
        output = _to_csv(data, tool_name)
    else:
        return {"status": "error", "message": f"Unknown format: {format}. Use 'csv' or 'json'."}

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output)
        return {"status": "ok", "format": format, "path": str(path), "size": len(output)}

    return {"status": "ok", "format": format, "content": output}


def _to_csv(data: Any, tool_name: str) -> str:
    """Convert tool output to CSV."""
    rows = _extract_rows(data, tool_name)
    if not rows:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _extract_rows(data: Any, tool_name: str) -> list[dict]:
    """Extract flat rows from tool output for CSV export."""
    if isinstance(data, list):
        return [_flatten(row) for row in data]

    if isinstance(data, dict):
        if "transactions" in data:
            return [_flatten_transaction(t) for t in data["transactions"]]
        if "balances" in data:
            return [_flatten(b) for b in data["balances"]]
        if "breakdown" in data:
            breakdown = data["breakdown"]
            if isinstance(breakdown, dict) and "expenses" in breakdown:
                return [_flatten(e) for e in breakdown["expenses"]]
            if isinstance(breakdown, list):
                return [_flatten(b) for b in breakdown]
        if "holdings" in data:
            return [_flatten_holding(h) for h in data["holdings"]]
        if "short_term" in data and "long_term" in data:
            all_dispositions = []
            for d in data.get("short_term", {}).get("dispositions", []):
                all_dispositions.append(_flatten(d))
            for d in data.get("long_term", {}).get("dispositions", []):
                all_dispositions.append(_flatten(d))
            return all_dispositions

    return []


def _flatten(d: dict) -> dict:
    """Flatten a dict, converting nested structures to strings."""
    flat = {}
    for k, v in d.items():
        if isinstance(v, (list, dict)):
            flat[k] = json.dumps(v, default=str)
        else:
            flat[k] = v
    return flat


def _flatten_transaction(t: dict) -> dict:
    """Flatten a transaction for CSV."""
    flat = {
        "date": t.get("date"),
        "payee": t.get("payee"),
        "narration": t.get("narration"),
        "uuid": t.get("uuid"),
    }
    postings = t.get("postings", [])
    for i, p in enumerate(postings):
        flat[f"account_{i}"] = p.get("account")
        flat[f"amount_{i}"] = p.get("amount")
        flat[f"currency_{i}"] = p.get("currency")
    return flat


def _flatten_holding(h: dict) -> dict:
    """Flatten a holding for CSV."""
    return {
        "account": h.get("account"),
        "commodity": h.get("commodity"),
        "quantity": h.get("quantity"),
        "cost_basis": h.get("cost_basis"),
        "market_price": h.get("market_price"),
        "market_value": h.get("market_value"),
        "unrealized_gain": h.get("unrealized_gain"),
        "unrealized_pct": h.get("unrealized_pct"),
    }


def _run_spending(**kwargs) -> dict:
    from personalfinance.analysis.spending import analyze_spending
    from datetime import date
    return analyze_spending(
        date_from=date.fromisoformat(kwargs["date_from"]) if kwargs.get("date_from") else None,
        date_to=date.fromisoformat(kwargs["date_to"]) if kwargs.get("date_to") else None,
        group_by=kwargs.get("group_by", "category"),
    )


def _run_portfolio(**kwargs) -> dict:
    from personalfinance.analysis.portfolio import analyze_portfolio
    from datetime import date
    return analyze_portfolio(
        date_=date.fromisoformat(kwargs["date"]) if kwargs.get("date") else None,
    )


def _run_capital_gains(**kwargs) -> dict:
    from personalfinance.analysis.capital_gains import report_capital_gains
    return report_capital_gains(year=kwargs.get("year"))


def _run_transactions(**kwargs) -> dict:
    from personalfinance.queries import get_transactions
    from datetime import date
    return {
        "transactions": get_transactions(
            date_from=date.fromisoformat(kwargs["date_from"]) if kwargs.get("date_from") else None,
            date_to=date.fromisoformat(kwargs["date_to"]) if kwargs.get("date_to") else None,
            payee=kwargs.get("payee"),
            account=kwargs.get("account"),
        ),
    }


def _run_balances(**kwargs) -> dict:
    from personalfinance.queries import get_balances
    return {"balances": get_balances(account_filter=kwargs.get("account_filter"))}
