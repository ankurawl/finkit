# FinKit Quickstart

A step-by-step walkthrough from installation to portfolio analysis.

## 1. Install

```bash
cd finkit
pip install -e ".[dev,market]"
```

This installs FinKit with development tools (pytest) and market data support (yfinance, pandas). Add `excel` for XLSX/XLS import support, or `agent` for Ollama-based categorization.

## 2. Initialize the Ledger

```bash
finkit init
```

This creates `~/finance/finkit.db` with the full schema, default accounts (including `Equity:OpeningBalances`), and seeded currency tolerances. If the database already exists, it connects without overwriting.

Output:
```json
{
  "status": "ok",
  "db_path": "/Users/you/finance/finkit.db"
}
```

## 3. Open Accounts

Open the accounts you need. Account names use colon-separated hierarchy. The five root types are: Assets, Liabilities, Income, Expenses, Equity.

```bash
# US checking account
finkit open-account Assets:Chase:Checking \
  --type Assets --currency USD --institution chase

# US savings account
finkit open-account Assets:Chase:Savings \
  --type Assets --currency USD --institution chase

# Credit card
finkit open-account Liabilities:Amex:Platinum \
  --type Liabilities --currency USD --institution amex

# India savings account
finkit open-account Assets:HDFC:Savings \
  --type Assets --currency INR --institution hdfc

# US brokerage account
finkit open-account Assets:Schwab:Brokerage \
  --type Assets --currency USD --institution schwab \
  --booking-method FIFO --asset-class equity --jurisdiction US

# Expense categories
finkit open-account Expenses:Groceries --type Expenses --currency USD
finkit open-account Expenses:Dining --type Expenses --currency USD
finkit open-account Expenses:Utilities --type Expenses --currency USD
finkit open-account Expenses:Transport --type Expenses --currency USD

# Income
finkit open-account Income:Salary --type Income --currency USD
```

Set an opening balance using the Equity:OpeningBalances account:

```bash
finkit submit --date 2025-01-01 --payee "Opening" --narration "Chase checking starting balance" \
  --postings '[
    {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
    {"account": "Equity:OpeningBalances", "amount": "-5000.00", "currency": "USD"}
  ]'
```

## 4. Import a Chase CSV

Chase checking exports have columns like: `Posting Date`, `Description`, `Amount`, `Type`, `Balance`. FinKit auto-detects the format and applies a column mapping.

```bash
finkit import ~/Downloads/chase-checking-jan-2025.csv Assets:Chase:Checking \
  --institution chase --mapping chase_checking
```

On first import for an institution, FinKit detects column structure and saves the mapping for reuse. The file is copied into `~/finance/statements/2025/` and SHA-256 is recorded for dedup. Importing the same file again is a no-op.

## 4b. Import a PDF Statement

FinKit can also import PDF statements directly. Institution-specific parsers extract transactions from the PDF text.

```bash
# PDF import with auto-detected institution
finkit import ~/Downloads/chase-freedom-jan-2026.pdf Liabilities:Chase:Freedom --institution chase

# The institution can often be auto-detected from the PDF content
finkit import ~/Downloads/marcus-savings-dec-2025.pdf Assets:Marcus:Savings
```

Supported PDF institutions: Chase (credit cards), Capital One, Citi, Marcus (Goldman Sachs), Alliant Credit Union, FirstTech Federal, Frost Bank, and Fidelity (investment accounts).

Output:
```json
{
  "imported": 47,
  "skipped_duplicates": 0,
  "source_file_id": 1,
  "archived_path": "2025/chase-checking-jan-2025.csv"
}
```

## 5. Import an HDFC CSV (INR)

Import a statement from an Indian bank. The same workflow handles INR transactions.

```bash
finkit import ~/Downloads/hdfc-savings-jan-2025.csv Assets:HDFC:Savings \
  --institution hdfc --mapping hdfc_savings
```

HDFC uses different column conventions (some Indian banks use positive amounts for debits). The column mapping's `amount_sign` setting handles this. Set up an opening balance for the INR account if needed:

```bash
finkit submit --date 2025-01-01 --payee "Opening" --narration "HDFC savings opening balance" \
  --postings '[
    {"account": "Assets:HDFC:Savings", "amount": "500000.00", "currency": "INR"},
    {"account": "Equity:OpeningBalances", "amount": "-500000.00", "currency": "INR"}
  ]'
```

## 6. Categorize Transactions

Add rules to auto-categorize transactions by payee pattern:

```bash
# Substring matching (default)
finkit categorize add "WHOLE FOODS" Expenses:Groceries
finkit categorize add "TRADER JOE" Expenses:Groceries
finkit categorize add "UBER EATS" Expenses:Dining
finkit categorize add "SHELL OIL" Expenses:Transport

# Regex matching
finkit categorize add "AMAZON.*PRIME" Expenses:Subscriptions --pattern-type regex

# Institution-specific rules
finkit categorize add "SWIGGY" Expenses:Dining --institution hdfc

# List all rules
finkit categorize list
```

Rules are applied automatically during CSV import. Transactions matching a pattern get their expense/income side categorized to the target account.

## 7. Spending Analysis

Analyze spending by category, with month-over-month trends:

```bash
# Current month
finkit spending

# Specific month
finkit spending --month 2025-01

# Last 12 months trend
finkit spending --months 12

# Single category deep-dive
finkit spending --category Expenses:Groceries --months 12

# INR spending
finkit spending --currency INR
```

The spending tool reads from `s_monthly_spending` for instant results. It returns totals by category, month-over-month changes, and flags anomalies (spikes exceeding 2 standard deviations from the mean).

## 8. Fetch Market Prices

Fetch current prices for stocks, crypto, and forex:

```bash
# Stocks and ETFs
finkit fetch-prices --symbols AAPL,VTI,VTSAX

# Cryptocurrency
finkit fetch-prices --coins bitcoin,ethereum

# Forex exchange rates
finkit fetch-prices --forex-pairs USD/INR,EUR/USD

# All at once
finkit fetch-prices --symbols AAPL,VTI --coins bitcoin --forex-pairs USD/INR

# Manual price entry for unlisted assets
finkit manual-price HDFC-EQUITY-FUND INR 45.67 2025-01-15
```

Fetched prices are written to the `prices` table and trigger a refresh of `s_portfolio_holdings` and `s_net_worth`.

## 9. Portfolio Analysis

View investment holdings, asset allocation, and unrealized gains:

```bash
# Portfolio overview (uses base currency for consolidation)
finkit portfolio

# In a specific currency
finkit portfolio --currency USD
```

Output includes:
- Total net worth per currency and consolidated
- Asset allocation breakdown (cash, equity, debt, crypto)
- Per-holding: quantity, cost basis, current market value, unrealized gain/loss
- Lot-level detail with acquisition dates

For capital gains reporting:

```bash
# Current year realized gains
finkit capital-gains

# Specific year
finkit capital-gains --year 2024

# Simulate selling before committing
finkit what-if Assets:Schwab:Brokerage AAPL 50 --method FIFO --price 195.00
```

The `what-if` command shows which lots would be sold, the gain/loss for each, short vs long term classification, and warns if any lots have a lock-in period that hasn't expired (relevant for Indian ELSS funds).

## 10. Assert Balance

Verify that your computed balance matches your bank statement:

```bash
finkit assert-balance Assets:Chase:Checking 2025-01-31 4523.47 --currency USD
```

Output:
```json
{
  "matches": true,
  "expected": "4523.47",
  "actual": "4523.47",
  "difference": "0.00"
}
```

If there's a mismatch, the assertion is still recorded for audit purposes. The difference helps track down missing or duplicate transactions.

## Next Steps

- Read the [Architecture](../docs/architecture.md) for design decisions and data flow
- Read the [Tools Reference](../docs/tools_reference.md) for detailed parameter documentation
- Read the [Schema Reference](../docs/schema_reference.md) for database table layouts
- Set up the MCP server (`python -m finkit.mcp.server`) for LLM-driven interaction
- Configure budgets and track spending against them with `budget_vs_actual`
- Set up recurring transaction templates for predictable income/expenses
