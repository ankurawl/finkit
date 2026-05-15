# FinKit

Privacy-first personal and family finance toolkit. All data stays on your machine --- no cloud accounts, no telemetry, no third-party access to your financial records.

FinKit uses a SQLite-canonical architecture with an extensible summary layer, exposed through both MCP tools (for LLM-driven interaction) and a traditional CLI.

## Features

- **Double-entry accounting** --- every transaction balances. Postings are validated with currency-aware tolerance (0.01 for fiat, 0.00000001 for crypto).
- **Multi-currency support** --- tracks USD and INR natively with price-weighted balancing for cross-currency transfers and investment trades. EUR and other currencies can be added dynamically.
- **Lot tracking with capital gains** --- per-lot cost basis using FIFO, LIFO, or HIFO selection. Automatic holding period classification (short-term vs long-term) based on jurisdiction rules. Wash sale detection for US tax reporting.
- **Statement import** --- ingest CSV, XLSX, and PDF bank/brokerage statements. SHA-256 dedup ensures re-importing the same file is a no-op. Original files are copied, never moved or deleted.
- **Summary layer** --- pre-computed tables (daily balances, monthly spending, portfolio holdings, net worth, capital gains) are updated atomically on every write and rebuilt on demand.
- **MCP server** --- 39 tools for LLM integration. Point Claude, GPT, or any MCP-compatible client at the server for natural-language financial queries.
- **CLI** --- every MCP tool has a matching CLI subcommand. No LLM required for any operation.
- **Rule-based categorization** --- pattern matching (substring, regex, exact) to auto-categorize transactions. Optional Ollama integration for LLM-assisted categorization.
- **Market data** --- fetch stock/ETF prices via yfinance, crypto via CoinGecko, forex via exchange rate APIs. Manual price entry for unlisted assets.
- **Corporate actions** --- stock splits, reverse splits, and bonus shares adjust all affected lots automatically.

## Architecture

```
User <-> LLM <-> MCP Server (39 tools) <-> Python Core <-> SQLite + File Archive
                                                |
                                         All computation
                                         happens here
                                         (deterministic)
```

SQLite stores both normalized core tables (transactions, postings, accounts, lots, prices) and derived summary tables (s_daily_balances, s_monthly_spending, s_portfolio_holdings, s_net_worth, s_yearly_capital_gains). Summary tables are updated within the same transaction as the core write, ensuring consistency. They can be rebuilt from scratch at any time with `finkit rebuild`.

## Installation

```bash
# Clone the repository
git clone https://github.com/your-org/finkit.git
cd finkit/finkit

# Install with development and market data extras
pip install -e ".[dev,market]"

# For Excel import support (XLSX, XLS)
pip install -e ".[dev,market,excel]"

# For LLM-assisted categorization via Ollama
pip install -e ".[dev,market,agent]"
```

Requires Python 3.10 or later. SQLite is included in the Python standard library.

## Quick Start

```bash
# 1. Initialize the ledger (creates ~/finance/finkit.db)
finkit init

# 2. Open accounts
finkit open-account Assets:Chase:Checking --type Assets --currency USD --institution chase
finkit open-account Expenses:Groceries --type Expenses --currency USD
finkit open-account Expenses:Dining --type Expenses --currency USD

# 3. Submit a transaction (postings must balance to zero)
finkit submit --date 2025-01-15 --payee "Whole Foods" --narration "Weekly groceries" \
  --postings '[
    {"account": "Expenses:Groceries", "amount": "85.50", "currency": "USD"},
    {"account": "Assets:Chase:Checking", "amount": "-85.50", "currency": "USD"}
  ]'

# 4. Import a CSV bank statement
finkit import ~/Downloads/chase-jan-2025.csv Assets:Chase:Checking --institution chase

# 5. Query your data
finkit balances --type Assets
finkit spending --month 2025-01
finkit query "SELECT * FROM s_monthly_spending WHERE year_month = '2025-01'"
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `finkit init` | Initialize the database and default accounts |
| `finkit open-account` | Open a new account in the chart of accounts |
| `finkit submit` | Submit a double-entry transaction |
| `finkit amend` | Amend or delete a transaction by UUID |
| `finkit assert-balance` | Verify an account balance on a given date |
| `finkit query` | Run a read-only SQL query |
| `finkit balances` | Show account balances |
| `finkit transactions` | Search and list transactions |
| `finkit accounts` | List all accounts |
| `finkit import` | Import a CSV, XLSX, or PDF statement file |
| `finkit import-pdf` | Extract raw text/tables from a PDF (extraction only) |
| `finkit import-dir` | Batch import all matching files from a directory |
| `finkit fetch-prices` | Fetch market prices for stocks, crypto, and forex |
| `finkit manual-price` | Record a manual price entry |
| `finkit spending` | Analyze spending patterns by category |
| `finkit portfolio` | Analyze portfolio holdings and net worth |
| `finkit capital-gains` | Report realized capital gains for tax filing |
| `finkit what-if` | Simulate selling a position |
| `finkit export` | Export data as CSV or JSON |
| `finkit categorize` | Manage categorization rules (add/remove/list) |
| `finkit corporate-action` | Record a stock split or other corporate action |
| `finkit undo-import` | Reverse a file import |
| `finkit recategorize-posting` | Change one posting's account on a transaction |
| `finkit batch-recategorize` | Recategorize all transactions matching a payee pattern |
| `finkit payee-rules` | Manage payee normalization rules (add/remove/list) |
| `finkit normalize-payees` | Apply normalization rules to existing transactions |
| `finkit find-duplicates` | Find potential duplicate transactions across sources |
| `finkit merge-duplicates` | Merge two duplicate transactions |
| `finkit detect-transfers` | Detect potential inter-account transfers |
| `finkit link-transfer` | Link two transfer transactions |
| `finkit import-report` | Generate post-import health report |
| `finkit learn-template` | Extract text from a document for template creation |
| `finkit apply-template` | Apply a template to extract transactions |
| `finkit list-templates` | List saved document templates |
| `finkit delete-template` | Delete a document template |
| `finkit rebuild` | Rebuild all summary tables from core data |
| `finkit backup` | Create a database backup using SQLite backup API |

All commands accept `--data-dir` to override the default data directory (`~/finance`). You can also set the `FINKIT_DATA_DIR` environment variable (or add it to a `.env` file in the project root).

## MCP Server

The MCP server exposes 39 tools to any MCP-compatible LLM client. For Claude Code, it auto-configures via `.mcp.json` — just open the project and the tools are available.

For other MCP clients, start the server manually:

```bash
python -m finkit.mcp.server
```

The `query` tool enforces read-only access with `PRAGMA query_only = ON`.

## Configuration

FinKit reads configuration from `finkit.toml` in your data directory. Copy the example to get started:

```bash
cp example/finkit.example.toml ~/finance/finkit.toml
```

Key settings:

```toml
[general]
data_dir = "~/finance"         # Database and statement archive location
default_currency = "USD"       # Default currency for new accounts
base_currency = "USD"          # Base currency for consolidated net worth

[holding_periods]
"US.equity" = 365              # Days for long-term classification
"US.crypto" = 365
"IN.equity" = 365
"IN.debt" = 1095               # 3 years for India debt instruments
"IN.elss" = 1095               # 3-year lock-in for ELSS funds

[import]
dedup_window_days = 3          # Window for detecting duplicate transactions

[market]
stock_source = "yfinance"      # Stock/ETF price provider
crypto_source = "coingecko"    # Cryptocurrency price provider
forex_source = "exchangerate-api"

[ollama]
enabled = false                # Enable LLM categorization
model = "qwen2.5:7b"
base_url = "http://localhost:11434"
```

API keys for market data providers can be set in a `.env` file in the data directory:

```
COINGECKO_API_KEY=your_key_here
EXCHANGERATE_API_KEY=your_key_here
```

## Privacy

All data is stored locally:

- **Database**: `~/finance/finkit.db` (single SQLite file)
- **Statements**: `~/finance/statements/` (archived copies organized by year)
- **Backups**: `~/finance/backups/`

No data is ever sent to any external service. Market price fetching is the only network operation, and it sends only ticker symbols --- never your account data, balances, or transaction history.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System design, data flow, and key decisions |
| [Schema Reference](docs/schema_reference.md) | Database table layouts with example queries |
| [Tools Reference](docs/tools_reference.md) | Detailed parameter docs for all 20 MCP tools and CLI commands |
| [Roadmap](docs/roadmap.md) | Completed features, known limitations, and future ideas |
| [Quickstart](example/quickstart.md) | Step-by-step walkthrough from install to portfolio analysis |
| [Contributing](CONTRIBUTING.md) | Code conventions and patterns for adding new features |
| [Changelog](CHANGELOG.md) | What changed in each release |

## License

MIT. See [LICENSE](LICENSE) for details.
