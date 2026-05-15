# FinKit Architecture

Living architecture document for FinKit. For schema details see [schema_reference.md](schema_reference.md), for tool parameters see [tools_reference.md](tools_reference.md).

---

## Design Philosophy

**Privacy-first.** All data stays on the user's machine. The database, archived statements, and backups live under a single data directory (default `~/finance`). No cloud accounts, no telemetry. The only network calls are market price fetches, which send ticker symbols only.

**SQLite-canonical.** One file (`finkit.db`) holds the entire ledger. No database server, no migrations framework. WAL mode enables concurrent reads. The SQLite backup API handles backups.

**Double-entry accounting.** Every transaction's postings must sum to zero within currency-aware tolerance. Multi-currency postings balance via price-weighted amounts. A transaction that doesn't balance is rejected at the boundary --- never silently accepted.

**Deterministic computation.** Summary tables are derived from core tables through pure functions. Any summary can be rebuilt from scratch at any time, producing identical results. Write operations update summaries atomically within the same database transaction.

---

## System Architecture

```
                    +-----------+
                    |   User    |
                    +-----+-----+
                          |
                +---------+---------+
                |                   |
          +-----v-----+     +------v------+
          |    CLI     |     |  LLM Client |
          | (cli.py)   |     | (any MCP)   |
          +-----+------+     +------+------+
                |                   |
                +--------+----------+
                         |
                 +-------v--------+
                 |   MCP Server   |
                 | (mcp/server.py)|
                 |   39 tools     |
                 +-------+--------+
                         |
          +--------------+----------------+
          |              |                |
   +------v------+ +----v-----+ +--------v--------+
   | operations.py| |queries.py| | analysis/*.py   |
   | (writes)     | | (reads)  | | (read-only)     |
   +------+------+ +----+-----+ +--------+--------+
          |              |                |
   +------v--------------v----------------v------+
   |              engine/                         |
   | validation | lots | balances | prices        |
   +------+-----------------------------------+--+
          |                                   |
   +------v---------+              +---------v--------+
   | summaries/      |              | importers/       |
   | registry.py     |              | file_importer.py |
   | daily_balances   |              | pdf_parsers.py   |
   | monthly_spending |              | archive.py       |
   | portfolio_holdings|             +------------------+
   | net_worth        |
   | capital_gains    |
   +------+-----------+
          |
   +------v------+
   |   SQLite    |  +  ~/finance/statements/
   | (finkit.db) |     (archived files)
   +-------------+
```

The CLI and MCP server both call the same backing functions in `operations.py`, `queries.py`, and `analysis/`. There is no separate business logic layer --- the MCP tool handlers are thin wrappers.

---

## Data Flow

### Import Pipeline (CSV/XLSX)

```
file_path
  |
  v
archive_file()           -- copy to statements/{year}/, SHA-256 dedup
  |                         (duplicate file -> immediate no-op return)
  v
extract_rows()           -- parse CSV/XLSX into list[dict]
  |
  v
raw_extractions          -- every row saved as JSON blob (nothing discarded)
  |
  v
apply_mapping()          -- column mapping transforms raw rows to Transaction objects
  |                         (date parsing, amount normalization, counter-postings)
  v
categorize_transactions()-- rule-based pattern matching assigns expense/income accounts
  |
  v
dedup_transactions()     -- amount + date window + normalized payee check
  |
  v
save transactions        -- INSERT into transactions + postings tables
  |
  v
registry.refresh_all()   -- update all summary tables within the same transaction
```

### Import Pipeline (PDF)

```
file_path
  |
  v
archive_file()           -- same SHA-256 dedup as CSV
  |
  v
extract_pdf()            -- pdfplumber extracts raw text
  |
  v
detect_institution()     -- keyword matching against known institutions
  |
  v
parse_<institution>()    -- institution-specific regex parser
  |                         returns list[dict] with date, payee, narration, amount
  v
(joins CSV pipeline at raw_extractions step)
```

### Write Operations

Every write operation follows the same pattern:

```python
with db.transaction():
    # 1. Write to core tables (transactions, postings, lots, prices, etc.)
    # 2. Build RefreshContext with affected accounts, date range, commodities
    # 3. SummaryRegistry.refresh_all(db, context)
    # If anything fails, the entire transaction rolls back
```

Write operations: `submit_transaction`, `submit_transactions`, `amend_transaction`, `import_file`, `undo_import`, `corporate_action`, `fetch_prices`, `recategorize_posting`, `batch_recategorize`, `merge_duplicates`, `link_transfer`.

---

## Core vs Summary Tables

### Core Tables (source of truth)

| Table | Purpose |
|-------|---------|
| `accounts` | Chart of accounts with colon-separated hierarchy |
| `transactions` | Transaction headers (date, payee, narration, status) |
| `postings` | Individual legs of transactions (account, amount, currency, price) |
| `lots` | Per-lot cost basis for investment positions |
| `lot_dispositions` | Records of lot sales with gain/loss and holding period |
| `prices` | Historical prices for commodities/currencies |
| `source_files` | Imported file metadata and SHA-256 hashes |
| `raw_extractions` | Verbatim row data from imported files as JSON |
| `categorization_rules` | Pattern-matching rules for auto-categorization |
| `column_mappings` | Institution-specific column mappings for CSV/XLSX import |
| `balance_assertions` | Balance verification records |
| `currency_tolerances` | Per-currency precision for balancing (0.01 for fiat, 0.00000001 for BTC) |
| `budgets` | Monthly budget amounts per account |
| `recurring_transactions` | Templates for recurring entries |
| `transaction_tags` | Tag associations for transactions |
| `schema_version` | Schema migration tracking |

### Summary Tables (derived, rebuildable)

| Table | Keyed By | Purpose |
|-------|----------|---------|
| `s_daily_balances` | account + date + currency | Running balance per account per day |
| `s_monthly_spending` | account + month + currency | Monthly totals keyed by expense/income account (not bank account) |
| `s_portfolio_holdings` | account + commodity | Current holdings with cost basis and market value |
| `s_account_monthly_balances` | account + month + currency | End-of-month closing balance per account |
| `s_net_worth` | month + currency | Consolidated net worth with asset class breakdown |
| `s_yearly_capital_gains` | year + term + currency | Annual realized gains by short/long term |

**Summary invariants:**
- Rebuilt via `finkit rebuild` --- idempotent, produces identical results every time.
- Updated atomically within the same database transaction as the core write.
- If summary refresh fails, the entire write operation rolls back. No partial state.

---

## Import Architecture

### CSV/XLSX: Column Mappings

Column mappings translate institution-specific column names to standard fields. Mappings are stored in the `column_mappings` table and can be reused across imports.

Standard fields: `date_col`, `payee_col`, `narration_col`, `amount_col`, `amount_sign`, `date_format`, `currency_col`, `debit_col`, `credit_col`, `header_row`, `skip_footer_rows`.

Amount sign modes:
- `negative_is_debit` --- negative values are debits (most common)
- `positive_is_debit` --- positive values are debits (some institutions)
- `separate_columns` --- separate debit and credit columns

### PDF: Institution Parsers

PDF import uses `pdfplumber` for text extraction, then institution-specific regex parsers in `importers/pdf_parsers.py`. Auto-detection matches keywords in the extracted text against known institutions.

Supported institutions:

| Slug | Institution | Parser |
|------|------------|--------|
| `marcus` | Goldman Sachs / Marcus | `parse_marcus` |
| `alliant` | Alliant Credit Union | `parse_alliant` |
| `firsttech` | First Tech Federal Credit Union | `parse_firsttech` |
| `frost` | Frost Bank | `parse_frost` |
| `chase` | Chase Credit Cards | `parse_chase_cc` |
| `capitalone` | Capital One Credit Cards | `parse_capitalone_cc` |
| `citi` | Citi Credit Cards | `parse_citi_cc` |
| `fidelity` | Fidelity Investments | `parse_fidelity` |

Each parser returns `list[dict]` with keys: `date` (YYYY-MM-DD), `payee`, `narration`, `amount` (string).

### Dedup Strategy

Two layers of deduplication:
1. **File-level**: SHA-256 hash of file contents. Re-importing the same file is a no-op.
2. **Transaction-level**: Within a configurable window (default 3 days), transactions with the same amount and normalized payee against the same account are considered duplicates.

---

### LLM-Assisted Import Pipeline

For documents without a deterministic parser (payslips, tax returns, receipts, invoices, etc.), FinKit uses a two-phase import architecture:

```
file_path
  |
  v
ingest_document()              Phase 1: deterministic (FinKit)
  |  archive + extract + classify + return hints
  v
LLM interprets content         Phase 2: semantic (MCP client)
  |  reads text, understands document, builds transactions
  v
submit_transactions()          Batch commit with source_file_id linkage
  |
  v
undo_import()                  Reverses everything via source_file_id
```

**Phase 1 (FinKit):** `ingest_document` archives the file (SHA-256 dedup), extracts text via pdfplumber (for PDFs) or row parsing (for CSV/XLSX), classifies the document type using keyword matching against 15 document types, and returns the extracted content with type-specific hints.

**Phase 2 (LLM):** The calling LLM reads the extracted text, uses the hints to understand what fields to look for, and calls `submit_transactions` with properly structured double-entry postings. The `source_file_id` from Phase 1 links all created transactions back to the source document.

Document types detected: payslip, tax_w2, tax_1099, tax_form16, receipt, invoice, insurance_statement, loan_statement, mortgage_statement, bank_statement, credit_card_statement, brokerage_statement, utility_bill, property_tax, unknown.

### Payslip Decomposition

Payslips are decomposed into multi-posting double-entry transactions:

```
Income:Salary:Acme            -5000.00 USD   (gross pay)
Expenses:Taxes:Federal          750.00 USD   (federal withholding)
Expenses:Taxes:State            250.00 USD   (state tax)
Expenses:Taxes:SocialSecurity   310.00 USD   (Social Security)
Expenses:Taxes:Medicare          72.50 USD   (Medicare)
Expenses:Benefits:Health        200.00 USD   (health insurance)
Assets:Retirement:401k         500.00 USD   (401k contribution)
Assets:Chase:Checking         2917.50 USD   (net pay)
```

`setup_payroll_accounts` creates the standard account hierarchy per employer (US and India jurisdictions supported).

### Tax Document Reconciliation

Tax forms (W-2, 1099, Form 16) are reconciled against the ledger rather than imported as transactions:

- **W-2**: Compare wages, federal/state tax, SS/Medicare against `Income:Salary:*` and `Expenses:Taxes:*` totals
- **1099-INT/DIV**: Compare interest/dividend income. Generate suggested transactions for missing income
- **1099-B**: Compare capital gains against `s_yearly_capital_gains` summary
- **Form 16**: India equivalent --- compare gross salary and TDS

`tax_readiness_report` provides a comprehensive gap analysis for a tax year.

---

## Lot Tracking

### Cost Basis

Each investment purchase creates a `lots` row with `original_quantity`, `quantity` (mutable), `cost_price`, and `acquired_date`. The `quantity` field is decremented on sell; `original_quantity` is immutable.

### Disposition Selection

When selling, lots are selected by the account's `booking_method`:
- **FIFO** --- first in, first out (default)
- **LIFO** --- last in, first out
- **HIFO** --- highest cost first (tax-optimal for losses)

Each disposition records `quantity`, `proceeds_per_unit`, `gain_loss`, and `term` (short/long).

### Holding Period Classification

Term classification is jurisdiction and asset-class aware, configured in `finkit.toml`:

| Key | Days | Context |
|-----|------|---------|
| `US.equity` | 365 | US stocks, ETFs |
| `US.crypto` | 365 | US cryptocurrency |
| `IN.equity` | 365 | India equities |
| `IN.debt` | 1095 | India debt instruments (3 years) |
| `IN.elss` | 1095 | India ELSS mutual funds (3-year lock-in) |

### Wash Sale Detection

Applies to loss dispositions only. Checks for purchases of the same commodity within +/-30 calendar days of the sale. Flagged via `wash_sale` and `wash_sale_adjustment` on the disposition record.

### Corporate Actions

Stock splits (forward and reverse) and bonus shares adjust all undisposed lots for the affected commodity:
- `quantity` and `original_quantity` are multiplied by the ratio
- `cost_price` is divided by the ratio

### Rebuild

`finkit rebuild` for lots:
1. Reset every lot: `quantity = original_quantity`, `disposed = 0`
2. Replay all `lot_dispositions` chronologically
3. Result is identical to the state produced by incremental updates

---

## Configuration

### Sources (in priority order)

1. **`--data-dir` flag** --- CLI/MCP parameter, highest priority
2. **`FINKIT_DATA_DIR` env var** --- overrides config file and default
3. **`finkit.toml`** --- in the data directory
4. **Defaults** --- `~/finance`, USD, 365-day holding periods

### Data Directory Layout

```
~/finance/
├── finkit.db              # SQLite database
├── finkit.toml            # Configuration
├── .env                   # API keys (COINGECKO_API_KEY, EXCHANGERATE_API_KEY)
├── statements/            # Archived files, organized by year
│   ├── 2024/
│   └── 2025/
└── backups/               # SQLite backup API snapshots
```

### Settings Reference

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `general` | `data_dir` | `~/finance` | Database and archive location |
| `general` | `default_currency` | `USD` | Default currency for new accounts |
| `general` | `base_currency` | `USD` | Base currency for consolidated net worth |
| `holding_periods` | `<jurisdiction>.<asset_class>` | 365 | Days for long-term classification |
| `import` | `dedup_window_days` | 3 | Window for transaction-level dedup |
| `market` | `stock_source` | `yfinance` | Stock/ETF price provider |
| `market` | `crypto_source` | `coingecko` | Crypto price provider |
| `market` | `forex_source` | `exchangerate-api` | Forex rate provider |
| `ollama` | `enabled` | `false` | Enable LLM-assisted categorization |
| `ollama` | `model` | `qwen2.5:7b` | Ollama model for categorization |

---

## Key Design Decisions

**Amounts as TEXT in SQLite.** `float` introduces rounding errors in financial math. All amounts are `decimal.Decimal` in Python and `TEXT` in SQLite. The `Decimal(str(value))` pattern avoids float contamination when reading from JSON.

**8-char hex UUIDs.** Transaction UUIDs are `uuid4().hex[:8]` --- short enough to type or speak, sufficient entropy for a personal ledger.

**WAL mode.** Write-Ahead Logging enables concurrent readers without blocking on writes. Set on every connection via `PRAGMA journal_mode=WAL`.

**Original files never modified.** Import copies files to `statements/{year}/`. The user's original files are never moved, renamed, or deleted. `source_files.path` is relative to `statements/`; `source_files.original_path` is the absolute original location.

**Verbatim raw extraction.** Every imported row is preserved as a JSON blob in `raw_extractions` with all original fields. Nothing from the source file is discarded, even if the column mapping ignores certain fields.

**Price auto-recording.** When a posting includes a `price` field (e.g., buying stock at $150/share), that price is automatically written to the `prices` table. This builds a price history as a side effect of normal transaction entry.

**Foreign keys enforced.** `PRAGMA foreign_keys = ON` on every connection. Cascade deletes on postings and tags when a transaction is deleted.

**Read-only query boundary.** The ad-hoc `query` tool sets `PRAGMA query_only = ON` before executing user-provided SQL. This prevents accidental writes through the query interface.

## Document Template Engine

The template engine implements a "learn once, apply forever" pattern for document import:

1. **Learn phase**: `learn_template` extracts text from a sample document and returns it to the LLM. The LLM generates regex patterns and field-to-account mappings, which are saved via `save_document_template`.

2. **Apply phase**: `apply_template` auto-matches incoming documents to saved templates using keyword matching, extracts data via regex, builds transactions, and submits them through the standard import pipeline (archive → normalize → categorize → dedup → submit).

Templates support two modes:
- **Table mode** — for bank/CC statements with multiple transactions per document. Uses section delimiters and row patterns.
- **Field mode** — for payslips, tax forms, and single-transaction documents. Uses named field patterns with type validation.

Template matching ranks candidates by (1) number of matching keywords, then (2) use count. Confidence scoring tracks fields_extracted / fields_expected.

## Payee Normalization

Raw bank payees (e.g., "ACH Deposit ACME 9876543210 PP - DIRECT DEP") are normalized to canonical names (e.g., "Acme") using pattern-matching rules stored in `payee_normalization_rules`. The raw payee is preserved in the `payee` column; the canonical name is stored in `normalized_payee`. Downstream systems (categorization, duplicate detection, queries) prefer `normalized_payee` when available.
