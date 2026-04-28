"""Interactive local agent using Ollama for fully offline finance management."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any


SYSTEM_PROMPT = """\
You are FinKit, a personal finance assistant running locally via Ollama. \
All data stays on the user's machine — nothing is sent to external services.

You manage a Beancount v3 ledger with tools for accounts, transactions, \
imports, and analysis. Be concise and accurate.

When importing from PDFs:
1. Call import_pdf to extract tables and text from the PDF
2. Examine the extracted tables to identify transactions (date, amount, payee/description)
3. Call open_account if the target account doesn't exist yet
4. Call submit_transaction for each transaction found
5. Use Expenses:Other for outflows and Income:Other for inflows as contra accounts

When the user asks about spending, balances, or portfolio, use the appropriate analysis tool.\
"""


def _tool(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
            },
        },
    }


TOOLS = [
    _tool("init_ledger", "Create a new ledger with default accounts, or load an existing one.", {
        "path": {"type": "string", "description": "Ledger file path (default: ~/finance/main.beancount)"},
        "load_existing": {"type": "boolean", "description": "True to load an existing ledger"},
    }),
    _tool("open_account", "Open a new account in the ledger.", {
        "account": {"type": "string", "description": "Full account path (e.g., Assets:Chase:Checking)"},
        "currencies": {"type": "array", "items": {"type": "string"}, "description": "Currencies (default: [USD])"},
        "booking": {"type": "string", "description": "Booking method: FIFO, LIFO, HIFO, AVERAGE, STRICT"},
        "date_str": {"type": "string", "description": "Open date as YYYY-MM-DD"},
    }, required=["account"]),
    _tool("submit_transaction", "Add a transaction to the ledger.", {
        "date_str": {"type": "string", "description": "Date as YYYY-MM-DD"},
        "narration": {"type": "string", "description": "Description of the transaction"},
        "postings": {
            "type": "array",
            "items": {"type": "object"},
            "description": "List of postings, each with 'account', 'amount', and optional 'currency'",
        },
        "payee": {"type": "string", "description": "Payee name"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
    }, required=["date_str", "narration", "postings"]),
    _tool("amend_transaction", "Edit or delete a transaction by UUID.", {
        "uuid": {"type": "string", "description": "Transaction UUID (8-char hex)"},
        "date_str": {"type": "string", "description": "New date as YYYY-MM-DD"},
        "payee": {"type": "string", "description": "New payee"},
        "narration": {"type": "string", "description": "New narration"},
        "postings": {"type": "array", "items": {"type": "object"}, "description": "New postings"},
        "delete": {"type": "boolean", "description": "Delete the transaction"},
    }, required=["uuid"]),
    _tool("assert_balance", "Assert an account balance and write a balance directive.", {
        "account": {"type": "string", "description": "Account to check"},
        "expected_amount": {"type": "string", "description": "Expected balance amount"},
        "date_str": {"type": "string", "description": "Balance date as YYYY-MM-DD"},
        "currency": {"type": "string", "description": "Currency (default: USD)"},
    }, required=["account", "expected_amount"]),
    _tool("query", "Execute a beanquery SQL query against the ledger (read-only).", {
        "sql": {"type": "string", "description": "Beanquery SQL query"},
    }, required=["sql"]),
    _tool("get_balances", "Get account balances, optionally filtered.", {
        "account_filter": {"type": "string", "description": "Account filter with wildcards (e.g., Assets:*)"},
        "date_str": {"type": "string", "description": "Balance date as YYYY-MM-DD"},
        "currency": {"type": "string", "description": "Filter by currency"},
    }),
    _tool("get_transactions", "Search transactions with filters.", {
        "date_from": {"type": "string", "description": "Start date as YYYY-MM-DD"},
        "date_to": {"type": "string", "description": "End date as YYYY-MM-DD"},
        "payee": {"type": "string", "description": "Filter by payee"},
        "account": {"type": "string", "description": "Filter by account"},
        "uuid": {"type": "string", "description": "Find by UUID"},
    }),
    _tool("import_file", "Import transactions from CSV/XLS/XLSX with auto-detection and deduplication.", {
        "file_path": {"type": "string", "description": "Path to CSV/XLS/XLSX file"},
        "account": {"type": "string", "description": "Target account"},
        "mapping_name": {"type": "string", "description": "Saved mapping name to reuse"},
        "confirm_mapping": {"type": "object", "description": "Confirmed column mapping from phase 1"},
        "sheet_name": {"type": "string", "description": "Sheet name for multi-sheet workbooks"},
    }, required=["file_path", "account"]),
    _tool("import_pdf", "Extract text and tables from a PDF bank statement.", {
        "file_path": {"type": "string", "description": "Path to PDF file"},
        "password": {"type": "string", "description": "PDF password"},
        "passwords": {"type": "array", "items": {"type": "string"}, "description": "Candidate passwords to try"},
    }, required=["file_path"]),
    _tool("fetch_prices", "Fetch current market prices for held commodities.", {
        "commodities": {"type": "array", "items": {"type": "string"}, "description": "Specific commodities to fetch"},
    }),
    _tool("analyze_spending", "Analyze spending with breakdowns and anomaly detection.", {
        "date_from": {"type": "string", "description": "Start date as YYYY-MM-DD"},
        "date_to": {"type": "string", "description": "End date as YYYY-MM-DD"},
        "group_by": {"type": "string", "description": "Group by: category, month, or payee"},
    }),
    _tool("analyze_portfolio", "Analyze investment portfolio: net worth, holdings, gains.", {
        "date_str": {"type": "string", "description": "Valuation date as YYYY-MM-DD"},
    }),
    _tool("report_capital_gains", "Report realized capital gains/losses for tax.", {
        "year": {"type": "integer", "description": "Tax year"},
    }),
    _tool("what_if_sell", "Simulate selling shares and see tax impact.", {
        "commodity": {"type": "string", "description": "Commodity to sell (e.g., AAPL)"},
        "quantity": {"type": "string", "description": "Number of units to sell"},
        "price": {"type": "string", "description": "Hypothetical price per unit"},
        "currency": {"type": "string", "description": "Price currency (default: USD)"},
        "account": {"type": "string", "description": "Specific account to sell from"},
    }, required=["commodity", "quantity", "price"]),
]


def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Route a tool call to the appropriate core library function."""
    try:
        if name == "init_ledger":
            from personalfinance.operations import init_ledger
            return init_ledger(
                path=args.get("path"),
                load_existing=args.get("load_existing", False),
            )

        if name == "open_account":
            from personalfinance.operations import open_account
            d = date.fromisoformat(args["date_str"]) if args.get("date_str") else None
            return open_account(
                account=args["account"],
                currencies=args.get("currencies"),
                booking=args.get("booking"),
                date_=d,
            )

        if name == "submit_transaction":
            from personalfinance.operations import submit_transaction
            return submit_transaction(
                date_=date.fromisoformat(args["date_str"]),
                payee=args.get("payee"),
                narration=args["narration"],
                postings=args["postings"],
                tags=set(args["tags"]) if args.get("tags") else None,
            )

        if name == "amend_transaction":
            from personalfinance.operations import amend_transaction
            d = date.fromisoformat(args["date_str"]) if args.get("date_str") else None
            return amend_transaction(
                uuid=args["uuid"],
                date_=d,
                payee=args.get("payee"),
                narration=args.get("narration"),
                postings=args.get("postings"),
                delete=args.get("delete", False),
            )

        if name == "assert_balance":
            from personalfinance.operations import assert_balance
            d = date.fromisoformat(args["date_str"]) if args.get("date_str") else None
            return assert_balance(
                account=args["account"],
                expected_amount=Decimal(args["expected_amount"]),
                date_=d,
                currency=args.get("currency"),
            )

        if name == "query":
            from personalfinance.queries import run_query
            rows = run_query(args["sql"])
            return {"status": "ok", "rows": rows, "count": len(rows)}

        if name == "get_balances":
            from personalfinance.queries import get_balances
            d = date.fromisoformat(args["date_str"]) if args.get("date_str") else None
            results = get_balances(
                account_filter=args.get("account_filter"),
                date_=d,
                currency=args.get("currency"),
            )
            return {"status": "ok", "balances": results, "count": len(results)}

        if name == "get_transactions":
            from personalfinance.queries import get_transactions
            results = get_transactions(
                date_from=date.fromisoformat(args["date_from"]) if args.get("date_from") else None,
                date_to=date.fromisoformat(args["date_to"]) if args.get("date_to") else None,
                payee=args.get("payee"),
                account=args.get("account"),
                uuid=args.get("uuid"),
            )
            return {"status": "ok", "transactions": results, "count": len(results)}

        if name == "import_file":
            from personalfinance.importers.file_importer import import_file
            return import_file(
                file_path=args["file_path"],
                account=args["account"],
                mapping_name=args.get("mapping_name"),
                confirm_mapping=args.get("confirm_mapping"),
                sheet_name=args.get("sheet_name"),
            )

        if name == "import_pdf":
            from personalfinance.importers.pdf_extractor import extract_pdf
            return extract_pdf(
                file_path=args["file_path"],
                password=args.get("password"),
                passwords=args.get("passwords"),
            )

        if name == "fetch_prices":
            from personalfinance.market.fetcher import fetch_prices
            return fetch_prices(commodities=args.get("commodities"))

        if name == "analyze_spending":
            from personalfinance.analysis.spending import analyze_spending
            return analyze_spending(
                date_from=date.fromisoformat(args["date_from"]) if args.get("date_from") else None,
                date_to=date.fromisoformat(args["date_to"]) if args.get("date_to") else None,
                group_by=args.get("group_by", "category"),
            )

        if name == "analyze_portfolio":
            from personalfinance.analysis.portfolio import analyze_portfolio
            d = date.fromisoformat(args["date_str"]) if args.get("date_str") else None
            return analyze_portfolio(date_=d)

        if name == "report_capital_gains":
            from personalfinance.analysis.capital_gains import report_capital_gains
            return report_capital_gains(year=args.get("year"))

        if name == "what_if_sell":
            from personalfinance.analysis.whatif import what_if_sell
            return what_if_sell(
                commodity=args["commodity"],
                quantity=Decimal(args["quantity"]),
                price=Decimal(args["price"]),
                currency=args.get("currency"),
                account=args.get("account"),
            )

        return {"status": "error", "message": f"Unknown tool: {name}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def run(data_dir: str | None = None) -> None:
    """Run the interactive agent with local Ollama."""
    try:
        import ollama
    except ImportError:
        print("Ollama SDK not installed. Run: pip install '.[agent]'")
        return

    try:
        from rich.console import Console
        from rich.markdown import Markdown
        console = Console()
        use_rich = True
    except ImportError:
        console = None
        use_rich = False

    from personalfinance.config import get_config, load_config

    if data_dir:
        load_config(data_dir)

    config = get_config()

    if not config.ollama.enabled:
        print("Ollama is not enabled.")
        print("Set enabled = true in your finkit.toml under [ollama], or create one:")
        print("  cp example/finkit.example.toml ~/finance/finkit.toml")
        print("  # then edit [ollama] enabled = true")
        return

    client = ollama.Client(host=config.ollama.base_url)

    try:
        client.list()
    except Exception:
        print(f"Cannot connect to Ollama at {config.ollama.base_url}")
        print("Make sure Ollama is running: ollama serve")
        return

    model = config.ollama.model

    try:
        client.show(model)
    except Exception:
        print(f"Model '{model}' not found. Pull it first: ollama pull {model}")
        return

    def _print(text: str) -> None:
        if use_rich:
            console.print(text)
        else:
            print(text)

    def _print_md(text: str) -> None:
        if use_rich:
            console.print(Markdown(text))
        else:
            print(text)

    _print(f"[bold]FinKit Agent[/bold] — local Ollama ({model})" if use_rich
           else f"FinKit Agent — local Ollama ({model})")
    _print("[dim]All data stays on your machine. Type 'quit' to exit.[/dim]\n" if use_rich
           else "All data stays on your machine. Type 'quit' to exit.\n")

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("finkit> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit", "q"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        while True:
            response = client.chat(
                model=model,
                messages=messages,
                tools=TOOLS,
            )

            msg = response.message
            messages.append(msg)

            if not msg.tool_calls:
                if msg.content:
                    _print_md(msg.content)
                break

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                tool_args = tc.function.arguments
                _print(f"  [dim]→ {tool_name}[/dim]" if use_rich
                       else f"  → {tool_name}")

                result = _dispatch(tool_name, tool_args)
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result, default=str),
                })
