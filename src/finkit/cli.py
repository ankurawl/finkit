from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from finkit.config import load_settings
from finkit.db import Database, get_db


def _output(data) -> None:
    print(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Handler functions
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    from finkit.operations import init_ledger

    settings = load_settings(data_dir=args.data_dir)
    db = init_ledger(settings)
    db.close()
    _output({"status": "ok", "db_path": str(settings.db_path)})


def cmd_open_account(args: argparse.Namespace) -> None:
    from finkit.operations import open_account

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        account_id = open_account(
            db,
            name=args.name,
            type=args.type,
            currency=args.currency,
            booking_method=args.booking_method,
            institution=args.institution,
            asset_class=args.asset_class,
            jurisdiction=args.jurisdiction,
        )
    _output({"account_id": account_id})


def cmd_submit(args: argparse.Namespace) -> None:
    from finkit.operations import submit_transaction

    settings = load_settings(data_dir=args.data_dir)
    postings = json.loads(args.postings)
    tags = args.tags.split(",") if args.tags else None

    with get_db(settings) as db:
        uuid = submit_transaction(
            db,
            date=args.date,
            postings=postings,
            payee=args.payee,
            narration=args.narration,
            tags=tags,
            status=args.status,
            settings=settings,
        )
    _output({"uuid": uuid})


def cmd_amend(args: argparse.Namespace) -> None:
    from finkit.operations import amend_transaction

    settings = load_settings(data_dir=args.data_dir)
    updates = json.loads(args.updates) if args.updates else None

    with get_db(settings) as db:
        amend_transaction(
            db,
            uuid=args.uuid,
            updates=updates,
            delete=args.delete,
            settings=settings,
        )
    _output({"status": "ok"})


def cmd_assert_balance(args: argparse.Namespace) -> None:
    from finkit.operations import assert_balance as assert_balance_op

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = assert_balance_op(
            db,
            account_name=args.account,
            date=args.date,
            expected_amount=args.amount,
            currency=args.currency,
        )
    _output(result)


def cmd_query(args: argparse.Namespace) -> None:
    from finkit.queries import run_query

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        rows = run_query(db, args.sql)
    _output(rows)


def cmd_balances(args: argparse.Namespace) -> None:
    from finkit.queries import get_balances

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        rows = get_balances(
            db,
            account_name=args.account,
            account_type=args.type,
            as_of_date=args.as_of,
        )
    _output(rows)


def cmd_transactions(args: argparse.Namespace) -> None:
    from finkit.queries import get_transactions

    settings = load_settings(data_dir=args.data_dir)
    tags = args.tags.split(",") if args.tags else None

    with get_db(settings) as db:
        rows = get_transactions(
            db,
            date_from=getattr(args, "from"),
            date_to=args.to,
            payee=args.payee,
            account_name=args.account,
            tags=tags,
            uuid=args.uuid,
            status=args.status,
            limit=args.limit,
        )
    _output(rows)


def cmd_import(args: argparse.Namespace) -> None:
    from finkit.importers.file_importer import import_file

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = import_file(
            db,
            file_path=Path(args.file_path),
            account_name=args.account,
            mapping_name=args.mapping,
            institution=args.institution,
            settings=settings,
        )
    _output(result)


def cmd_import_pdf(args: argparse.Namespace) -> None:
    from finkit.importers.pdf_extractor import extract_pdf

    result = extract_pdf(
        file_path=Path(args.file_path),
        password=args.password,
    )
    _output(result)


def cmd_import_dir(args: argparse.Namespace) -> None:
    from finkit.importers.directory_importer import import_directory

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = import_directory(
            db,
            source_dir=Path(args.source_dir),
            account_name=args.account,
            institution=args.institution,
            glob_pattern=args.glob,
            recursive=args.recursive,
            mapping_name=args.mapping,
            settings=settings,
        )
    _output(result)


def cmd_fetch_prices(args: argparse.Namespace) -> None:
    from finkit.market.fetcher import fetch_prices

    settings = load_settings(data_dir=args.data_dir)
    symbols = args.symbols.split(",") if args.symbols else None
    coins = args.coins.split(",") if args.coins else None
    forex_pairs = None
    if args.forex_pairs:
        forex_pairs = []
        for pair in args.forex_pairs.split(","):
            base, quote = pair.strip().split("/")
            forex_pairs.append((base.strip(), quote.strip()))

    with get_db(settings) as db:
        result = fetch_prices(
            db,
            symbols=symbols,
            coins=coins,
            forex_pairs=forex_pairs,
            settings=settings,
        )
    _output(result)


def cmd_manual_price(args: argparse.Namespace) -> None:
    from finkit.market.fetcher import manual_price

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        manual_price(
            db,
            commodity=args.commodity,
            currency=args.currency,
            price=args.price,
            date=args.date,
        )
    _output({"status": "ok"})


def cmd_spending(args: argparse.Namespace) -> None:
    from finkit.analysis.spending import analyze_spending

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = analyze_spending(
            db,
            year_month=args.month,
            months=args.months,
            category=args.category,
            currency=args.currency,
        )
    _output(result)


def cmd_portfolio(args: argparse.Namespace) -> None:
    from finkit.analysis.portfolio import analyze_portfolio

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = analyze_portfolio(db, currency=args.currency)
    _output(result)


def cmd_capital_gains(args: argparse.Namespace) -> None:
    from finkit.analysis.capital_gains import report_capital_gains

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = report_capital_gains(
            db,
            year=args.year,
            currency=args.currency,
        )
    _output(result)


def cmd_what_if(args: argparse.Namespace) -> None:
    from finkit.analysis.whatif import what_if_sell

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = what_if_sell(
            db,
            account=args.account,
            commodity=args.commodity,
            quantity=args.quantity,
            method=args.method,
            price=args.price,
        )
    _output(result)


def cmd_export(args: argparse.Namespace) -> None:
    from finkit.analysis.export import export_csv, export_json

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        if args.format == "csv":
            result = export_csv(db, sql=args.sql, output=args.output)
        else:
            result = export_json(db, sql=args.sql, output=args.output)
    _output(result)


def cmd_categorize_add(args: argparse.Namespace) -> None:
    from finkit.categorize.rules import add_rule

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        rule_id = add_rule(
            db,
            pattern=args.pattern,
            target_account=args.target_account,
            pattern_type=args.pattern_type,
            institution=args.institution,
            priority=args.priority,
        )
    _output({"rule_id": rule_id})


def cmd_categorize_remove(args: argparse.Namespace) -> None:
    from finkit.categorize.rules import remove_rule

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        removed = remove_rule(db, rule_id=args.rule_id)
    _output({"removed": removed})


def cmd_categorize_list(args: argparse.Namespace) -> None:
    from finkit.categorize.rules import list_rules

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        rules = list_rules(db, institution=args.institution)
    _output([
        {
            "id": r.id,
            "pattern": r.pattern,
            "pattern_type": r.pattern_type,
            "target_account": r.target_account,
            "institution": r.institution,
            "priority": r.priority,
        }
        for r in rules
    ])


def cmd_corporate_action(args: argparse.Namespace) -> None:
    from finkit.operations import corporate_action as corporate_action_op

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = corporate_action_op(
            db,
            commodity=args.commodity,
            action_type=args.action_type,
            ratio=args.ratio,
            date=args.date,
            narration=args.narration,
        )
    _output(result)


def cmd_undo_import(args: argparse.Namespace) -> None:
    from finkit.operations import undo_import as undo_import_op

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        result = undo_import_op(db, source_file_id=args.source_file_id)
    _output(result)


def cmd_rebuild(args: argparse.Namespace) -> None:
    from finkit.summaries.registry import SummaryRegistry

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        SummaryRegistry.rebuild_all(db)
        db.conn.commit()
    _output({"status": "ok", "tables": SummaryRegistry.get_registered()})


def cmd_backup(args: argparse.Namespace) -> None:
    settings = load_settings(data_dir=args.data_dir)
    dest = Path(args.dest_path)
    with get_db(settings) as db:
        db.backup(dest)
    _output({"status": "ok", "backup_path": str(dest)})


def cmd_accounts(args: argparse.Namespace) -> None:
    from finkit.queries import list_accounts

    settings = load_settings(data_dir=args.data_dir)
    with get_db(settings) as db:
        rows = list_accounts(db, account_type=args.type)
    _output(rows)


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finkit",
        description="Privacy-first personal/family finance toolkit",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override the data directory (default: ~/finance)",
    )

    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Initialize a new ledger")

    # open-account
    p = sub.add_parser("open-account", help="Open a new account")
    p.add_argument("name", help="Account name (e.g. Assets:Chase:Checking)")
    p.add_argument("--type", required=True, help="Account type (Assets, Liabilities, Income, Expenses, Equity)")
    p.add_argument("--currency", default="USD")
    p.add_argument("--booking-method", default=None)
    p.add_argument("--institution", default=None)
    p.add_argument("--asset-class", default=None)
    p.add_argument("--jurisdiction", default=None)

    # submit
    p = sub.add_parser("submit", help="Submit a new transaction")
    p.add_argument("--date", required=True)
    p.add_argument("--payee", default=None)
    p.add_argument("--narration", default=None)
    p.add_argument("--postings", required=True, help="JSON array of posting objects")
    p.add_argument("--tags", default=None, help="Comma-separated tags")
    p.add_argument("--status", default="cleared")

    # amend
    p = sub.add_parser("amend", help="Amend or delete a transaction")
    p.add_argument("uuid", help="Transaction UUID")
    p.add_argument("--updates", default=None, help="JSON object with fields to update")
    p.add_argument("--delete", action="store_true", help="Delete the transaction")

    # assert-balance
    p = sub.add_parser("assert-balance", help="Assert an account balance on a date")
    p.add_argument("account", help="Account name")
    p.add_argument("date", help="Date (YYYY-MM-DD)")
    p.add_argument("amount", help="Expected balance amount")
    p.add_argument("--currency", default="USD")

    # query
    p = sub.add_parser("query", help="Run a read-only SQL query")
    p.add_argument("sql", help="SQL statement")

    # balances
    p = sub.add_parser("balances", help="Show account balances")
    p.add_argument("--account", default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--as-of", default=None, help="As-of date (YYYY-MM-DD)")

    # transactions
    p = sub.add_parser("transactions", help="List transactions")
    p.add_argument("--from", default=None, dest="from", help="Start date")
    p.add_argument("--to", default=None, help="End date")
    p.add_argument("--payee", default=None)
    p.add_argument("--account", default=None)
    p.add_argument("--tags", default=None, help="Comma-separated tags")
    p.add_argument("--uuid", default=None)
    p.add_argument("--status", default=None)
    p.add_argument("--limit", type=int, default=100)

    # import
    p = sub.add_parser("import", help="Import a statement file")
    p.add_argument("file_path", help="Path to the file")
    p.add_argument("account", help="Target account name")
    p.add_argument("--mapping", default=None, help="Column mapping name")
    p.add_argument("--institution", default=None)

    # import-pdf
    p = sub.add_parser("import-pdf", help="Extract tables and text from a PDF")
    p.add_argument("file_path", help="Path to the PDF file")
    p.add_argument("--password", default=None)

    # import-dir
    p = sub.add_parser("import-dir", help="Import all files from a directory")
    p.add_argument("source_dir", help="Source directory path")
    p.add_argument("account", help="Target account name")
    p.add_argument("--institution", default=None)
    p.add_argument("--glob", default="*.csv", help="Glob pattern (default: *.csv)")
    p.add_argument("--recursive", action="store_true", default=True)
    p.add_argument("--no-recursive", action="store_false", dest="recursive")
    p.add_argument("--mapping", default=None, help="Column mapping name")

    # fetch-prices
    p = sub.add_parser("fetch-prices", help="Fetch market prices")
    p.add_argument("--symbols", default=None, help="Comma-separated stock symbols")
    p.add_argument("--coins", default=None, help="Comma-separated CoinGecko coin IDs")
    p.add_argument("--forex-pairs", default=None, help="Comma-separated forex pairs (e.g. USD/INR,EUR/USD)")

    # manual-price
    p = sub.add_parser("manual-price", help="Record a manual price entry")
    p.add_argument("commodity", help="Commodity symbol")
    p.add_argument("currency", help="Price currency")
    p.add_argument("price", help="Price value")
    p.add_argument("date", help="Date (YYYY-MM-DD)")

    # spending
    p = sub.add_parser("spending", help="Analyze spending patterns")
    p.add_argument("--month", default=None, help="Year-month (YYYY-MM)")
    p.add_argument("--months", type=int, default=6, help="Number of months to analyze")
    p.add_argument("--category", default=None)
    p.add_argument("--currency", default="USD")

    # portfolio
    p = sub.add_parser("portfolio", help="Analyze portfolio holdings and net worth")
    p.add_argument("--currency", default=None)

    # capital-gains
    p = sub.add_parser("capital-gains", help="Report capital gains and losses")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--currency", default=None)

    # what-if
    p = sub.add_parser("what-if", help="Simulate selling a position")
    p.add_argument("account", help="Account name")
    p.add_argument("commodity", help="Commodity symbol")
    p.add_argument("quantity", help="Quantity to sell")
    p.add_argument("--method", default=None, help="Booking method (FIFO, LIFO, HIFO)")
    p.add_argument("--price", default=None, help="Simulated sell price")

    # export
    p = sub.add_parser("export", help="Export data as CSV or JSON")
    p.add_argument("--format", choices=["csv", "json"], default="csv")
    p.add_argument("--sql", required=True, help="SQL query to export")
    p.add_argument("--output", default=None, help="Output file path")

    # categorize (with subcommands)
    p = sub.add_parser("categorize", help="Manage categorization rules")
    cat_sub = p.add_subparsers(dest="categorize_command")

    p_add = cat_sub.add_parser("add", help="Add a categorization rule")
    p_add.add_argument("pattern", help="Match pattern")
    p_add.add_argument("target_account", help="Target account for matching transactions")
    p_add.add_argument("--pattern-type", default="substring", choices=["substring", "regex", "exact"])
    p_add.add_argument("--institution", default=None)
    p_add.add_argument("--priority", type=int, default=0)

    p_rm = cat_sub.add_parser("remove", help="Remove a categorization rule")
    p_rm.add_argument("rule_id", type=int, help="Rule ID to remove")

    p_ls = cat_sub.add_parser("list", help="List categorization rules")
    p_ls.add_argument("--institution", default=None)

    # corporate-action
    p = sub.add_parser("corporate-action", help="Record a corporate action (split, reverse split)")
    p.add_argument("commodity", help="Commodity symbol")
    p.add_argument("action_type", help="Action type (split, reverse_split)")
    p.add_argument("ratio", help="Split ratio (e.g. 2 for 2:1 split)")
    p.add_argument("--date", default=None)
    p.add_argument("--narration", default=None)

    # undo-import
    p = sub.add_parser("undo-import", help="Undo a file import")
    p.add_argument("source_file_id", type=int, help="Source file ID to undo")

    # rebuild
    sub.add_parser("rebuild", help="Rebuild all summary tables from core data")

    # backup
    p = sub.add_parser("backup", help="Create a database backup")
    p.add_argument("dest_path", help="Destination file path")

    # accounts
    p = sub.add_parser("accounts", help="List accounts")
    p.add_argument("--type", default=None, help="Filter by account type")

    return parser


_COMMAND_HANDLERS = {
    "init": cmd_init,
    "open-account": cmd_open_account,
    "submit": cmd_submit,
    "amend": cmd_amend,
    "assert-balance": cmd_assert_balance,
    "query": cmd_query,
    "balances": cmd_balances,
    "transactions": cmd_transactions,
    "import": cmd_import,
    "import-pdf": cmd_import_pdf,
    "import-dir": cmd_import_dir,
    "fetch-prices": cmd_fetch_prices,
    "manual-price": cmd_manual_price,
    "spending": cmd_spending,
    "portfolio": cmd_portfolio,
    "capital-gains": cmd_capital_gains,
    "what-if": cmd_what_if,
    "export": cmd_export,
    "corporate-action": cmd_corporate_action,
    "undo-import": cmd_undo_import,
    "rebuild": cmd_rebuild,
    "backup": cmd_backup,
    "accounts": cmd_accounts,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "categorize":
        if args.categorize_command is None:
            parser.parse_args(["categorize", "--help"])
            sys.exit(1)
        handler_map = {
            "add": cmd_categorize_add,
            "remove": cmd_categorize_remove,
            "list": cmd_categorize_list,
        }
        handler = handler_map[args.categorize_command]
    else:
        handler = _COMMAND_HANDLERS.get(args.command)
        if handler is None:
            parser.print_help()
            sys.exit(1)

    try:
        handler(args)
    except Exception as exc:
        _output({"error": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
