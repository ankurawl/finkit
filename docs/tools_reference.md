# FinKit Tools Reference

Every MCP tool has a corresponding CLI command. Parameters are equivalent.

## Ledger Management

### init_ledger / `finkit init`

Create a new ledger or load an existing one.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| path | positional | Ledger file path (default: ~/finance/main.beancount) |
| load_existing | `--load` | Load existing ledger instead of creating new |
| data_dir | `--data-dir` | Data directory (default: ~/finance) |

```bash
finkit init ~/finance/main.beancount
finkit init --load ~/existing.beancount
```

### open_account / `finkit open-account`

Open a new account in the ledger.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| account | positional | Full account path (e.g., Assets:Chase:Checking) |
| currencies | `--currency` | Comma-separated currencies (default: USD) |
| booking | `--booking` | Booking method: FIFO, LIFO, HIFO, AVERAGE, STRICT |
| date_str | `--date` | Open date as YYYY-MM-DD (default: 2020-01-01) |

```bash
finkit open-account "Assets:Vanguard:Brokerage" --currency USD --booking FIFO
```

### submit_transaction / `finkit submit`

Add a transaction with UUID tag and fuzzy account matching.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| date_str | `--date` | Transaction date (YYYY-MM-DD) |
| narration | `--narration` | Transaction description |
| postings | `--postings` | JSON array of postings |
| payee | `--payee` | Payee name |
| tags | `--tags` | Comma-separated tags |

```bash
finkit submit --date 2025-04-15 --payee "Whole Foods" --narration "Groceries" \
  --postings '[{"account":"Expenses:Food:Groceries","amount":"87.43","currency":"USD"},{"account":"Assets:Checking","amount":"-87.43","currency":"USD"}]'
```

### amend_transaction / `finkit amend`

Edit or delete a transaction by UUID.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| uuid | positional | Transaction UUID (8-char hex) |
| date_str | `--date` | New date |
| payee | `--payee` | New payee |
| narration | `--narration` | New narration |
| postings | `--postings` | New postings (JSON) |
| delete | `--delete` | Delete the transaction |

```bash
finkit amend a1b2c3d4 --narration "Updated description"
finkit amend a1b2c3d4 --delete
```

### assert_balance / `finkit assert-balance`

Assert an account balance and verify.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| account | positional | Account path |
| expected_amount | positional | Expected balance |
| date_str | `--date` | Balance date (default: today) |
| currency | `--currency` | Currency (default: USD) |

```bash
finkit assert-balance "Assets:Chase:Checking" 3241.56 --date 2025-04-27
```

## Querying

### query / `finkit query`

Execute raw beanquery SQL (read-only).

```bash
finkit query "SELECT account, sum(position) GROUP BY account ORDER BY account"
```

### get_balances / `finkit balances`

Get account balances with optional filters.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| account_filter | `--account` | Account filter with wildcards (e.g., Assets:*) |
| date_str | `--date` | Balance date |
| currency | `--currency` | Filter by currency |

```bash
finkit balances --account "Assets:*"
```

### get_transactions / `finkit transactions`

Search transactions with structured filters.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| date_from | `--date-from` | Start date |
| date_to | `--date-to` | End date |
| payee | `--payee` | Filter by payee |
| account | `--account` | Filter by account |
| uuid | `--uuid` | Find by UUID |

```bash
finkit transactions --date-from 2025-01-01 --payee "Whole Foods"
```

## Ingestion

### import_file / `finkit import`

Import CSV/XLS/XLSX with two-phase flow.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| file_path | positional | Path to file |
| account | `--account` | Target account |
| mapping_name | `--mapping` | Saved mapping name |
| confirm_mapping | `--confirm-mapping` | Confirmed mapping (JSON) |
| sheet_name | `--sheet` | Sheet name for workbooks |

### import_pdf / `finkit extract-pdf`

Extract text/tables from PDF statements.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| file_path | positional | Path to PDF |
| password | `--password` | PDF password |
| passwords | `--passwords` | Comma-separated candidate passwords |

### fetch_prices / `finkit fetch-prices`

Fetch market prices for held commodities.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| commodities | `--commodities` | Comma-separated commodity list |

## Analysis

### analyze_spending / `finkit spending`

Spending/income analysis with breakdowns.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| date_from | `--date-from` | Start date |
| date_to | `--date-to` | End date |
| group_by | `--group-by` | category, month, or payee |

### analyze_portfolio / `finkit portfolio`

Net worth and investment holdings analysis.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| date_str | `--date` | Valuation date |

### report_capital_gains / `finkit capital-gains`

Realized capital gains/losses report.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| year | `--year` | Tax year (default: current) |

### what_if_sell / `finkit whatif-sell`

Simulate selling and compute tax impact.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| commodity | positional | Commodity to sell |
| quantity | positional | Number of units |
| price | positional | Hypothetical sell price |
| currency | `--currency` | Price currency |
| account | `--account` | Specific account to sell from |

```bash
finkit whatif-sell AAPL 50 200
```

### export / `finkit export`

Export tool output as CSV or JSON.

| Parameter | CLI Flag | Description |
|-----------|----------|-------------|
| tool_name | positional | Tool name to export |
| format | `--format` | csv or json |
| output_path | `--output` | Output file path |

```bash
finkit export get_transactions --format csv --output transactions.csv
```
