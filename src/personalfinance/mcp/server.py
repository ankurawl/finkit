"""FastMCP server exposing personal finance tools."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP

from personalfinance.config import load_config

mcp = FastMCP(
    "Personal Finance Toolkit",
    description="Privacy-first personal finance management built on Beancount v3",
)


@mcp.tool()
def init_ledger(
    path: Annotated[Optional[str], "Path for the ledger file (default: ~/finance/main.beancount)"] = None,
    load_existing: Annotated[bool, "True to load an existing ledger instead of creating new"] = False,
    data_dir: Annotated[Optional[str], "Data directory (default: ~/finance)"] = None,
) -> dict:
    """Create a new ledger with default accounts, or load an existing one. New: writes starter template. Load: validates file, discovers accounts/commodities."""
    from personalfinance.operations import init_ledger as _init
    return _init(path=path, load_existing=load_existing, data_dir=data_dir)


@mcp.tool()
def open_account(
    account: Annotated[str, "Full account path (e.g., Assets:Chase:Checking)"],
    currencies: Annotated[Optional[list[str]], "Currencies for this account (default: [USD])"] = None,
    booking: Annotated[Optional[str], "Booking method: FIFO, LIFO, HIFO, AVERAGE, STRICT"] = None,
    date_str: Annotated[Optional[str], "Open date as YYYY-MM-DD (default: 2020-01-01)"] = None,
) -> dict:
    """Open a new account in the ledger with optional booking method for investments."""
    from personalfinance.operations import open_account as _open
    date_ = date.fromisoformat(date_str) if date_str else None
    return _open(account=account, currencies=currencies, booking=booking, date_=date_)


@mcp.tool()
def submit_transaction(
    date_str: Annotated[str, "Transaction date as YYYY-MM-DD"],
    narration: Annotated[str, "Description of the transaction"],
    postings: Annotated[list[dict], "List of postings, each with 'account', 'amount' (number or null for auto-balance), and optional 'currency'"],
    payee: Annotated[Optional[str], "Payee name (merchant, employer, etc.)"] = None,
    tags: Annotated[Optional[list[str]], "Tags for the transaction"] = None,
    links: Annotated[Optional[list[str]], "Links to related transactions"] = None,
    metadata: Annotated[Optional[dict[str, str]], "Key-value metadata"] = None,
) -> dict:
    """Add a transaction to the ledger. Uses fuzzy account matching with confidence gate — if a match is below 0.85 confidence, returns top 3 candidates for user to select. Every transaction gets a UUID tag for stable identification."""
    from personalfinance.operations import submit_transaction as _submit
    date_ = date.fromisoformat(date_str)
    tag_set = set(tags) if tags else None
    link_set = set(links) if links else None
    return _submit(
        date_=date_, payee=payee, narration=narration,
        postings=postings, tags=tag_set, links=link_set, metadata=metadata,
    )


@mcp.tool()
def amend_transaction(
    uuid: Annotated[str, "UUID of the transaction to modify (8-char hex)"],
    date_str: Annotated[Optional[str], "New date as YYYY-MM-DD"] = None,
    payee: Annotated[Optional[str], "New payee"] = None,
    narration: Annotated[Optional[str], "New narration"] = None,
    postings: Annotated[Optional[list[dict]], "New postings (replaces all existing postings)"] = None,
    delete: Annotated[bool, "Set to true to delete the transaction entirely"] = False,
) -> dict:
    """Edit or delete a transaction by its UUID tag. Only provided fields are changed; omitted fields keep their original values."""
    from personalfinance.operations import amend_transaction as _amend
    date_ = date.fromisoformat(date_str) if date_str else None
    return _amend(uuid=uuid, date_=date_, payee=payee, narration=narration, postings=postings, delete=delete)


@mcp.tool()
def assert_balance(
    account: Annotated[str, "Account to check (e.g., Assets:Chase:Checking)"],
    expected_amount: Annotated[str, "Expected balance amount"],
    date_str: Annotated[Optional[str], "Balance date as YYYY-MM-DD (default: today)"] = None,
    currency: Annotated[Optional[str], "Currency (default: USD)"] = None,
    write_directive: Annotated[bool, "Whether to write a balance directive to the ledger"] = True,
) -> dict:
    """Write a balance assertion and verify against the ledger. Reports match/mismatch with the difference."""
    from personalfinance.operations import assert_balance as _assert
    date_ = date.fromisoformat(date_str) if date_str else None
    return _assert(
        account=account, expected_amount=Decimal(expected_amount),
        date_=date_, currency=currency, write_directive=write_directive,
    )


@mcp.tool()
def query(
    sql: Annotated[str, "Beanquery SQL query (read-only)"],
) -> dict:
    """Execute a raw beanquery SQL query against the ledger. Power-user escape hatch for anything the structured tools can't do. Read-only."""
    from personalfinance.queries import run_query
    try:
        results = run_query(sql)
        return {"status": "ok", "rows": results, "count": len(results)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_balances(
    account_filter: Annotated[Optional[str], "Account filter with wildcards (e.g., Assets:*, Liabilities:CreditCard)"] = None,
    date_str: Annotated[Optional[str], "Balance date as YYYY-MM-DD (default: current)"] = None,
    currency: Annotated[Optional[str], "Filter by currency"] = None,
) -> dict:
    """Get account balances, optionally filtered by account pattern, date, or currency."""
    from personalfinance.queries import get_balances as _balances
    date_ = date.fromisoformat(date_str) if date_str else None
    results = _balances(account_filter=account_filter, date_=date_, currency=currency)
    return {"status": "ok", "balances": results, "count": len(results)}


@mcp.tool()
def get_transactions(
    date_from: Annotated[Optional[str], "Start date as YYYY-MM-DD"] = None,
    date_to: Annotated[Optional[str], "End date as YYYY-MM-DD"] = None,
    payee: Annotated[Optional[str], "Filter by payee (substring match)"] = None,
    account: Annotated[Optional[str], "Filter by account (substring match)"] = None,
    tags: Annotated[Optional[list[str]], "Filter by tags (all must match)"] = None,
    amount_min: Annotated[Optional[str], "Minimum amount"] = None,
    amount_max: Annotated[Optional[str], "Maximum amount"] = None,
    uuid: Annotated[Optional[str], "Find specific transaction by UUID"] = None,
) -> dict:
    """Search transactions with structured filters: date range, payee, account, tags, amount range, or UUID."""
    from personalfinance.queries import get_transactions as _txns
    results = _txns(
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        payee=payee, account=account, tags=tags,
        amount_min=Decimal(amount_min) if amount_min else None,
        amount_max=Decimal(amount_max) if amount_max else None,
        uuid=uuid,
    )
    return {"status": "ok", "transactions": results, "count": len(results)}


# === Phase 3 tools (import, market, categorize) ===

@mcp.tool()
def import_file(
    file_path: Annotated[str, "Path to CSV, XLS, or XLSX file"],
    account: Annotated[str, "Target account for imported transactions (e.g., Assets:Chase:Checking)"],
    mapping_name: Annotated[Optional[str], "Name of saved column mapping to reuse"] = None,
    confirm_mapping: Annotated[Optional[dict], "Confirmed column mapping from phase 1 (date_col, amount_col, payee_col, etc.)"] = None,
    sheet_name: Annotated[Optional[str], "Sheet name for multi-sheet workbooks"] = None,
) -> dict:
    """Import transactions from CSV, XLS, or XLSX. Two-phase flow: Phase 1 auto-detects columns and returns proposed mapping. Phase 2 (provide confirm_mapping) applies the mapping and imports transactions with deduplication."""
    from personalfinance.importers.file_importer import import_file as _import
    return _import(
        file_path=file_path, account=account,
        mapping_name=mapping_name, confirm_mapping=confirm_mapping,
        sheet_name=sheet_name,
    )


@mcp.tool()
def import_pdf(
    file_path: Annotated[str, "Path to PDF file"],
    password: Annotated[Optional[str], "PDF password (used in-memory only, never stored)"] = None,
    passwords: Annotated[Optional[list[str]], "List of candidate passwords to try"] = None,
) -> dict:
    """Extract text and tables from a PDF bank/brokerage statement. Supports password-protected PDFs. Returns structured content for interpretation — with LLM: identifies transactions; without: dumps tables as CSV."""
    from personalfinance.importers.pdf_extractor import extract_pdf
    return extract_pdf(file_path=file_path, password=password, passwords=passwords)


@mcp.tool()
def fetch_prices(
    commodities: Annotated[Optional[list[str]], "Specific commodities to fetch (default: all held)"] = None,
    manual_prices: Annotated[Optional[dict[str, str]], "Manual prices for unlisted assets: {commodity: price}"] = None,
) -> dict:
    """Fetch current market prices for held commodities via public APIs (yfinance, CoinGecko, forex). Writes Price directives. Also accepts manual prices for unlisted assets."""
    from personalfinance.market.fetcher import fetch_prices as _fetch
    return _fetch(commodities=commodities, manual_prices=manual_prices)


# === Phase 4 tools (analysis, export) ===

@mcp.tool()
def analyze_spending(
    date_from: Annotated[Optional[str], "Start date as YYYY-MM-DD"] = None,
    date_to: Annotated[Optional[str], "End date as YYYY-MM-DD"] = None,
    group_by: Annotated[str, "Group by: category, month, payee"] = "category",
) -> dict:
    """Analyze spending and income with breakdowns by category, month, or payee. Includes totals, trends, and anomaly detection."""
    from personalfinance.analysis.spending import analyze_spending as _analyze
    return _analyze(
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        group_by=group_by,
    )


@mcp.tool()
def analyze_portfolio(
    date_str: Annotated[Optional[str], "Valuation date as YYYY-MM-DD (default: today)"] = None,
) -> dict:
    """Analyze investment portfolio: net worth, holdings with allocation %, unrealized gain/loss per lot, total portfolio value at current market prices."""
    from personalfinance.analysis.portfolio import analyze_portfolio as _analyze
    date_ = date.fromisoformat(date_str) if date_str else None
    return _analyze(date_=date_)


@mcp.tool()
def report_capital_gains(
    year: Annotated[Optional[int], "Tax year (default: current year)"] = None,
) -> dict:
    """Report realized capital gains/losses grouped by short-term vs long-term. Lists each lot disposition with buy date, sell date, quantity, proceeds, cost basis, and gain/loss."""
    from personalfinance.analysis.capital_gains import report_capital_gains as _report
    return _report(year=year)


@mcp.tool()
def what_if_sell(
    commodity: Annotated[str, "Commodity to sell (e.g., AAPL, BTC)"],
    quantity: Annotated[str, "Number of units to sell"],
    price: Annotated[str, "Hypothetical sell price per unit"],
    currency: Annotated[Optional[str], "Price currency (default: USD)"] = None,
    account: Annotated[Optional[str], "Specific account to sell from"] = None,
) -> dict:
    """Simulate selling shares/crypto: which lots get sold (per booking method), realized gain/loss, short vs long term split. Does NOT modify the ledger."""
    from personalfinance.analysis.whatif import what_if_sell as _whatif
    return _whatif(
        commodity=commodity,
        quantity=Decimal(quantity),
        price=Decimal(price),
        currency=currency,
        account=account,
    )


@mcp.tool()
def export(
    tool_name: Annotated[str, "Name of the tool whose output to export (e.g., analyze_spending, get_transactions)"],
    format: Annotated[str, "Output format: csv or json"] = "csv",
    output_path: Annotated[Optional[str], "File path to write (default: returns as string)"] = None,
    **kwargs,
) -> dict:
    """Export any tool's output as CSV or JSON for external use (spreadsheet, accountant, etc.)."""
    from personalfinance.analysis.export import export_output
    return export_output(tool_name=tool_name, format=format, output_path=output_path, **kwargs)


def run():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run()
