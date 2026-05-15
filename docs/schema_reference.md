# FinKit Schema Reference

All tables in the FinKit SQLite database. Core tables store normalized source-of-truth data. Summary tables (prefixed with `s_`) are derived and rebuildable via `finkit rebuild`.

All monetary amounts are stored as `TEXT` for exact decimal precision. All dates are ISO 8601 `TEXT` (`YYYY-MM-DD` for dates, `YYYY-MM-DDTHH:MM:SS` for timestamps). UUIDs are 8-character hex strings. Foreign keys are enforced.

---

## Core Tables

### accounts

The chart of accounts. Names use colon-separated hierarchy.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `name` | TEXT | NOT NULL, UNIQUE | Colon-separated path, e.g. `Assets:Chase:Checking` |
| `type` | TEXT | NOT NULL | Root type: Assets, Liabilities, Income, Expenses, Equity |
| `currency` | TEXT | DEFAULT 'USD' | Default currency for this account |
| `booking_method` | TEXT | | Lot selection for investment accounts: FIFO, LIFO, HIFO |
| `institution` | TEXT | | Financial institution, e.g. `chase`, `hdfc` |
| `asset_class` | TEXT | | cash, equity, debt, crypto, real_estate |
| `jurisdiction` | TEXT | | Tax jurisdiction: US, IN, EU |
| `opened_at` | TEXT | NOT NULL | ISO 8601 date when the account was opened |
| `closed_at` | TEXT | | ISO 8601 date when the account was closed |

**Indexes**: `idx_accounts_type(type)`

```sql
-- List all asset accounts
SELECT name, currency, institution FROM accounts WHERE type = 'Assets';

-- Find investment accounts
SELECT name, booking_method, asset_class, jurisdiction
FROM accounts WHERE booking_method IS NOT NULL;
```

---

### transactions

Immutable transaction headers. Linked to postings for the double-entry detail.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `uuid` | TEXT | NOT NULL, UNIQUE | 8-char hex for stable human-readable identification |
| `date` | TEXT | NOT NULL | Transaction date (YYYY-MM-DD) |
| `payee` | TEXT | | Raw payee name from the source |
| `narration` | TEXT | | Free-text description |
| `normalized_payee` | TEXT | | Canonical payee name (set by normalization rules) |
| `status` | TEXT | DEFAULT 'cleared' | pending, cleared, reconciled |
| `source_file_id` | INTEGER | FK -> source_files | Link to the imported file, if any |
| `raw_extraction_id` | INTEGER | FK -> raw_extractions | Link to the raw parsed row |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |
| `modified_at` | TEXT | | ISO 8601 timestamp of last amendment |

**Indexes**: `idx_transactions_date(date)`, `idx_transactions_uuid(uuid)`, `idx_transactions_payee(payee)`, `idx_transactions_source(source_file_id)`

```sql
-- Recent transactions
SELECT uuid, date, payee, narration, status
FROM transactions ORDER BY date DESC LIMIT 20;

-- Transactions from a specific import
SELECT t.uuid, t.date, t.payee
FROM transactions t
WHERE t.source_file_id = 1;
```

---

### postings

Individual legs of a transaction. Postings within a transaction must sum to zero.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `transaction_id` | INTEGER | NOT NULL, FK -> transactions (CASCADE) | Parent transaction |
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Target account |
| `amount` | TEXT | NOT NULL | Decimal amount as TEXT |
| `currency` | TEXT | NOT NULL | Currency code (USD, INR, AAPL, BTC, ...) |
| `cost_amount` | TEXT | | Per-unit cost basis for lot tracking |
| `cost_currency` | TEXT | | Currency of the cost basis |
| `cost_date` | TEXT | | Original acquisition date |
| `price` | TEXT | | Market/conversion price per unit |
| `price_currency` | TEXT | | Currency the price is denominated in |
| `lot_id` | INTEGER | FK -> lots | Link to the lot for investment postings |

**Indexes**: `idx_postings_transaction(transaction_id)`, `idx_postings_account(account_id)`

```sql
-- All postings for a transaction
SELECT a.name, p.amount, p.currency, p.price, p.price_currency
FROM postings p
JOIN accounts a ON a.id = p.account_id
WHERE p.transaction_id = 42;

-- Account activity
SELECT t.date, t.payee, p.amount, p.currency
FROM postings p
JOIN transactions t ON t.id = p.transaction_id
JOIN accounts a ON a.id = p.account_id
WHERE a.name = 'Assets:Chase:Checking'
ORDER BY t.date DESC;
```

---

### transaction_tags

Tags associated with transactions, for categorization and filtering.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `transaction_id` | INTEGER | NOT NULL, FK -> transactions (CASCADE) | Parent transaction |
| `tag` | TEXT | NOT NULL | Tag string |

**Primary key**: `(transaction_id, tag)`

```sql
-- Find transactions with a specific tag
SELECT t.uuid, t.date, t.payee
FROM transactions t
JOIN transaction_tags tt ON tt.transaction_id = t.id
WHERE tt.tag = 'tax-deductible';
```

---

### lots

Investment lot tracking. Each purchase creates a lot. `quantity` is decremented on sell; `original_quantity` is immutable for rebuild.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Investment account holding the lot |
| `commodity` | TEXT | NOT NULL | Ticker/symbol: AAPL, VTSAX, BTC, etc. |
| `quantity` | TEXT | NOT NULL | Remaining quantity (mutable, decremented on sell) |
| `original_quantity` | TEXT | NOT NULL | Original purchase quantity (immutable) |
| `cost_price` | TEXT | NOT NULL | Per-unit cost basis |
| `cost_currency` | TEXT | NOT NULL | Currency of the cost basis |
| `acquired_date` | TEXT | NOT NULL | Purchase date (YYYY-MM-DD) |
| `label` | TEXT | | Optional label: "Jan 2024 SIP", "Bonus lump sum" |
| `lock_until` | TEXT | | Lock-in expiry date for ELSS funds |
| `source_transaction_id` | INTEGER | FK -> transactions | The buy transaction that created this lot |
| `disposed` | INTEGER | DEFAULT 0 | 1 if fully sold/redeemed |

**Indexes**: `idx_lots_account_commodity(account_id, commodity)`, `idx_lots_commodity_disposed(commodity, disposed)`

```sql
-- Current holdings
SELECT l.commodity, l.quantity, l.cost_price, l.cost_currency, l.acquired_date
FROM lots l
WHERE l.disposed = 0 AND l.account_id = 5;

-- Lots with lock-in periods
SELECT l.commodity, l.quantity, l.lock_until, a.name
FROM lots l
JOIN accounts a ON a.id = l.account_id
WHERE l.lock_until IS NOT NULL AND l.disposed = 0;
```

---

### lot_dispositions

Records each sale/redemption event against a specific lot.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `lot_id` | INTEGER | NOT NULL, FK -> lots | Lot being partially or fully sold |
| `sell_transaction_id` | INTEGER | NOT NULL, FK -> transactions | The sell transaction |
| `quantity` | TEXT | NOT NULL | Quantity sold from this lot |
| `proceeds_per_unit` | TEXT | NOT NULL | Sale price per unit |
| `proceeds_currency` | TEXT | NOT NULL | Currency of proceeds |
| `gain_loss` | TEXT | NOT NULL | Total gain or loss |
| `gain_loss_currency` | TEXT | NOT NULL | Currency of the gain/loss |
| `term` | TEXT | NOT NULL | "short" or "long" |
| `wash_sale` | INTEGER | DEFAULT 0 | 1 if loss disallowed under wash sale rules |
| `wash_sale_adjustment` | TEXT | | Amount of disallowed loss |

**Indexes**: `idx_lot_dispositions_sell(sell_transaction_id)`

```sql
-- Capital gains detail for 2024
SELECT l.commodity, ld.quantity, ld.proceeds_per_unit, ld.gain_loss, ld.term, ld.wash_sale
FROM lot_dispositions ld
JOIN lots l ON l.id = ld.lot_id
JOIN transactions t ON t.id = ld.sell_transaction_id
WHERE t.date >= '2024-01-01' AND t.date <= '2024-12-31';
```

---

### prices

Historical prices for commodities, currencies, and exchange rates.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `commodity` | TEXT | NOT NULL | Ticker, coin ID, or base currency |
| `currency` | TEXT | NOT NULL | Quote currency |
| `price` | TEXT | NOT NULL | Price as decimal text |
| `date` | TEXT | NOT NULL | Price date (YYYY-MM-DD) |
| `source` | TEXT | | yfinance, coingecko, manual, import |

**Unique constraint**: `(commodity, currency, date)`
**Indexes**: `idx_prices_commodity_date(commodity, date)`

```sql
-- Latest AAPL price
SELECT price, date, source FROM prices
WHERE commodity = 'AAPL' AND currency = 'USD'
ORDER BY date DESC LIMIT 1;

-- USD/INR exchange rate history
SELECT date, price FROM prices
WHERE commodity = 'USD' AND currency = 'INR'
ORDER BY date DESC LIMIT 30;
```

---

### source_files

Registry of imported statement files. SHA-256 hash ensures dedup.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `path` | TEXT | NOT NULL | Path within `statements/` dir, e.g. `2024/chase-jan-2024.csv` |
| `original_path` | TEXT | | Absolute path of the user's original file |
| `sha256` | TEXT | NOT NULL, UNIQUE | SHA-256 hash for dedup |
| `institution` | TEXT | | Financial institution |
| `file_type` | TEXT | | csv, xlsx, xls, pdf |
| `imported_at` | TEXT | NOT NULL | ISO 8601 timestamp |
| `original_filename` | TEXT | | Original file name |

**Indexes**: `idx_source_files_institution(institution)`

```sql
-- List all imported files
SELECT id, original_filename, institution, imported_at FROM source_files ORDER BY imported_at DESC;
```

---

### raw_extractions

Every row from every imported file, preserved as a JSON blob. Nothing from the source file is discarded.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `source_file_id` | INTEGER | NOT NULL, FK -> source_files | Parent file |
| `row_index` | INTEGER | | Row position in the original file |
| `raw_data` | TEXT | NOT NULL | JSON blob of all original fields |
| `extraction_date` | TEXT | NOT NULL | ISO 8601 timestamp |

**Indexes**: `idx_raw_extractions_source(source_file_id)`

```sql
-- View raw data for an imported file
SELECT row_index, raw_data FROM raw_extractions WHERE source_file_id = 1 LIMIT 5;
```

---

### categorization_rules

Pattern-matching rules for auto-categorizing transactions during import.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `pattern` | TEXT | NOT NULL | Pattern string to match against payee/narration |
| `pattern_type` | TEXT | DEFAULT 'substring' | substring, regex, exact |
| `target_account` | TEXT | NOT NULL | Account to categorize into |
| `institution` | TEXT | | Only apply for this institution |
| `priority` | INTEGER | DEFAULT 0 | Higher values checked first |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

**Indexes**: `idx_cat_rules_priority(priority DESC)`

```sql
-- List rules by priority
SELECT pattern, pattern_type, target_account, institution, priority
FROM categorization_rules ORDER BY priority DESC;
```

---

### balance_assertions

Records of balance verification checks.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Account checked |
| `date` | TEXT | NOT NULL | Date of assertion (YYYY-MM-DD) |
| `expected_amount` | TEXT | NOT NULL | Expected balance |
| `actual_amount` | TEXT | NOT NULL | Computed balance |
| `currency` | TEXT | NOT NULL | Currency |
| `matches` | INTEGER | NOT NULL | 1 if match, 0 if mismatch |
| `difference` | TEXT | | Amount of difference |
| `asserted_at` | TEXT | NOT NULL | ISO 8601 timestamp |

---

### column_mappings

Saved mappings for parsing institution-specific CSV/XLSX formats.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `name` | TEXT | NOT NULL, UNIQUE | Mapping name, e.g. `chase_checking` |
| `institution` | TEXT | | Financial institution |
| `mapping` | TEXT | NOT NULL | JSON mapping configuration (see below) |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

**Mapping JSON structure**:
```json
{
  "date_col": "Posting Date",
  "date_format": "%m/%d/%Y",
  "payee_col": "Description",
  "amount_col": "Amount",
  "amount_sign": "negative_is_debit",
  "balance_col": "Balance",
  "default_currency": "USD",
  "header_row": 0,
  "skip_footer_rows": 0
}
```

`amount_sign` options: `"negative_is_debit"` (Chase-style), `"positive_is_debit"` (some Indian banks), `"separate_columns"` (requires `debit_col` and `credit_col`).

---

### currency_tolerances

Currency-specific tolerances for double-entry validation.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `currency` | TEXT | PRIMARY KEY | Currency code |
| `tolerance` | TEXT | NOT NULL | Tolerance as decimal text |

Seeded on init: `0.01` for USD, INR, EUR; `0.00000001` for BTC. New currencies can be added dynamically.

```sql
SELECT * FROM currency_tolerances;
-- USD | 0.01
-- INR | 0.01
-- BTC | 0.00000001
```

---

### recurring_transactions

Templates for recurring transactions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `frequency` | TEXT | NOT NULL | daily, weekly, monthly, quarterly, yearly |
| `next_date` | TEXT | NOT NULL | Next scheduled date (YYYY-MM-DD) |
| `payee` | TEXT | | Payee name |
| `narration` | TEXT | | Description |
| `template_postings` | TEXT | NOT NULL | JSON array of posting templates |
| `active` | INTEGER | DEFAULT 1 | 1 if active, 0 if paused |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

---

### budgets

Monthly or annual budget amounts by account.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Expense/income account |
| `year_month` | TEXT | NOT NULL | "2025-03" (monthly) or "2025" (annual) |
| `amount` | TEXT | NOT NULL | Budget amount |
| `currency` | TEXT | NOT NULL | Currency |

**Primary key**: `(account_id, year_month, currency)` (WITHOUT ROWID table)

```sql
-- Budget vs actual
SELECT b.year_month, a.name, b.amount AS budget, s.total AS actual
FROM budgets b
JOIN accounts a ON a.id = b.account_id
LEFT JOIN s_monthly_spending s ON s.account_id = b.account_id AND s.year_month = b.year_month
WHERE b.year_month = '2025-01';
```

---

### schema_version

Tracks database migrations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `version` | INTEGER | PRIMARY KEY | Schema version number |
| `applied_at` | TEXT | NOT NULL | ISO 8601 timestamp |
| `description` | TEXT | | Migration description |

---

## Summary Tables

All summary tables use the `s_` prefix. They are derived from core tables, updated atomically on every write, and fully rebuildable via `finkit rebuild`.

### s_daily_balances

Running balance per account per day (sparse --- only days with transactions).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Account |
| `date` | TEXT | NOT NULL | Date (YYYY-MM-DD) |
| `balance` | TEXT | NOT NULL | Closing balance for this date |
| `currency` | TEXT | NOT NULL | Currency |
| `transaction_count` | INTEGER | | Number of transactions on this date |

**Primary key**: `(account_id, date, currency)`

```sql
-- Current balance for an account
SELECT balance FROM s_daily_balances
WHERE account_id = 1 ORDER BY date DESC LIMIT 1;

-- Balance history
SELECT date, balance FROM s_daily_balances
WHERE account_id = 1 ORDER BY date;
```

---

### s_monthly_spending

Spending and income totals by expense/income account per month. Keyed by the expense/income account, NOT the source bank account.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Expense or income account |
| `year_month` | TEXT | NOT NULL | Month (YYYY-MM) |
| `total` | TEXT | NOT NULL | Total amount |
| `currency` | TEXT | NOT NULL | Currency |
| `transaction_count` | INTEGER | | Number of transactions |

**Primary key**: `(account_id, year_month, currency)`

```sql
-- Grocery spending over time
SELECT s.year_month, s.total, s.transaction_count
FROM s_monthly_spending s
JOIN accounts a ON a.id = s.account_id
WHERE a.name = 'Expenses:Groceries'
ORDER BY s.year_month DESC;

-- Top spending categories this month
SELECT a.name, s.total
FROM s_monthly_spending s
JOIN accounts a ON a.id = s.account_id
WHERE a.type = 'Expenses' AND s.year_month = '2025-01'
ORDER BY CAST(s.total AS REAL) DESC;
```

---

### s_portfolio_holdings

Current investment positions with market value and unrealized gains.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Investment account |
| `commodity` | TEXT | NOT NULL | Ticker/symbol |
| `total_quantity` | TEXT | NOT NULL | Total shares/units held |
| `total_cost_basis` | TEXT | NOT NULL | Total cost basis |
| `cost_currency` | TEXT | NOT NULL | Currency of cost basis |
| `latest_price` | TEXT | | Most recent market price |
| `latest_price_date` | TEXT | | Date of the latest price |
| `market_value` | TEXT | | Current market value |
| `unrealized_gain` | TEXT | | Market value minus cost basis |
| `asset_class` | TEXT | | From account's asset_class setting |

**Primary key**: `(account_id, commodity)`

```sql
-- Portfolio summary
SELECT a.name, h.commodity, h.total_quantity, h.total_cost_basis,
       h.market_value, h.unrealized_gain
FROM s_portfolio_holdings h
JOIN accounts a ON a.id = h.account_id;
```

---

### s_account_monthly_balances

Closing balance per account per month.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `account_id` | INTEGER | NOT NULL, FK -> accounts | Account |
| `year_month` | TEXT | NOT NULL | Month (YYYY-MM) |
| `closing_balance` | TEXT | NOT NULL | Month-end balance |
| `currency` | TEXT | NOT NULL | Currency |

**Primary key**: `(account_id, year_month, currency)`

```sql
-- Monthly balance trend
SELECT year_month, closing_balance
FROM s_account_monthly_balances
WHERE account_id = 1
ORDER BY year_month;
```

---

### s_net_worth

Monthly net worth per currency and consolidated.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `year_month` | TEXT | NOT NULL | Month (YYYY-MM) |
| `currency` | TEXT | NOT NULL | USD, INR, or CONSOLIDATED |
| `total_assets` | TEXT | NOT NULL | Sum of all asset accounts |
| `total_liabilities` | TEXT | NOT NULL | Sum of all liability accounts |
| `net_worth` | TEXT | NOT NULL | Assets minus liabilities |
| `assets_cash` | TEXT | | Cash and bank account total |
| `assets_equity` | TEXT | | Equity investments total |
| `assets_debt` | TEXT | | Debt instruments total |
| `assets_crypto` | TEXT | | Cryptocurrency total |
| `assets_other` | TEXT | | Other assets total |
| `exchange_rate_to_base` | TEXT | | Exchange rate used for consolidation |

**Primary key**: `(year_month, currency)`

```sql
-- Net worth trend (consolidated)
SELECT year_month, net_worth, assets_equity, assets_cash
FROM s_net_worth
WHERE currency = 'CONSOLIDATED'
ORDER BY year_month;

-- Net worth by currency
SELECT year_month, currency, net_worth
FROM s_net_worth
WHERE year_month = '2025-01';
```

---

### s_yearly_capital_gains

Realized capital gains by year, holding period term, and currency.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `year` | INTEGER | NOT NULL | Tax year |
| `term` | TEXT | NOT NULL | "short" or "long" |
| `currency` | TEXT | NOT NULL | Currency of gains |
| `total_proceeds` | TEXT | NOT NULL | Total sale proceeds |
| `total_cost_basis` | TEXT | NOT NULL | Total cost basis of sold lots |
| `total_gain_loss` | TEXT | NOT NULL | Net gain or loss |
| `disposition_count` | INTEGER | | Number of lot dispositions |

**Primary key**: `(year, term, currency)`

```sql
-- Capital gains summary for 2024
SELECT term, currency, total_gain_loss, disposition_count
FROM s_yearly_capital_gains
WHERE year = 2024;

-- Multi-year trend
SELECT year, SUM(CAST(total_gain_loss AS REAL)) AS total
FROM s_yearly_capital_gains
WHERE currency = 'USD'
GROUP BY year ORDER BY year;
```

---

## payee_normalization_rules

Rules for normalizing raw bank payees to canonical names.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | |
| `pattern` | TEXT | NOT NULL | Pattern to match in raw payee |
| `pattern_type` | TEXT | DEFAULT 'substring' | Match type: substring, regex, exact |
| `canonical_name` | TEXT | NOT NULL | Clean canonical name |
| `priority` | INTEGER | DEFAULT 0 | Higher = checked first |
| `created_at` | TEXT | NOT NULL | ISO timestamp |

```sql
-- List all normalization rules
SELECT * FROM payee_normalization_rules ORDER BY priority DESC;

-- Find rules matching a payee
SELECT * FROM payee_normalization_rules
WHERE 'ACH Deposit META 4100' LIKE '%' || pattern || '%';
```

## document_templates

Templates for automated document extraction (learn once, apply forever).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | |
| `name` | TEXT | NOT NULL UNIQUE | Template identifier |
| `institution` | TEXT | | Financial institution |
| `document_type` | TEXT | NOT NULL | payslip, bank_statement, cc_statement, etc. |
| `match_keywords` | TEXT | NOT NULL | JSON array of identification keywords |
| `template_json` | TEXT | NOT NULL | JSON extraction patterns (mode, fields/sections) |
| `account_mapping` | TEXT | | JSON field-to-account mapping |
| `created_at` | TEXT | NOT NULL | ISO timestamp |
| `last_used_at` | TEXT | | Last template application timestamp |
| `use_count` | INTEGER | DEFAULT 0 | Number of times applied |

```sql
-- List templates by usage
SELECT name, institution, document_type, use_count
FROM document_templates ORDER BY use_count DESC;
```
