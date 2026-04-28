# FinKit — Personal Finance Toolkit

Privacy-first personal finance management built on [Beancount v3](https://github.com/beancount/beancount). All data stays local as plain text files. No cloud sync, no third-party access, no credentials stored.

FinKit wraps Beancount with an **MCP server** (15 tools), a **CLI** (`finkit`), and a **local Ollama agent** for managing your finances through Claude Code, Cursor, the terminal, or a fully offline conversational agent.

## Features

- **Double-entry accounting** via Beancount v3 — multi-currency, lot tracking, booking methods
- **MCP server** with 15 tools for conversational finance management
- **Local Ollama agent** — fully offline conversational interface, no data leaves your machine
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

### 1. Install

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

### 2. Initialize a Ledger

```bash
# Create a new ledger with default accounts
finkit init ~/finance/main.beancount

# Or load an existing Beancount file
finkit init --load ~/existing-ledger.beancount
```

### 3. Set Up the MCP Server (Recommended)

The MCP server lets you manage your finances conversationally through Claude Code, Cursor, or any MCP-compatible client. This is the recommended way to use FinKit — especially for PDF imports, bulk operations, and exploratory analysis.

```bash
# From the finkit project directory:
claude mcp add finkit -- python -m personalfinance.mcp.server
```

Or add manually to your MCP config:
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

Start a new Claude Code session after adding the server so it picks up the finkit tools.

### 3b. Local Ollama Agent (Fully Offline Alternative)

If you want **zero data leaving your machine** — no cloud APIs, no external LLM calls — use the built-in Ollama agent. It runs a local LLM with tool calling to provide the same conversational experience as the MCP server, but entirely offline.

**Step 1: Install Ollama and pull a model**

Install Ollama from [ollama.com](https://ollama.com), then pull a model with tool-calling support:

```bash
ollama pull qwen2.5:7b          # Default — lightweight, works on most machines
ollama pull qwen2.5:14b         # Better accuracy for complex tasks (needs ~10GB RAM)
ollama pull llama3.1:8b          # Good alternative with strong tool calling
```

**Step 2: Install the agent dependencies**

```bash
pip install ".[agent]"          # Adds ollama SDK + rich terminal formatting
```

**Step 3: Enable Ollama in your config**

Create or edit `~/finance/finkit.toml`:

```toml
[ollama]
enabled = true
model = "qwen2.5:7b"               # Must match a model you've pulled
base_url = "http://localhost:11434" # Default Ollama address
```

**Step 4: Launch the agent**

```bash
ollama serve &                  # Start Ollama if not already running
finkit agent                    # Start the interactive agent
```

You'll get a conversational prompt:
```
FinKit Agent — local Ollama (qwen2.5:7b)
All data stays on your machine. Type 'quit' to exit.

finkit> Show me my account balances
  → get_balances
...

finkit> Import my Chase statement from ~/finance/statements/Chase_Checking.pdf
  → import_pdf
  → submit_transaction
  → submit_transaction
...
```

The agent has access to all 15 FinKit tools — the same ones exposed by the MCP server. It can extract PDFs, create accounts, submit transactions, analyze spending, and everything else, all running locally.

> **Tip**: Larger models (14B+) produce significantly better results for complex multi-step tasks like bulk PDF import. The 7B default is fine for queries and single-file imports. If you have the RAM, use `qwen2.5:14b` or larger.

### 4. Import Bank Data

FinKit supports two import paths: **CSV/spreadsheet import** (fully automated via CLI or MCP) and **PDF extraction** (MCP-assisted, where Claude interprets the extracted content).

#### Option A: CSV / XLS / XLSX (CLI or MCP)

Best when your bank offers CSV or spreadsheet downloads. The import is fully automated with auto-column-detection, two-phase mapping, and deduplication.

```bash
# Phase 1: Auto-detect columns
finkit import ~/Downloads/Chase_Activity.csv --account Assets:Chase:Checking

# Phase 2: Confirm mapping and import
finkit import ~/Downloads/Chase_Activity.csv --account Assets:Chase:Checking \
  --confirm-mapping '{"date_col":"Posting Date","amount_col":"Amount","payee_col":"Description","date_format":"%m/%d/%Y","save_as":"chase"}'
```

Once you save a mapping with `save_as`, reuse it for future files from the same bank:
```bash
finkit import chase_feb.csv --account Assets:Chase:Checking --mapping chase
```

#### Option B: PDF Bank Statements (MCP Recommended)

Many banks only provide PDF statements. FinKit extracts tables and text from PDFs (including password-protected ones), and the MCP server lets Claude interpret the extracted content and submit transactions automatically.

**CLI extraction** (extracts raw content, no automatic import):
```bash
finkit extract-pdf ~/Downloads/statement.pdf
finkit extract-pdf ~/Downloads/statement.pdf --password "mypass123"
finkit extract-pdf ~/Downloads/statement.pdf --passwords "pass1,pass2,pass3"
```

**LLM-assisted import** (recommended — the LLM interprets and imports in one flow):

Via MCP (Claude Code / Cursor):
```
> Import my Chase statement from ~/Downloads/chase_jan.pdf into Assets:Chase:Checking
```

Via local Ollama agent:
```
finkit> Import my Chase statement from ~/Downloads/chase_jan.pdf into Assets:Chase:Checking
```

In both cases, the LLM calls `import_pdf` to extract the content, identifies transactions from the tables, and calls `submit_transaction` for each one.

#### Bulk PDF Import

If you have many PDF statements across multiple banks and time periods, the MCP server handles this well. Organize your PDFs and let Claude process them in batch.

**1. Organize your statements:**
```
~/finance/statements/
├── FY2023/
│   ├── Chase_Checking.pdf
│   ├── BofA_Savings.pdf
│   └── Amex_CreditCard_pass_mypass123.pdf
├── FY2024/
│   ├── Chase_Checking.pdf
│   └── ...
```

If your statements already live elsewhere, symlink instead of copying:
```bash
ln -s /path/to/your/actual/statements ~/finance/statements
```

Naming convention: include the bank/account name in the filename. For password-protected PDFs, append the password after `pass_` (e.g., `HDFC_Savings_pass_secret123.pdf`).

**2. Use this prompt** in Claude Code (MCP) or the Ollama agent (`finkit agent`):

```
I need to import all my bank statements into my Beancount ledger at
~/finance/main.beancount.

My PDF statements are in ~/finance/statements/, organized in subfolders
by financial year. Each PDF filename contains the bank/organization name.
If a PDF is password-protected, the password is included in the filename
(e.g., "HDFC_Savings_pass_mypass123.pdf" means the password is "mypass123").

Here's what I need you to do:

1. List all PDFs in ~/finance/statements/ recursively so we can review
   the plan before importing.

2. For each unique bank/account, use open_account to create an
   appropriate Beancount account (e.g., Assets:Chase:Checking,
   Liabilities:Amex:CreditCard). Use your judgment on account type
   and naming.

3. Process each PDF one at a time:
   - Extract the password from the filename if present (text after
     "pass_" before the extension)
   - Call import_pdf with the file path and password
   - Interpret the extracted tables to identify transactions
   - Call submit_transaction for each transaction, posting to the
     correct account
   - Use Expenses:Other for outflows and Income:Other for inflows

4. After all PDFs, run get_balances to show the final state.

Start by listing the PDFs so we can review the plan before importing.
```

> **Note**: PDF extraction quality varies by bank. Banks that produce clean tabular PDFs work best. If a bank's format causes issues, try converting that PDF to CSV with a dedicated tool first, then use `finkit import`.
>
> **Note**: For bulk PDF import with many files, MCP via Claude Code tends to handle multi-step workflows more reliably than smaller local models. If using the Ollama agent for bulk import, consider a 14B+ model.

### 5. Analyze

```bash
finkit spending --period 2025-03     # Monthly spending breakdown
finkit balances                       # All account balances
finkit portfolio                      # Investment holdings + net worth
finkit capital-gains --year 2025      # Realized gains for tax
finkit whatif-sell AAPL 50 200        # Tax impact simulation
```

Or conversationally via MCP: *"Show me where my money went last month"*, *"What's my net worth?"*, *"What if I sell 50 AAPL at $200?"*

## Configuration

Copy `example/finkit.example.toml` to your finance data directory as `finkit.toml`. All settings are optional — defaults work out of the box.

For API keys (market data), copy `example/.env.example` to your data directory as `.env`.

## Architecture

```
CLI (finkit) ──────┐
                   │
MCP Server ────────┼──→ Core Library ──→ Beancount v3
                   │     (ledger, queries, analysis, import, market)
Ollama Agent ──────┘
(finkit agent)
```

The CLI, MCP server, and Ollama agent are all thin wrappers over the same core library functions. Every MCP tool has a corresponding CLI command, and the Ollama agent can call all 15 tools via local LLM tool-calling.

## Privacy & Security

- **All data local**: Ledger files are plain text on your machine
- **No credentials stored**: Bank CSV exports are downloaded manually
- **Market data only sends ticker symbols**: Never account balances or personal info
- **PDF passwords are in-memory only**: Never written to disk or logged
- **No telemetry**: Zero network calls except market price fetches

## License

MIT
