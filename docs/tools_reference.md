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
| `source_file_id` | int | no | null | Link to source document from ingest_document. Enables undo_import. |

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

**MCP**: `assert_balance(account_name, date, expected_amount, currency?)`
**CLI**: `finkit assert-balance ACCOUNT DATE AMOUNT [--currency CUR]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `account_name` | str | yes | | Account name |
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

**MCP**: `query(sql)`
**CLI**: `finkit query SQL`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sql` | str | yes | | SQL SELECT statement |

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

**MCP**: `get_balances(account_name?, account_type?, as_of_date?)`
**CLI**: `finkit balances [--account NAME] [--type TYPE] [--as-of DATE]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `account_name` | str | no | null | Filter by account name (fuzzy match) |
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

**MCP**: `get_transactions(date_from?, date_to?, payee?, account_name?, tags?, amount_min?, amount_max?, uuid?, status?, limit?)`
**CLI**: `finkit transactions [options]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `date_from` | str | no | null | Start date (YYYY-MM-DD) |
| `date_to` | str | no | null | End date (YYYY-MM-DD) |
| `payee` | str | no | null | Filter by payee (fuzzy match) |
| `account_name` | str | no | null | Filter by account name |
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

Import transactions from a CSV, XLSX, or PDF file into the ledger.

**MCP**: `import_file(file_path, account_name, mapping_name?, institution?)`
**CLI**: `finkit import FILE_PATH ACCOUNT [--mapping NAME] [--institution NAME]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | str | yes | | Path to CSV, XLSX, or PDF file |
| `account_name` | str | yes | | Target account name |
| `mapping_name` | str | no | null | Saved column mapping name to use (CSV/XLSX only) |
| `institution` | str | no | null | Financial institution (e.g. chase, hdfc). For PDFs, the institution is auto-detected from file content when not specified |

The file is copied to `~/finance/statements/{year}/`. SHA-256 ensures re-importing the same file is a no-op. All original fields are preserved in `raw_extractions`. Categorization rules are applied automatically. For PDF files, institution-specific parsers extract transactions directly from the statement text.

**Example**:
```bash
finkit import ~/Downloads/chase-jan-2025.csv Assets:Chase:Checking --institution chase
finkit import ~/Downloads/hdfc-statement.pdf Assets:HDFC:Savings
```

**Output**: `{"imported": 47, "skipped_duplicates": 3, "source_file_id": 1}`

**Errors**:
- `DuplicateImportError` --- file already imported (same SHA-256)
- File format not recognized
- Account not found

---

## 10. import_pdf

Extract raw text and tables from a PDF bank or brokerage statement. This is an extraction-only tool that returns unprocessed content; it does not create transactions in the ledger. For full PDF import with transaction creation, use `import_file` instead.

**MCP**: `import_pdf(file_path, password?)`
**CLI**: `finkit import-pdf FILE_PATH [--password PW]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | str | yes | | Path to the PDF file |
| `password` | str | no | null | Password for encrypted PDFs |

Returns raw text and structured table data for inspection or further processing. With an LLM client, the data can be interpreted and fed into `submit_transaction`. For automated PDF-to-transaction import, use `import_file` with a PDF path instead.

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

**MCP**: `what_if_sell(account_name, commodity, quantity, booking_method?, sell_price?)`
**CLI**: `finkit what-if ACCOUNT COMMODITY QUANTITY [--method METHOD] [--price PRICE]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `account_name` | str | yes | | Investment account name |
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

**MCP**: `import_directory(source_dir, account_name, institution?, glob_pattern?, recursive?, mapping_name?)`
**CLI**: `finkit import-dir SOURCE_DIR ACCOUNT [options]`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_dir` | str | yes | | Path to the source directory |
| `account_name` | str | yes | | Target account for all files |
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

## 21. ingest_document

Archive any financial document, extract its content, classify the document type, and return extracted text with structured hints for LLM interpretation. Does not create transactions.

**MCP**: `ingest_document(file_path, password?, institution?)`
**CLI**: (MCP only --- designed for LLM interaction)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | str | yes | | Path to any financial document (PDF, CSV, XLSX) |
| `password` | str | no | null | Password for encrypted PDFs |
| `institution` | str | no | null | Institution name override for classification |

Archives the file (copy + SHA-256 dedup), extracts text (PDF) or rows (CSV/XLSX), classifies the document type, and returns everything to the LLM. Use `submit_transaction` or `submit_transactions` with the returned `source_file_id` to create transactions.

**Example flow**:
1. `ingest_document("~/Downloads/payslip-jan-2025.pdf")` --- returns extracted text + document_type="payslip" + hints
2. LLM interprets the content using extraction hints
3. `submit_transactions([...], source_file_id=3)` --- creates transactions linked to the document

**Output**: `{"source_file_id": 3, "is_new": true, "file_type": "pdf", "document_type": "payslip", "confidence": "high", "text": "...", "extraction_hints": {...}, "existing_accounts": [...]}`

**Errors**:
- File not found
- Duplicate file (returns `is_new: false`)

---

## 22. submit_transactions

Submit multiple transactions atomically. All succeed or all fail.

**MCP**: `submit_transactions(transactions, source_file_id?)`
**CLI**: (MCP only)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `transactions` | list[dict] | yes | | List of transaction dicts, each with date, postings, and optional payee, narration, tags, status |
| `source_file_id` | int | no | null | Shared source document ID from ingest_document |

More efficient than calling submit_transaction repeatedly. Single database transaction, single summary refresh. All transactions are linked to the same source_file_id for undo_import support.

**Example**:
```json
{
  "transactions": [
    {
      "date": "2025-01-15",
      "payee": "Employer",
      "narration": "January salary",
      "postings": [
        {"account": "Income:Salary:Acme", "amount": "-5000.00", "currency": "USD"},
        {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"}
      ]
    },
    {
      "date": "2025-01-15",
      "payee": "IRS",
      "narration": "Federal tax withholding",
      "postings": [
        {"account": "Assets:Chase:Checking", "amount": "-750.00", "currency": "USD"},
        {"account": "Expenses:Taxes:Federal", "amount": "750.00", "currency": "USD"}
      ]
    }
  ],
  "source_file_id": 3
}
```

**Output**: `{"uuids": ["a1b2c3d4", "e5f6a7b8"], "count": 2, "source_file_id": 3}`

**Errors**:
- Any transaction unbalanced --- entire batch rolls back
- Invalid source_file_id

---

## 23. setup_payroll_accounts

Create the standard payroll account hierarchy for an employer.

**MCP**: `setup_payroll_accounts(employer, jurisdiction?)`
**CLI**: (MCP only)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `employer` | str | yes | | Employer name (e.g., "Acme") |
| `jurisdiction` | str | no | US | Tax jurisdiction: US or IN |

Idempotent --- skips accounts that already exist. Creates Income:Salary:{Employer}, Expenses:Taxes:\*, Expenses:Benefits:\*, and Assets:Retirement:\* accounts.

**Example**: `setup_payroll_accounts("Acme", jurisdiction="US")`

**Output**: `{"gross": "Income:Salary:Acme", "federal_tax": "Expenses:Taxes:Federal", ...}`

---

## 24. reconcile_tax_document

Compare tax form data against recorded transactions.

**MCP**: `reconcile_tax_document(form_type, year, fields)`
**CLI**: (MCP only)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `form_type` | str | yes | | Tax form: w2, 1099_int, 1099_div, 1099_b, form16 |
| `year` | int | yes | | Tax year |
| `fields` | dict | yes | | Key-value pairs from the tax form (amounts as decimal strings) |

Returns field-by-field comparison with match/mismatch/missing status. For missing income (e.g., interest from 1099-INT not in ledger), generates suggested transactions.

**Example**:
```bash
reconcile_tax_document("w2", 2024, {"wages": "60000.00", "federal_tax": "9000.00"})
```

**Output**: comparisons array with status per field, missing_income array, summary counts.

---

## 25. tax_readiness_report

Generate a tax readiness report for a given year.

**MCP**: `tax_readiness_report(year?, jurisdiction?)`
**CLI**: (MCP only)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year` | int | no | previous year | Tax year |
| `jurisdiction` | str | no | US | Tax jurisdiction: US or IN |

Queries the entire ledger to build a comprehensive picture of captured income, taxes paid, capital gains, and deductible expenses. Flags gaps like missing pay periods.

**Output**: income breakdown, taxes_paid, capital_gains, deductible_expenses, gaps list.

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

---

## New Utilities

### recategorize_posting

Change one posting's account without rebuilding all postings. Only changes the account — amounts stay the same.

**MCP tool**: `recategorize_posting(uuid, old_account, new_account, posting_id?)`
**CLI**: `finkit recategorize-posting UUID --old-account NAME --new-account NAME [--posting-id ID]`

Parameters:
- `uuid` — Transaction UUID
- `old_account` — Current account name (exact match)
- `new_account` — New account name (fuzzy match OK)
- `posting_id` — Target a specific posting ID when multiple postings share the same account

Refuses to operate on lot-tracked accounts (either old or new).

### batch_recategorize

Recategorize all transactions matching a payee pattern from one account to another.

**MCP tool**: `batch_recategorize(pattern, old_account, new_account, pattern_type?, dry_run?)`
**CLI**: `finkit batch-recategorize PATTERN --old-account OLD --new-account NEW [--pattern-type substring] [--dry-run]`

Parameters:
- `pattern` — Payee pattern to match
- `old_account` — Current account name of postings to change
- `new_account` — New account name to assign
- `pattern_type` — Match type: substring (default), regex, or exact
- `dry_run` — MCP default: true. CLI: use `--dry-run` flag

### payee_rules

Manage payee normalization rules. Maps raw bank payees to clean canonical names.

**MCP tool**: `payee_rules(action, pattern?, canonical_name?, pattern_type?, priority?, rule_id?)`
**CLI**: `finkit payee-rules add|remove|list ...`

Actions:
- `add` — Add a rule: `payee_rules(action="add", pattern="META 4100", canonical_name="Meta")`
- `remove` — Remove by ID: `payee_rules(action="remove", rule_id=1)`
- `list` — List all rules

### normalize_existing_payees

Apply payee normalization rules to all existing transactions retroactively. Sets `normalized_payee` column without overwriting the raw `payee`.

**MCP tool**: `normalize_existing_payees(dry_run?)`
**CLI**: `finkit normalize-payees [--dry-run]`

### find_duplicates

Find potential duplicate transactions across different source files.

**MCP tool**: `find_duplicates(tolerance_days?, tolerance_amount?, account_name?)`
**CLI**: `finkit find-duplicates [--days 3] [--tolerance 0.01] [--account NAME]`

Returns pairs with confidence scoring: high (exact date + amount + payee), medium (amount match within date window).

### merge_duplicates

Merge two duplicate transactions by keeping one and deleting the other.

**MCP tool**: `merge_duplicates(keep_uuid, delete_uuid, enrich?)`
**CLI**: `finkit merge-duplicates KEEP_UUID DELETE_UUID [--enrich]`

With `enrich=true`, copies metadata (payee, narration, tags) from the deleted transaction to the kept one.

### detect_transfers

Detect potential inter-account transfers that appear as two separate transactions (one outgoing, one incoming) with Uncategorized contra postings.

**MCP tool**: `detect_transfers(tolerance_days?)`
**CLI**: `finkit detect-transfers [--days 3]`

### link_transfer

Link two transfer transactions: keeps `uuid_from`, replaces its Uncategorized posting with the real account from `uuid_to`, deletes `uuid_to`.

**MCP tool**: `link_transfer(uuid_from, uuid_to)`
**CLI**: `finkit link-transfer UUID_FROM UUID_TO`

### import_report

Generate a post-import health report covering uncategorized transactions, potential duplicates, balance anomalies, missing periods, and orphaned source files.

**MCP tool**: `import_report(source_file_id?)`
**CLI**: `finkit import-report [SOURCE_FILE_ID]`

### learn_template

Extract text from a document and return instructions for creating a reusable template.

**MCP tool**: `learn_template(file_path, template_name, institution?, password?)`
**CLI**: `finkit learn-template FILE_PATH NAME [--institution INST] [--password PASS]`

### save_document_template

Save a document template for automated extraction. Used after `learn_template`.

**MCP tool**: `save_document_template(name, document_type, match_keywords, template_json, account_mapping?, institution?)`

### apply_template

Apply a document template to extract and submit transactions from a document. Auto-detects the template if `template_name` is omitted.

**MCP tool**: `apply_template(file_path, template_name?, password?, dry_run?)`
**CLI**: `finkit apply-template FILE_PATH [--template NAME] [--password PASS] [--dry-run]`

### list_templates

List all saved document templates.

**MCP tool**: `list_templates(institution?)`
**CLI**: `finkit list-templates [--institution INST]`

### delete_template

Delete a document template.

**MCP tool**: `delete_template(name)`
**CLI**: `finkit delete-template NAME`
