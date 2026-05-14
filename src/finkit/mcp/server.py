from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP

from finkit.config import Settings, load_settings
from finkit.db import Database

mcp = FastMCP("finkit")

_settings: Settings | None = None
_db: Database | None = None


def _get_db() -> Database:
    global _settings, _db
    if _db is None:
        _settings = load_settings()
        _db = Database(_settings.db_path)
        _db.connect()
    return _db


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


@mcp.tool()
def init_ledger() -> dict:
    """Create or connect to the finkit database and initialize schema."""
    try:
        from finkit.operations import init_ledger as _init_ledger

        db = _get_db()
        return _init_ledger(db)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def open_account(
    name: Annotated[str, "Colon-separated account name, e.g. Assets:Chase:Checking"],
    type: Annotated[str, "Account type: Assets, Liabilities, Income, Expenses, or Equity"],
    currency: Annotated[str, "Default currency for the account"] = "USD",
    booking_method: Annotated[str | None, "Lot booking method: FIFO, LIFO, or HIFO"] = None,
    institution: Annotated[str | None, "Financial institution name"] = None,
    asset_class: Annotated[str | None, "Asset class: equity, debt, crypto, cash, etc."] = None,
    jurisdiction: Annotated[str | None, "Tax jurisdiction: US, IN, etc."] = None,
) -> dict:
    """Open a new account in the ledger."""
    try:
        from finkit.operations import open_account as _open_account

        db = _get_db()
        return _open_account(
            db,
            name=name,
            type=type,
            currency=currency,
            booking_method=booking_method,
            institution=institution,
            asset_class=asset_class,
            jurisdiction=jurisdiction,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def submit_transaction(
    date: Annotated[str, "Transaction date in YYYY-MM-DD format"],
    postings: Annotated[list[dict], "List of posting dicts with account, amount, currency, and optional price/cost fields"],
    payee: Annotated[str | None, "Payee name"] = None,
    narration: Annotated[str | None, "Transaction description"] = None,
    tags: Annotated[list[str] | None, "Tags for categorization"] = None,
    status: Annotated[str, "Transaction status: cleared, pending, or voided"] = "cleared",
) -> dict:
    """Submit a new double-entry transaction. Postings must sum to zero."""
    try:
        from finkit.operations import submit_transaction as _submit_transaction

        db = _get_db()
        return _submit_transaction(
            db,
            date=date,
            postings=postings,
            payee=payee,
            narration=narration,
            tags=tags,
            status=status,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def amend_transaction(
    uuid: Annotated[str, "8-char hex UUID of the transaction to amend"],
    updates: Annotated[dict | None, "Fields to update: date, payee, narration, status, postings"] = None,
    delete: Annotated[bool, "If true, delete the transaction instead of amending"] = False,
) -> dict:
    """Amend or delete an existing transaction by UUID."""
    try:
        from finkit.operations import amend_transaction as _amend_transaction

        db = _get_db()
        return _amend_transaction(db, uuid=uuid, updates=updates, delete=delete)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def assert_balance(
    account_name: Annotated[str, "Account name to check"],
    date: Annotated[str, "Date to check balance as of (YYYY-MM-DD)"],
    expected_amount: Annotated[str, "Expected balance amount as a decimal string"],
    currency: Annotated[str, "Currency of the expected balance"] = "USD",
) -> dict:
    """Assert that an account has the expected balance on a given date."""
    try:
        from finkit.operations import assert_balance as _assert_balance

        db = _get_db()
        return _assert_balance(
            db,
            account_name=account_name,
            date=date,
            expected_amount=expected_amount,
            currency=currency,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def query(
    sql: Annotated[str, "SQL query to execute (read-only, SELECT statements only)"],
) -> list[dict] | dict:
    """Run an ad-hoc read-only SQL query against the database."""
    try:
        from finkit.queries import run_query

        db = _get_db()
        return run_query(db, sql=sql)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_balances(
    account_name: Annotated[str | None, "Filter by account name (fuzzy match)"] = None,
    account_type: Annotated[str | None, "Filter by account type: Assets, Liabilities, etc."] = None,
    as_of_date: Annotated[str | None, "Balance as of this date (YYYY-MM-DD), defaults to today"] = None,
) -> list[dict] | dict:
    """Get current balances for accounts."""
    try:
        from finkit.queries import get_balances as _get_balances

        db = _get_db()
        return _get_balances(db, account_name=account_name, account_type=account_type, as_of_date=as_of_date)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_transactions(
    date_from: Annotated[str | None, "Start date filter (YYYY-MM-DD)"] = None,
    date_to: Annotated[str | None, "End date filter (YYYY-MM-DD)"] = None,
    payee: Annotated[str | None, "Filter by payee name (fuzzy match)"] = None,
    account_name: Annotated[str | None, "Filter by account name"] = None,
    tags: Annotated[list[str] | None, "Filter by tags"] = None,
    amount_min: Annotated[str | None, "Minimum posting amount filter"] = None,
    amount_max: Annotated[str | None, "Maximum posting amount filter"] = None,
    uuid: Annotated[str | None, "Filter by transaction UUID"] = None,
    status: Annotated[str | None, "Filter by status: cleared, pending, voided"] = None,
    limit: Annotated[int, "Maximum number of transactions to return"] = 100,
) -> list[dict] | dict:
    """Search and retrieve transactions with optional filters."""
    try:
        from finkit.queries import get_transactions as _get_transactions

        db = _get_db()
        return _get_transactions(
            db,
            date_from=date_from,
            date_to=date_to,
            payee=payee,
            account_name=account_name,
            tags=tags,
            amount_min=amount_min,
            amount_max=amount_max,
            uuid=uuid,
            status=status,
            limit=limit,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def import_file(
    file_path: Annotated[str, "Path to the CSV, XLSX, or PDF file to import"],
    account_name: Annotated[str, "Target account for imported transactions"],
    mapping_name: Annotated[str | None, "Name of a saved column mapping to use"] = None,
    institution: Annotated[str | None, "Financial institution (e.g. chase, schwab)"] = None,
) -> dict:
    """Import transactions from a CSV, XLSX, or PDF file into the ledger."""
    try:
        from finkit.importers.file_importer import import_file as _import_file

        db = _get_db()
        settings = _get_settings()
        return _import_file(
            db,
            settings=settings,
            file_path=file_path,
            account_name=account_name,
            mapping_name=mapping_name,
            institution=institution,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def import_pdf(
    file_path: Annotated[str, "Path to the PDF statement to extract tables from"],
    password: Annotated[str | None, "Password for encrypted PDF files"] = None,
) -> dict:
    """Extract raw text and tables from a PDF statement. For extraction only — use import_file to create transactions."""
    try:
        from finkit.importers.pdf_extractor import extract_pdf

        return extract_pdf(file_path=file_path, password=password)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def fetch_prices(
    symbols: Annotated[list[str] | None, "Stock/ETF ticker symbols to fetch (e.g. ['AAPL', 'VTI'])"] = None,
    coins: Annotated[list[str] | None, "Cryptocurrency IDs to fetch (e.g. ['bitcoin', 'ethereum'])"] = None,
    forex_pairs: Annotated[list[str] | None, "Forex pairs to fetch (e.g. ['USD/INR', 'EUR/USD'])"] = None,
) -> dict:
    """Fetch latest market prices for stocks, crypto, and forex pairs."""
    try:
        from finkit.market.fetcher import fetch_prices as _fetch_prices

        db = _get_db()
        settings = _get_settings()
        return _fetch_prices(
            db,
            settings=settings,
            symbols=symbols,
            coins=coins,
            forex_pairs=forex_pairs,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def analyze_spending(
    year_month: Annotated[str | None, "Month to analyze (YYYY-MM), defaults to current month"] = None,
    months: Annotated[int, "Number of months to include in trend analysis"] = 6,
    category: Annotated[str | None, "Filter to a specific expense category"] = None,
    currency: Annotated[str, "Currency for aggregation"] = "USD",
) -> dict:
    """Analyze spending patterns by category with month-over-month trends."""
    try:
        from finkit.analysis.spending import analyze_spending as _analyze_spending

        db = _get_db()
        return _analyze_spending(
            db,
            year_month=year_month,
            months=months,
            category=category,
            currency=currency,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def analyze_portfolio(
    currency: Annotated[str | None, "Currency for valuation, defaults to base currency"] = None,
) -> dict:
    """Analyze investment portfolio: holdings, allocation, and unrealized gains."""
    try:
        from finkit.analysis.portfolio import analyze_portfolio as _analyze_portfolio

        db = _get_db()
        settings = _get_settings()
        return _analyze_portfolio(db, settings=settings, currency=currency)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def report_capital_gains(
    year: Annotated[int | None, "Tax year to report, defaults to current year"] = None,
    currency: Annotated[str | None, "Currency for the report"] = None,
) -> dict:
    """Generate capital gains report for tax filing."""
    try:
        from finkit.analysis.capital_gains import report_capital_gains as _report_capital_gains

        db = _get_db()
        settings = _get_settings()
        return _report_capital_gains(db, settings=settings, year=year, currency=currency)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def what_if_sell(
    account_name: Annotated[str, "Investment account holding the commodity"],
    commodity: Annotated[str, "Ticker/symbol to simulate selling"],
    quantity: Annotated[str, "Number of units to sell (decimal string)"],
    booking_method: Annotated[str, "Lot selection method: FIFO, LIFO, or HIFO"] = "FIFO",
    sell_price: Annotated[str | None, "Assumed sell price per unit; uses latest market price if omitted"] = None,
) -> dict:
    """Simulate selling a position to preview capital gains impact."""
    try:
        from finkit.analysis.whatif import what_if_sell as _what_if_sell

        db = _get_db()
        settings = _get_settings()
        return _what_if_sell(
            db,
            settings=settings,
            account_name=account_name,
            commodity=commodity,
            quantity=quantity,
            booking_method=booking_method,
            sell_price=sell_price,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def export(
    data_type: Annotated[str, "Type of data to export: transactions, balances, or custom"],
    format: Annotated[str, "Output format: csv or json"] = "csv",
    sql: Annotated[str | None, "Custom SQL query for data_type='custom'"] = None,
    file_path: Annotated[str | None, "Destination file path; returns data inline if omitted"] = None,
) -> dict:
    """Export ledger data as CSV or JSON."""
    try:
        from finkit.analysis.export import export_csv, export_json

        db = _get_db()
        if format == "json":
            return export_json(db, data_type=data_type, sql=sql, file_path=file_path)
        return export_csv(db, data_type=data_type, sql=sql, file_path=file_path)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def categorize(
    action: Annotated[str, "Action to perform: add, remove, or list"],
    pattern: Annotated[str | None, "Payee pattern to match (required for add)"] = None,
    target_account: Annotated[str | None, "Expense/income account to categorize into (required for add)"] = None,
    pattern_type: Annotated[str, "Match type: substring, regex, or exact"] = "substring",
    rule_id: Annotated[int | None, "Rule ID to remove (required for remove)"] = None,
    institution: Annotated[str | None, "Limit rule to a specific institution"] = None,
) -> dict:
    """Manage categorization rules for auto-categorizing transactions."""
    try:
        from finkit.categorize.rules import add_rule, list_rules, remove_rule

        db = _get_db()
        if action == "add":
            return add_rule(
                db,
                pattern=pattern,
                target_account=target_account,
                pattern_type=pattern_type,
                institution=institution,
            )
        elif action == "remove":
            return remove_rule(db, rule_id=rule_id)
        elif action == "list":
            return list_rules(db, institution=institution)
        else:
            return {"error": f"Unknown action: {action}. Use add, remove, or list."}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def corporate_action(
    commodity: Annotated[str, "Ticker/symbol affected by the action"],
    action_type: Annotated[str, "Type of corporate action: split, reverse_split, spinoff, merger"],
    ratio: Annotated[str, "Action ratio as a decimal string (e.g. '2' for 2:1 split)"],
    date: Annotated[str | None, "Date of the corporate action (YYYY-MM-DD)"] = None,
    narration: Annotated[str | None, "Description of the corporate action"] = None,
) -> dict:
    """Record a corporate action (stock split, merger, etc.) and adjust lots."""
    try:
        from finkit.operations import corporate_action as _corporate_action

        db = _get_db()
        return _corporate_action(
            db,
            commodity=commodity,
            action_type=action_type,
            ratio=ratio,
            date=date,
            narration=narration,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def undo_import(
    source_file_id: Annotated[int, "ID of the source file whose import to reverse"],
) -> dict:
    """Undo a file import by removing all transactions and data from that file."""
    try:
        from finkit.operations import undo_import as _undo_import

        db = _get_db()
        return _undo_import(db, source_file_id=source_file_id)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def import_directory(
    source_dir: Annotated[str, "Path to the directory containing statement files"],
    account_name: Annotated[str, "Target account for all imported transactions"],
    institution: Annotated[str | None, "Financial institution for all files in the directory"] = None,
    glob_pattern: Annotated[str, "File pattern to match"] = "*.csv",
    recursive: Annotated[bool, "Whether to search subdirectories"] = True,
    mapping_name: Annotated[str | None, "Name of a saved column mapping to use"] = None,
) -> dict:
    """Batch import all matching files from a directory."""
    try:
        from finkit.importers.directory_importer import import_directory as _import_directory

        db = _get_db()
        settings = _get_settings()
        return _import_directory(
            db,
            settings=settings,
            source_dir=source_dir,
            account_name=account_name,
            institution=institution,
            glob_pattern=glob_pattern,
            recursive=recursive,
            mapping_name=mapping_name,
        )
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
