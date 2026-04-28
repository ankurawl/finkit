"""CLI entry point for finkit — mirrors MCP tools as subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path


def _print_result(result: dict) -> None:
    """Pretty-print a result dict."""
    print(json.dumps(result, indent=2, default=str))


def cmd_init(args: argparse.Namespace) -> None:
    from personalfinance.operations import init_ledger
    result = init_ledger(
        path=args.path,
        load_existing=args.load,
        data_dir=args.data_dir,
    )
    _print_result(result)


def cmd_open_account(args: argparse.Namespace) -> None:
    from personalfinance.operations import open_account
    currencies = args.currency.split(",") if args.currency else None
    date_ = date.fromisoformat(args.date) if args.date else None
    result = open_account(
        account=args.account,
        currencies=currencies,
        booking=args.booking,
        date_=date_,
    )
    _print_result(result)


def cmd_submit(args: argparse.Namespace) -> None:
    from personalfinance.operations import submit_transaction
    postings = json.loads(args.postings)
    tags = set(args.tags.split(",")) if args.tags else None
    date_ = date.fromisoformat(args.date)
    result = submit_transaction(
        date_=date_,
        payee=args.payee,
        narration=args.narration,
        postings=postings,
        tags=tags,
    )
    _print_result(result)


def cmd_amend(args: argparse.Namespace) -> None:
    from personalfinance.operations import amend_transaction
    postings = json.loads(args.postings) if args.postings else None
    date_ = date.fromisoformat(args.date) if args.date else None
    result = amend_transaction(
        uuid=args.uuid,
        date_=date_,
        payee=args.payee,
        narration=args.narration,
        postings=postings,
        delete=args.delete,
    )
    _print_result(result)


def cmd_assert_balance(args: argparse.Namespace) -> None:
    from personalfinance.operations import assert_balance
    date_ = date.fromisoformat(args.date) if args.date else None
    result = assert_balance(
        account=args.account,
        expected_amount=Decimal(args.amount),
        date_=date_,
        currency=args.currency,
    )
    _print_result(result)


def cmd_query(args: argparse.Namespace) -> None:
    from personalfinance.queries import run_query
    results = run_query(args.sql)
    _print_result({"rows": results, "count": len(results)})


def cmd_balances(args: argparse.Namespace) -> None:
    from personalfinance.queries import get_balances
    date_ = date.fromisoformat(args.date) if args.date else None
    results = get_balances(account_filter=args.account, date_=date_, currency=args.currency)
    _print_result({"balances": results, "count": len(results)})


def cmd_transactions(args: argparse.Namespace) -> None:
    from personalfinance.queries import get_transactions
    results = get_transactions(
        date_from=date.fromisoformat(args.date_from) if args.date_from else None,
        date_to=date.fromisoformat(args.date_to) if args.date_to else None,
        payee=args.payee,
        account=args.account,
        uuid=args.uuid,
    )
    _print_result({"transactions": results, "count": len(results)})


def cmd_import(args: argparse.Namespace) -> None:
    from personalfinance.importers.file_importer import import_file
    confirm_mapping = json.loads(args.confirm_mapping) if args.confirm_mapping else None
    result = import_file(
        file_path=args.file,
        account=args.account,
        mapping_name=args.mapping,
        confirm_mapping=confirm_mapping,
        sheet_name=args.sheet,
    )
    _print_result(result)


def cmd_extract_pdf(args: argparse.Namespace) -> None:
    from personalfinance.importers.pdf_extractor import extract_pdf
    passwords = args.passwords.split(",") if args.passwords else None
    result = extract_pdf(
        file_path=args.file,
        password=args.password,
        passwords=passwords,
    )
    _print_result(result)


def cmd_fetch_prices(args: argparse.Namespace) -> None:
    from personalfinance.market.fetcher import fetch_prices
    commodities = args.commodities.split(",") if args.commodities else None
    result = fetch_prices(commodities=commodities)
    _print_result(result)


def cmd_spending(args: argparse.Namespace) -> None:
    from personalfinance.analysis.spending import analyze_spending
    result = analyze_spending(
        date_from=date.fromisoformat(args.date_from) if args.date_from else None,
        date_to=date.fromisoformat(args.date_to) if args.date_to else None,
        group_by=args.group_by,
    )
    _print_result(result)


def cmd_portfolio(args: argparse.Namespace) -> None:
    from personalfinance.analysis.portfolio import analyze_portfolio
    date_ = date.fromisoformat(args.date) if args.date else None
    result = analyze_portfolio(date_=date_)
    _print_result(result)


def cmd_capital_gains(args: argparse.Namespace) -> None:
    from personalfinance.analysis.capital_gains import report_capital_gains
    result = report_capital_gains(year=args.year)
    _print_result(result)


def cmd_whatif_sell(args: argparse.Namespace) -> None:
    from personalfinance.analysis.whatif import what_if_sell
    result = what_if_sell(
        commodity=args.commodity,
        quantity=Decimal(args.quantity),
        price=Decimal(args.price),
        currency=args.currency,
        account=args.account,
    )
    _print_result(result)


def cmd_export(args: argparse.Namespace) -> None:
    from personalfinance.analysis.export import export_output
    result = export_output(
        tool_name=args.tool,
        format=args.format,
        output_path=args.output,
    )
    _print_result(result)


def cmd_categorize(args: argparse.Namespace) -> None:
    from personalfinance.categorize.rules import apply_rules, review_uncategorized
    if args.review:
        result = review_uncategorized()
    elif args.rules_file:
        result = apply_rules(rules_file=args.rules_file)
    else:
        result = apply_rules()
    _print_result(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finkit",
        description="Personal Finance Toolkit — privacy-first finance management on Beancount v3",
    )
    parser.add_argument("--data-dir", help="Data directory (default: ~/finance)")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p = sub.add_parser("init", help="Create or load a ledger")
    p.add_argument("path", nargs="?", help="Ledger file path")
    p.add_argument("--load", action="store_true", help="Load existing ledger")
    p.set_defaults(func=cmd_init)

    # open-account
    p = sub.add_parser("open-account", help="Open a new account")
    p.add_argument("account", help="Account path (e.g., Assets:Chase:Checking)")
    p.add_argument("--currency", help="Currency (default: USD)")
    p.add_argument("--booking", help="Booking method: FIFO, LIFO, HIFO, AVERAGE, STRICT")
    p.add_argument("--date", help="Open date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_open_account)

    # submit
    p = sub.add_parser("submit", help="Add a transaction")
    p.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p.add_argument("--payee", help="Payee name")
    p.add_argument("--narration", required=True, help="Description")
    p.add_argument("--postings", required=True, help='JSON array of postings: [{"account":"...","amount":"...","currency":"..."}]')
    p.add_argument("--tags", help="Comma-separated tags")
    p.set_defaults(func=cmd_submit)

    # amend
    p = sub.add_parser("amend", help="Edit or delete a transaction by UUID")
    p.add_argument("uuid", help="Transaction UUID (8-char hex)")
    p.add_argument("--date", help="New date")
    p.add_argument("--payee", help="New payee")
    p.add_argument("--narration", help="New narration")
    p.add_argument("--postings", help="New postings as JSON")
    p.add_argument("--delete", action="store_true", help="Delete the transaction")
    p.set_defaults(func=cmd_amend)

    # assert-balance
    p = sub.add_parser("assert-balance", help="Assert an account balance")
    p.add_argument("account", help="Account path")
    p.add_argument("amount", help="Expected balance")
    p.add_argument("--date", help="Balance date (YYYY-MM-DD)")
    p.add_argument("--currency", help="Currency")
    p.set_defaults(func=cmd_assert_balance)

    # query
    p = sub.add_parser("query", help="Run a beanquery SQL query")
    p.add_argument("sql", help="SQL query string")
    p.set_defaults(func=cmd_query)

    # balances
    p = sub.add_parser("balances", help="Get account balances")
    p.add_argument("--account", help="Account filter (supports wildcards)")
    p.add_argument("--date", help="Balance date")
    p.add_argument("--currency", help="Filter by currency")
    p.set_defaults(func=cmd_balances)

    # transactions
    p = sub.add_parser("transactions", help="Search transactions")
    p.add_argument("--date-from", help="Start date")
    p.add_argument("--date-to", help="End date")
    p.add_argument("--payee", help="Filter by payee")
    p.add_argument("--account", help="Filter by account")
    p.add_argument("--uuid", help="Find by UUID")
    p.set_defaults(func=cmd_transactions)

    # import
    p = sub.add_parser("import", help="Import transactions from CSV/XLS/XLSX")
    p.add_argument("file", help="Path to file")
    p.add_argument("--account", required=True, help="Target account")
    p.add_argument("--mapping", help="Saved mapping name")
    p.add_argument("--confirm-mapping", help="Confirmed mapping as JSON")
    p.add_argument("--sheet", help="Sheet name for workbooks")
    p.set_defaults(func=cmd_import)

    # extract-pdf
    p = sub.add_parser("extract-pdf", help="Extract text/tables from a PDF")
    p.add_argument("file", help="Path to PDF")
    p.add_argument("--password", help="PDF password")
    p.add_argument("--passwords", help="Comma-separated candidate passwords")
    p.set_defaults(func=cmd_extract_pdf)

    # fetch-prices
    p = sub.add_parser("fetch-prices", help="Fetch market prices")
    p.add_argument("--commodities", help="Comma-separated commodity list")
    p.set_defaults(func=cmd_fetch_prices)

    # spending
    p = sub.add_parser("spending", help="Analyze spending")
    p.add_argument("--date-from", help="Start date")
    p.add_argument("--date-to", help="End date")
    p.add_argument("--group-by", default="category", choices=["category", "month", "payee"])
    p.set_defaults(func=cmd_spending)

    # portfolio
    p = sub.add_parser("portfolio", help="Analyze investment portfolio")
    p.add_argument("--date", help="Valuation date")
    p.set_defaults(func=cmd_portfolio)

    # capital-gains
    p = sub.add_parser("capital-gains", help="Report realized capital gains")
    p.add_argument("--year", type=int, help="Tax year")
    p.set_defaults(func=cmd_capital_gains)

    # whatif-sell
    p = sub.add_parser("whatif-sell", help="Simulate selling shares")
    p.add_argument("commodity", help="Commodity to sell (e.g., AAPL)")
    p.add_argument("quantity", help="Number of units")
    p.add_argument("price", help="Hypothetical price per unit")
    p.add_argument("--currency", default="USD", help="Price currency")
    p.add_argument("--account", help="Specific account to sell from")
    p.set_defaults(func=cmd_whatif_sell)

    # export
    p = sub.add_parser("export", help="Export tool output as CSV/JSON")
    p.add_argument("tool", help="Tool name to export from")
    p.add_argument("--format", default="csv", choices=["csv", "json"])
    p.add_argument("--output", help="Output file path")
    p.set_defaults(func=cmd_export)

    # categorize
    p = sub.add_parser("categorize", help="Categorize transactions")
    p.add_argument("--review", action="store_true", help="Review uncategorized transactions")
    p.add_argument("--rules-file", help="Path to rules JSON file")
    p.add_argument("--apply-rules", action="store_true", help="Apply built-in rules")
    p.set_defaults(func=cmd_categorize)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.data_dir:
        from personalfinance.config import load_config
        load_config(args.data_dir)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
