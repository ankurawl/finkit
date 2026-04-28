# FinKit — Personal Finance Toolkit

Privacy-first personal finance management built on [Beancount v3](https://github.com/beancount/beancount). All data stays local as plain text files. No cloud sync, no third-party access, no credentials stored.

FinKit wraps Beancount with an **MCP server** (15 tools) and a **CLI** (`finkit`) for managing your finances through Claude Code, Cursor, or the terminal.

## Features

- **Double-entry accounting** via Beancount v3 — multi-currency, lot tracking, booking methods
- **MCP server** with 15 tools for conversational finance management
- **CLI** mirroring every MCP tool for script/terminal workflows
- **CSV/XLS/XLSX import** with auto-column-detection and two-phase confirm-mapping
- **PDF extraction** for bank statements (supports password-protected PDFs)
- **Market data** from yfinance, CoinGecko, and forex APIs
- **Spending analysis** with category/month/payee breakdowns and anomaly detection
- **Portfolio analysis** with net worth, holdings, allocation, unrealized gains
- **Capital gains reporting** with short-term vs long-term classification
- **What-if simulation** — "what if I sell 50 AAPL at $200?"
- **Rule-based + LLM-assisted categorization** (Ollama, optional)
- **Export** any analysis as CSV or JSON

## Quick Start

### Install

```bash
pip install .                    # Core features
pip install ".[market]"          # + market data (yfinance, pandas)
pip install ".[dev]"             # + test dependencies
```

**Note**: Beancount v3 may require building from source:
```bash
pip install git+https://github.com/beancount/beancount.git
pip install git+https://github.com/beancount/beanquery.git
pip install git+https://github.com/beancount/beangulp.git
```

### Initialize a Ledger

```bash
# Create a new ledger with default accounts
finkit init ~/finance/main.beancount

# Or load an existing Beancount file
finkit init --load ~/existing-ledger.beancount
```

### Import Bank Data

```bash
# Phase 1: Auto-detect columns
finkit import ~/Downloads/Chase_Activity.csv --account Assets:Chase:Checking

# Phase 2: Confirm mapping and import
finkit import ~/Downloads/Chase_Activity.csv --account Assets:Chase:Checking \
  --confirm-mapping '{"date_col":"Posting Date","amount_col":"Amount","payee_col":"Description","date_format":"%m/%d/%Y","save_as":"chase"}'
```

### Analyze

```bash
finkit spending --period 2025-03     # Monthly spending breakdown
finkit balances                       # All account balances
finkit portfolio                      # Investment holdings + net worth
finkit capital-gains --year 2025      # Realized gains for tax
finkit whatif-sell AAPL 50 200        # Tax impact simulation
```

### Use with Claude Code (MCP)

Add to your Claude Code MCP config:
```json
{
  "mcpServers": {
    "finkit": {
      "command": "python",
      "args": ["-m", "personalfinance.mcp.server"]
    }
  }
}
```

Then talk to Claude: *"Import my Chase CSV and show me where my money went last month."*

## Configuration

Copy `example/finkit.example.toml` to your finance data directory as `finkit.toml`. All settings are optional — defaults work out of the box.

For API keys (market data), copy `example/.env.example` to your data directory as `.env`.

## Architecture

```
CLI (finkit) ──┐
               ├──→ Core Library ──→ Beancount v3
MCP Server ────┘     (ledger, queries, analysis, import, market)
```

The CLI and MCP server are thin wrappers over the same core library functions. Every MCP tool has a corresponding CLI command.

## Privacy & Security

- **All data local**: Ledger files are plain text on your machine
- **No credentials stored**: Bank CSV exports are downloaded manually
- **Market data only sends ticker symbols**: Never account balances or personal info
- **PDF passwords are in-memory only**: Never written to disk or logged
- **No telemetry**: Zero network calls except market price fetches

## License

MIT
