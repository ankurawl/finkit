# FinKit Quick Start (5 minutes)

## Prerequisites

- Python 3.10+
- Bank CSV export (download from your bank's website)

## Setup

```bash
pip install .
pip install ".[market]"   # Optional: for stock/crypto prices
```

## Path A: With Claude Code (MCP)

### 1. Add MCP server config

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

### 2. Start chatting

> **You**: "Import my Chase CSV" *(drag file or give path)*
>
> **Claude**: Auto-detects columns, asks you to confirm mapping, imports 147 transactions, creates ledger if needed.
>
> **You**: "My Chase balance is $3,241.56"
>
> **Claude**: Runs `assert_balance` — confirms imported data matches.
>
> **You**: "Where did my money go last month?"
>
> **Claude**: Runs `analyze_spending` — shows category breakdown with trends.
>
> **You**: "What if I sell 50 shares of AAPL at $200?"
>
> **Claude**: Runs `what_if_sell` — shows which lots get sold, tax impact, short vs long term split.

## Path B: CLI Only

### 1. Create ledger

```bash
finkit init ~/finance/main.beancount
```

### 2. Import bank CSV

```bash
# Auto-detect (shows proposed mapping)
finkit import ~/Downloads/Chase_Activity.csv --account Assets:Chase:Checking

# Confirm and import
finkit import ~/Downloads/Chase_Activity.csv --account Assets:Chase:Checking \
  --confirm-mapping '{"date_col":"Posting Date","amount_col":"Amount","payee_col":"Description","date_format":"%m/%d/%Y"}'
```

### 3. Verify balance

```bash
finkit assert-balance "Assets:Chase:Checking" 3241.56 --date 2025-04-27
```

### 4. Categorize

```bash
finkit categorize --apply-rules    # Auto-categorize known merchants
finkit categorize --review         # Review uncategorized transactions
```

### 5. Analyze

```bash
finkit spending --group-by category
finkit balances
finkit fetch-prices                # Get latest stock/crypto prices
finkit portfolio                   # Net worth + holdings
```

## Ongoing Workflow

| When | What | Time |
|------|------|------|
| Weekly | Download CSV → `finkit import` → spot-check | 5 min |
| Monthly | `finkit assert-balance` → `finkit spending` | 15 min |
| Quarterly | `finkit fetch-prices` → `finkit portfolio` | 10 min |
| Tax time | `finkit capital-gains` → `finkit export` | 30 min |
