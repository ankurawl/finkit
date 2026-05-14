# FinKit Tools Reference

Every tool is available as both an MCP tool (for LLM clients) and a CLI subcommand. They call the same backing functions.

---

## 1. init_ledger

Create or connect to the FinKit database and initialize the schema.

**MCP**: `init_ledger()`
**CLI**: `finkit init`

**Parameters**: None

**Example**:
```bash
finkit init
finkit --data-dir ~/work-finance init
```

**Output**: `{"status": "ok", "db_path": "/path/to/finkit.db"}`

**Errors**:
- Permission error if the data directory is not writable

---

## 2. open_account

Open a new account in the ledger.

**MCP**: `open_account(name, type, currency?, booking_method?, institution?, asset_class?, jurisdiction?)`
**CLI**: `finkit open-account NAME --type TYPE [options]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | str | yes | | Colon-separated name, e.g. `Assets:Chase:Checking` |
| `type` | str | yes | | One of: Assets, Liabilities, Income, Expenses, Equity |
| `currency` | str | no | USD | Default currency |
| `booking_method` | str | no | null | Lot selection: FIFO, LIFO, or HIFO |
| `institution` | str | no | null | Financial institution name |
| `asset_class` | str | no | null | cash, equity, debt, crypto, real_estate |
| `jurisdiction` | str | no | null | Tax jurisdiction: US, IN, EU |

**Example**:
```bash
finkit open-account Assets:Schwab:Brokerage --type Assets --currency USD \
  --booking-method FIFO --institution schwab --asset-class equity --jurisdiction US
```

**Output**: `{"account_id": 5}`

**Errors**:
- Account name already exists
- Invalid account type
- Account name does not start with a valid root type

---

## 3. submit_transaction

Submit a new double-entry transaction. All postings must sum to zero (within currency-aware tolerance).

**MCP**: `submit_transaction(date, postings, payee?, narration?, tags?, status?)`
**CLI**: `finkit submit --date DATE --postings JSON [options]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `date` | str | yes | | YYYY-MM-DD format |
| `postings` | list[dict] | yes | | Array of posting objects (see below) |
| `payee` | str | no | null | Payee name |
| `narration` | str | no | null | Transaction description |
| `tags` | list[str] | no | null | Tags for categorization |
| `status` | str | no | cleared | pending, cleared, or reconciled |

**Posting object fields**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `account` | str | yes | Account name (fuzzy-matched) |
| `amount` | str | yes | Decimal string, e.g. "150.00" |
| `currency` | str | yes | Currency code |
| `price` | str | no | Price per unit for trades/conversions |
| `price_currency` | str | no | Currency the price is in |
| `cost_amount` | str | no | Per-unit cost basis for lot tracking |
| `cost_currency` | str | no | Currency of the cost basis |
| `cost_date` | str | no | Original acquisition date for lot |

**Example** (simple expense):
```bash
finkit submit --date 2025-01-15 --payee "Whole Foods" \
  --postings '[
    {"account": "Expenses:Groceries", "amount": "85.50", "currency": "USD"},
    {"account": "Assets:Chase:Checking", "amount": "-85.50", "currency": "USD"}
  ]'
```

**Example** (multi-currency transfer with exchange rate):
```bash
finkit submit --date 2025-03-15 --payee "Wire transfer" --narration "USD to INR" \
  --postings '[
    {"account": "Assets:Chase:Checking", "amount": "-1000.00", "currency": "USD",
     "price": "83.50", "price_currency": "INR"},
    {"account": "Assets:HDFC:Savings", "amount": "83500.00", "currency": "INR"}
  ]'
```

**Example** (stock purchase creating a lot):
```bash
finkit submit --date 2025-02-01 --payee "Buy AAPL" \
  --postings '[
    {"account": "Assets:Schwab:Brokerage", "amount": "10", "currency": "AAPL",
     "cost_amount": "185.00", "cost_currency": "USD"},
    {"account": "Assets:Schwab:Cash", "amount": "-1850.00", "currency": "USD"}
  ]'
```

**Output**: `{"uuid": "a3f1b2c4"}`

**Errors**:
- `UnbalancedTransactionError` --- postings do not sum to zero
- `AccountNotFoundError` --- account name cannot be matched (below 0.85 confidence)
- Account not open on transaction date

---

## 4. amend_transaction

Amend or delete an existing transaction by its 8-char UUID.

**MCP**: `amend_transaction(uuid, updates?, delete?)`
**CLI**: `finkit amend UUID [--updates JSON] [--delete]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `uuid` | str | yes | | 8-char hex UUID of the transaction |
| `updates` | dict | no | null | Fields to update: date, payee, narration, status, postings |
| `delete` | bool | no | false | If true, delete the transaction |

**Example**:
```bash
# Update payee and narration
finkit amend a3f1b2c4 --updates '{"payee": "Whole Foods Market", "narration": "Organic groceries"}'

# Delete a transaction
finkit amend a3f1b2c4 --delete
```

**Output**: `{"status": "ok"}`

**Errors**:
- Transaction UUID not found
- Updated postings do not balance

---

## 5. assert_balance

Verify that an account has the expected balance on a given date.

**MCP**: `assert_balance(account, date, expected_amount, currency?)`
**CLI**: `finkit assert-balance ACCOUNT DATE AMOUNT [--currency CUR]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `account` | str | yes | | Account name |
| `date` | str | yes | | YYYY-MM-DD |
| `expected_amount` | str | yes | | Expected balance as decimal string |
| `currency` | str | no | USD | Currency of the expected balance |

**Example**:
```bash
finkit assert-balance Assets:Chase:Checking 2025-01-31 4523.47
```

**Output**:
```json
{
  "matches": true,
  "expected": "4523.47",
  "actual": "4523.47",
  "difference": "0.00"
}
```

**Errors**:
- Account not found

---

## 6. query

Run an ad-hoc read-only SQL query against the database.

**MCP**: `query(sql, params?)`
**CLI**: `finkit query SQL`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sql` | str | yes | | SQL SELECT statement |
| `params` | list or dict | no | null | Query parameters for parameterized queries |

The tool enforces `PRAGMA query_only = ON` before executing. INSERT, UPDATE, DELETE, and DDL statements are rejected.

**Example**:
```bash
finkit query "SELECT * FROM accounts WHERE type = 'Assets'"
finkit query "SELECT year_month, total FROM s_monthly_spending WHERE account_id = 3 ORDER BY year_month DESC LIMIT 6"
```

**Output**: Array of row objects.

**Errors**:
- SQL syntax error
- Attempted write operation rejected by query_only pragma

---

## 7. get_balances

Get current balances for accounts, reading from `s_daily_balances`.

**MCP**: `get_balances(account?, account_type?, as_of_date?)`
**CLI**: `finkit balances [--account NAME] [--type TYPE] [--as-of DATE]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `account` | str | no | null | Filter by account name (fuzzy match) |
| `account_type` | str | no | null | Filter by type: Assets, Liabilities, etc. |
| `as_of_date` | str | no | today | Balance as of this date (YYYY-MM-DD) |

**Example**:
```bash
finkit balances --type Assets
finkit balances --account Chase --as-of 2025-01-31
```

**Output**: Array of `{"account": "...", "balance": "...", "currency": "..."}` objects.

---

## 8. get_transactions

Search and retrieve transactions with optional filters.

**MCP**: `get_transactions(date_from?, date_to?, payee?, account?, tags?, amount_min?, amount_max?, uuid?, status?, limit?)`
**CLI**: `finkit transactions [options]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `date_from` | str | no | null | Start date (YYYY-MM-DD) |
| `date_to` | str | no | null | End date (YYYY-MM-DD) |
| `payee` | str | no | null | Filter by payee (fuzzy match) |
| `account` | str | no | null | Filter by account name |
| `tags` | list[str] | no | null | Filter by tags |
| `amount_min` | str | no | null | Minimum posting amount |
| `amount_max` | str | no | null | Maximum posting amount |
| `uuid` | str | no | null | Filter by transaction UUID |
| `status` | str | no | null | cleared, pending, or reconciled |
| `limit` | int | no | 100 | Maximum rows to return |

**Example**:
```bash
finkit transactions --from 2025-01-01 --to 2025-01-31 --payee "Whole Foods"
finkit transactions --account Expenses:Groceries --limit 20
finkit transactions --uuid a3f1b2c4
```

**Output**: Array of transaction objects with nested postings.

---

## 9. import_file

Import transactions from a CSV or XLSX file into the ledger.

**MCP**: `import_file(file_path, account, mapping_name?, institution?)`
**CLI**: `finkit import FILE_PATH ACCOUNT [--mapping NAME] [--institution NAME]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | str | yes | | Path to CSV/XLSX file |
| `account` | str | yes | | Target account name |
| `mapping_name` | str | no | null | Saved column mapping name to use |
| `institution` | str | no | null | Financial institution (e.g. chase, hdfc) |

The file is copied to `~/finance/statements/{year}/`. SHA-256 ensures re-importing the same file is a no-op. All original fields are preserved in `raw_extractions`. Categorization rules are applied automatically.

**Example**:
```bash
finkit import ~/Downloads/chase-jan-2025.csv Assets:Chase:Checking --institution chase
```

**Output**: `{"imported": 47, "skipped_duplicates": 3, "source_file_id": 1}`

**Errors**:
- `DuplicateImportError` --- file already imported (same SHA-256)
- File format not recognized
- Account not found

---

## 10. import_pdf

Extract tabular data from a PDF bank or brokerage statement.

**MCP**: `import_pdf(file_path, password?)`
**CLI**: `finkit import-pdf FILE_PATH [--password PW]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | str | yes | | Path to the PDF file |
| `password` | str | no | null | Password for encrypted PDFs |

Returns structured table data for further processing. With an LLM client, the data can be interpreted and fed into `import_file`. Without an LLM, tables are returned as CSV-formatted text.

**Example**:
```bash
finkit import-pdf ~/Downloads/schwab-statement-q1-2025.pdf
finkit import-pdf ~/Downloads/hdfc-statement.pdf --password mypassword
```

**Output**: `{"pages": [...], "tables": [...], "text": "..."}`

---

## 11. fetch_prices

Fetch latest market prices for stocks, crypto, and forex pairs.

**MCP**: `fetch_prices(symbols?, coins?, forex_pairs?)`
**CLI**: `finkit fetch-prices [--symbols LIST] [--coins LIST] [--forex-pairs LIST]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `symbols` | list[str] | no | null | Stock/ETF tickers (e.g. AAPL, VTI) |
| `coins` | list[str] | no | null | CoinGecko coin IDs (e.g. bitcoin) |
| `forex_pairs` | list[str] | no | null | Forex pairs (e.g. USD/INR) |

Fetched prices are written to the `prices` table and trigger a refresh of `s_portfolio_holdings` and `s_net_worth`.

**Example**:
```bash
finkit fetch-prices --symbols AAPL,VTI --coins bitcoin --forex-pairs USD/INR,EUR/USD
```

**Output**: `{"prices_updated": 4, "commodities": ["AAPL", "VTI", "BTC", "USD"]}`

**Errors**:
- Network error fetching prices
- Unknown ticker symbol

**CLI also supports manual price entry**:
```bash
finkit manual-price HDFC-EQUITY-FUND INR 45.67 2025-01-15
```

---

## 12. analyze_spending

Analyze spending patterns by category with month-over-month trends.

**MCP**: `analyze_spending(year_month?, months?, category?, currency?)`
**CLI**: `finkit spending [--month YYYY-MM] [--months N] [--category NAME] [--currency CUR]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year_month` | str | no | current | Month to analyze (YYYY-MM) |
| `months` | int | no | 6 | Number of months for trend analysis |
| `category` | str | no | null | Filter to a specific expense category |
| `currency` | str | no | USD | Currency for aggregation |

Reads from `s_monthly_spending`. Spending is keyed by the expense/income account, not the source bank account. Supports budget comparison when budgets are configured.

**Example**:
```bash
finkit spending --month 2025-01 --months 12
finkit spending --category Expenses:Groceries
```

**Output**: Totals by category, monthly trends, anomaly flags.

---

## 13. analyze_portfolio

Analyze investment portfolio: holdings, allocation, and unrealized gains.

**MCP**: `analyze_portfolio(currency?)`
**CLI**: `finkit portfolio [--currency CUR]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `currency` | str | no | base currency | Currency for valuation |

Reads from `s_portfolio_holdings` and `s_net_worth`. Returns total net worth (per currency and consolidated), asset allocation percentages, per-holding unrealized gain/loss, and lot-level detail.

**Example**:
```bash
finkit portfolio
finkit portfolio --currency INR
```

---

## 14. report_capital_gains

Generate a capital gains report for tax filing.

**MCP**: `report_capital_gains(year?, currency?)`
**CLI**: `finkit capital-gains [--year YEAR] [--currency CUR]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year` | int | no | current year | Tax year to report |
| `currency` | str | no | null | Currency filter |

Reads from `s_yearly_capital_gains` for totals and `lot_dispositions` for detail. Flags wash sales. Subtotals by jurisdiction for cross-border tax reporting.

**Example**:
```bash
finkit capital-gains --year 2024
finkit capital-gains --year 2024 --currency USD
```

---

## 15. what_if_sell

Read-only simulation of selling a position. Does not modify any data.

**MCP**: `what_if_sell(account, commodity, quantity, booking_method?, sell_price?)`
**CLI**: `finkit what-if ACCOUNT COMMODITY QUANTITY [--method METHOD] [--price PRICE]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `account` | str | yes | | Investment account name |
| `commodity` | str | yes | | Ticker/symbol to simulate selling |
| `quantity` | str | yes | | Number of units to sell |
| `booking_method` | str | no | FIFO | Lot selection: FIFO, LIFO, HIFO |
| `sell_price` | str | no | latest price | Assumed sell price per unit |

Returns which lots would be sold, gain/loss for each, short vs long term classification. Warns if any lots have a `lock_until` date in the future (ELSS lock-in).

**Example**:
```bash
finkit what-if Assets:Schwab:Brokerage AAPL 50 --method FIFO --price 195.00
```

---

## 16. export

Export ledger data as CSV or JSON.

**MCP**: `export(data_type, format?, sql?, file_path?)`
**CLI**: `finkit export --format csv|json --sql SQL [--output FILE]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `data_type` | str | yes (MCP) | | transactions, balances, or custom |
| `format` | str | no | csv | Output format: csv or json |
| `sql` | str | conditional | | SQL query (required for data_type=custom, CLI always uses this) |
| `file_path` | str | no | null | Destination file; returns inline if omitted |

**Example**:
```bash
finkit export --format csv --sql "SELECT * FROM transactions WHERE date >= '2025-01-01'" --output txns.csv
finkit export --format json --sql "SELECT * FROM s_monthly_spending"
```

---

## 17. categorize

Manage categorization rules for auto-categorizing transactions.

**MCP**: `categorize(action, pattern?, target_account?, pattern_type?, rule_id?, institution?)`
**CLI**: `finkit categorize add|remove|list [options]`

### Add a rule

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | str | yes | | Payee pattern to match |
| `target_account` | str | yes | | Expense/income account to categorize into |
| `pattern_type` | str | no | substring | substring, regex, or exact |
| `institution` | str | no | null | Limit rule to a specific institution |
| `priority` | int | no | 0 | Higher priority rules are checked first |

### Remove a rule

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `rule_id` | int | yes | ID of the rule to remove |

### List rules

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `institution` | str | no | Filter rules by institution |

**Example**:
```bash
finkit categorize add "WHOLE FOODS" Expenses:Groceries
finkit categorize add "AMAZON.*PRIME" Expenses:Subscriptions --pattern-type regex
finkit categorize remove 3
finkit categorize list --institution chase
```

---

## 18. corporate_action

Record a corporate action (stock split, reverse split, bonus shares) and adjust all affected lots.

**MCP**: `corporate_action(commodity, action_type, ratio, date?, narration?)`
**CLI**: `finkit corporate-action COMMODITY ACTION_TYPE RATIO [--date DATE] [--narration TEXT]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `commodity` | str | yes | | Ticker/symbol affected |
| `action_type` | str | yes | | split, reverse_split, or bonus |
| `ratio` | str | yes | | Ratio as decimal (e.g. "4" for 4:1 split) |
| `date` | str | no | today | Date of the action (YYYY-MM-DD) |
| `narration` | str | no | null | Description |

For a 4:1 split: all non-disposed lots get `quantity *= 4` and `cost_price /= 4`. A transaction is recorded for audit trail. All summaries are refreshed.

**Example**:
```bash
finkit corporate-action AAPL split 4 --date 2024-11-01 --narration "4:1 stock split"
```

---

## 19. undo_import

Reverse a file import by removing all transactions and data from that source file.

**MCP**: `undo_import(source_file_id)`
**CLI**: `finkit undo-import SOURCE_FILE_ID`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_file_id` | int | yes | ID of the source file to undo |

Deletes all transactions, postings, raw extractions, and the source file record. Cascades correctly. All summaries are refreshed within the same transaction.

**Example**:
```bash
finkit undo-import 3
```

**Output**: `{"status": "ok", "deleted_transactions": 47}`

---

## 20. import_directory

Batch import all matching files from a directory tree.

**MCP**: `import_directory(source_dir, account, institution?, glob_pattern?, recursive?, mapping_name?)`
**CLI**: `finkit import-dir SOURCE_DIR ACCOUNT [options]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_dir` | str | yes | | Path to the source directory |
| `account` | str | yes | | Target account for all files |
| `institution` | str | no | null | Financial institution |
| `glob_pattern` | str | no | *.csv | File pattern to match |
| `recursive` | bool | no | true | Whether to search subdirectories |
| `mapping_name` | str | no | null | Saved column mapping to use |

Walks the directory, imports each matching file, skips already-imported files (SHA-256 dedup). Original files are never moved or deleted.

**Example**:
```bash
finkit import-dir ~/Downloads/chase-statements/ Assets:Chase:Checking \
  --institution chase --glob "*.csv" --mapping chase_checking
```

**Output**: `{"imported_files": 5, "skipped_files": 2, "total_transactions": 234}`

---

## Utility Commands (CLI only)

### rebuild

Rebuild all summary tables from core data. Idempotent.

```bash
finkit rebuild
```

### backup

Create a database backup using the SQLite backup API (not file copy).

```bash
finkit backup ~/finance/backups/finkit-2025-01-31.db
```

### accounts

List all accounts, optionally filtered by type.

```bash
finkit accounts
finkit accounts --type Assets
```
