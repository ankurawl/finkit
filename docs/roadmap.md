# FinKit Roadmap

Living document tracking what's built, what's rough, and what could come next.

---

## Completed Features

### Core Engine

- **Double-entry validation** with currency-aware tolerance (0.01 fiat, 0.00000001 crypto). Tolerances stored in `currency_tolerances` table and looked up dynamically, so new currencies need zero code changes.
- **Price-weighted balancing** for multi-currency postings. When a posting has a `price` field, its weight is `amount * price` in `price_currency`. Handles cross-currency transfers and investment trades.
- **Lot tracking** with FIFO, LIFO, and HIFO selection methods. Per-lot cost basis with `quantity` (mutable) and `original_quantity` (immutable) fields for idempotent rebuild.
- **Lot disposition** with automatic gain/loss calculation, holding period classification (short-term vs long-term) based on jurisdiction and asset class, and wash sale detection within a +-30 calendar day window around losses.
- **Lot transfer** between accounts with partial-lot splitting.
- **Corporate actions** -- stock splits, reverse splits, and bonus shares adjust all affected lots (quantity and cost basis) automatically.
- **Price engine** -- store, retrieve, and convert prices. Supports direct lookup, inverse lookup, and cross-currency conversion. Prices are auto-recorded from transaction postings that have a `price` field.
- **Balance computation** -- per-account, per-currency, with optional as-of date. Subtree aggregation (e.g., all `Assets:*`) is supported.
- **Balance assertions** -- verify an account balance matches expectations on a given date. Results are persisted in the `balance_assertions` table.
- **Fuzzy account matching** via `matching.py` -- resolves partial or ambiguous account names.

### Import Pipeline

- **CSV import** with auto-detected delimiters and configurable column mappings (date, payee, narration, amount, split debit/credit columns). Handles multiple date formats.
- **XLSX import** via openpyxl and **XLS import** via xlrd, with configurable header row and footer skip.
- **PDF import** -- extracts text via pdfplumber, then parses with institution-specific regex parsers. Falls back to table extraction for unknown institutions.
- **8 institution PDF parsers**: Marcus (Goldman Sachs), Alliant Credit Union, First Tech Federal, Frost Bank, Chase credit cards, Capital One credit cards, Citi credit cards, and Fidelity (contributions, distributions, dividends, and holdings).
- **Auto-detection of institution** from PDF text content using keyword matching.
- **SHA-256 file dedup** -- re-importing the same file is a no-op. Original files are always copied, never moved or deleted.
- **Raw extraction preservation** -- every imported row is stored as a JSON blob in `raw_extractions` with all original fields intact.
- **Statement archive** organized by year under `statements/{year}/`. Collision handling appends a hash suffix.
- **Transaction dedup** within a configurable window (default 3 days) using amount + normalized payee matching.
- **Directory import** with glob patterns and recursive search.
- **Saved column mappings** -- persist and reuse column mapping configurations per institution.
- **Auto-categorization on import** -- categorization rules are applied to imported transactions before they're committed.

### Summary Layer

- **6 summary tables**, all with `s_` prefix:
  - `s_daily_balances` -- per-account daily balance snapshots
  - `s_monthly_spending` -- per-expense/income-account monthly totals (keyed by the expense account, not the bank account)
  - `s_portfolio_holdings` -- per-account per-commodity position with cost basis, latest price, market value, and unrealized gain
  - `s_account_monthly_balances` -- per-account monthly closing balances
  - `s_net_worth` -- monthly net worth with asset class breakdown (cash, equity, debt, crypto, other)
  - `s_yearly_capital_gains` -- annual capital gains by term (short/long) and currency
- **Atomic refresh** -- every write operation refreshes summaries within the same `db.transaction()`. If refresh fails, everything rolls back.
- **Idempotent rebuild** -- `finkit rebuild` drops and recreates all summary tables from core data. Lots are reset to `original_quantity` and dispositions replayed chronologically.
- **RefreshContext** scoping -- incremental refresh uses affected account IDs, date range, and commodities to limit recomputation.

### Analysis

- **Spending analysis** -- per-category spending with month-over-month trends, configurable lookback period, and currency filtering.
- **Portfolio analysis** -- current holdings, allocation percentages, and unrealized gains using latest market prices.
- **Capital gains reporting** -- realized gains/losses by tax year, broken out by short-term and long-term.
- **What-if sell simulation** -- preview capital gains impact of selling a position with a chosen booking method and assumed price.
- **Export** -- transactions, balances, or custom SQL results as CSV or JSON, to a file or inline.

### Categorization

- **Rule-based categorization** with three pattern types: substring (case-insensitive), regex, and exact match.
- **Priority ordering** -- higher-priority rules match first.
- **Institution scoping** -- rules can be limited to a specific institution or apply globally.
- **CRUD operations** -- add, remove, and list rules via MCP tool or CLI.
- **LLM-assisted categorization** -- optional Ollama integration sends transaction descriptions to a local model for classification against existing accounts. Disabled by default.

### MCP Server

- **20 tools** exposed via FastMCP: init_ledger, open_account, submit_transaction, amend_transaction, assert_balance, query, get_balances, get_transactions, import_file, import_pdf, import_directory, fetch_prices, analyze_spending, analyze_portfolio, report_capital_gains, what_if_sell, export, categorize, corporate_action, undo_import.
- **5 additional tools** for document ingestion and tax workflows: ingest_document, submit_transactions, setup_payroll_accounts, reconcile_tax_document, tax_readiness_report.
- **14 additional tools** for data quality and template engine: recategorize_posting, batch_recategorize, payee_rules, normalize_existing_payees, find_duplicates, merge_duplicates, detect_transfers, link_transfer, import_report, learn_template, save_document_template, apply_template, list_templates, delete_template.
- **39 tools total** exposed via FastMCP.
- **Auto-config** via `.mcp.json` at the project root -- MCP-compatible clients pick up the server automatically.
- **Read-only query safety** -- the `query` tool enforces `PRAGMA query_only = ON` before executing user SQL.

### Document Ingestion and Financial Planning

- **LLM-powered document ingestion** -- `ingest_document` archives any financial document (PDF, CSV, XLSX), extracts content via pdfplumber or CSV parsing, classifies the document type using keyword matching against 15 types (payslip, tax forms, receipts, invoices, etc.), and returns extracted text with type-specific hints for LLM interpretation.
- **Batch transaction submission** -- `submit_transactions` commits multiple transactions atomically with a shared `source_file_id`. Single database transaction and summary refresh. Supports `undo_import` for the entire batch.
- **Document provenance** -- `submit_transaction` now accepts optional `source_file_id` to link manually-created transactions to source documents, enabling `undo_import`.
- **Payslip decomposition** -- `setup_payroll_accounts` creates the standard payroll account hierarchy per employer (US and India jurisdictions). Payslips decompose into multi-posting transactions: gross pay, federal/state taxes, FICA, benefits, retirement contributions, net pay.
- **Tax document reconciliation** -- `reconcile_tax_document` compares W-2, 1099-INT, 1099-DIV, 1099-B, and Form 16 data against recorded transactions. Returns field-by-field comparisons with match/mismatch/missing status and suggested transactions for missing income.
- **Tax readiness report** -- `tax_readiness_report` generates a comprehensive gap analysis for a tax year: income totals, taxes paid, capital gains, deductible expenses, and missing pay period detection.

### Data Quality Utilities

- **Posting-level amend** -- `recategorize_posting` changes one posting's account without rebuilding all postings. Supports disambiguation by posting ID for transactions with duplicate accounts.
- **Batch recategorize** -- `batch_recategorize` recategorizes all transactions matching a payee pattern in a single operation. Supports substring, regex, and exact match patterns.
- **Payee normalizer** -- `payee_rules` manages normalization rules that map raw bank payees (e.g., "ACH Deposit ACME 9876543210") to canonical names (e.g., "Acme"). `normalize_existing_payees` applies rules retroactively. Normalized names are stored in `normalized_payee` column, preserving the raw payee.
- **Cross-source duplicate detector** -- `find_duplicates` detects potential duplicates across different source files using amount/date matching with configurable tolerances. `merge_duplicates` keeps one transaction and deletes the other, with optional metadata enrichment.
- **Transfer detector and linker** -- `detect_transfers` finds inter-account transfers that appear as two separate transactions (one outgoing with Uncategorized, one incoming with Uncategorized). `link_transfer` merges them into a single A-to-B transaction.
- **Import reconciliation report** -- `import_report` generates a post-import health report: uncategorized transactions, potential duplicates, balance anomalies (negative assets, positive liabilities), missing periods, and orphaned source files.
- **Document template engine** -- learn-once-apply-forever document import. `learn_template` extracts text from a sample document for LLM-assisted pattern generation. `save_document_template` stores regex patterns and field-to-account mappings. `apply_template` auto-matches documents to templates and extracts transactions without LLM involvement. Supports table-mode (bank/CC statements) and field-mode (payslips, tax forms) extraction with confidence scoring.
- **Schema migration** -- `ensure_schema_v2()` migrates existing databases to add `payee_normalization_rules`, `document_templates` tables, and `normalized_payee` column. Called automatically on connection.

### CLI

- **37 subcommands** mirroring all MCP tools plus extras: `accounts`, `manual-price`, `rebuild`, `backup`.
- **Consistent interface** -- all commands accept `--data-dir` to override the default data directory. JSON output to stdout.
- **Categorize sub-subcommands** -- `categorize add`, `categorize remove`, `categorize list`.

### Market Data

- **Stock/ETF prices** via yfinance -- fetches `regularMarketPrice` or `previousClose`, falls back to historical data.
- **Crypto prices** via CoinGecko API -- supports API key authentication, batch fetching by coin ID.
- **Forex rates** via ExchangeRate-API -- groups pairs by base currency to minimize API calls.
- **Manual price entry** for unlisted or private assets.
- **Summary refresh** after price fetch -- portfolio holdings and net worth are updated atomically.

### Infrastructure

- **SQLite with WAL mode** and foreign key enforcement on every connection.
- **Schema versioning** via `schema_version` table.
- **Database backup** using SQLite's built-in backup API.
- **Configuration** via `finkit.toml` with sensible defaults. Environment variables for API keys via `.env`.
- **Configurable holding periods** per jurisdiction and asset class (US equity 365 days, India debt 1095 days, etc.).

### Testing

- **20 test files** covering: database operations, validation, balances, lots, prices, summaries, importers, PDF parsers, operations, queries, analysis, categorization, integration, payee normalization, batch recategorization, duplicates, transfers, import reports, and template engine.

---

## Known Limitations

- **PDF parsers cover 8 US institutions only.** Other banks and brokerages produce no parsed transactions -- they fall through to an empty result. Adding a new institution requires writing a regex parser in `pdf_parsers.py`.
- **Transactions are uncategorized by default.** Imported transactions land as `Expenses:Uncategorized` or `Income:Uncategorized` until categorization rules are added manually. There is no built-in rule set.
- **No automatic recurring transaction generation.** The `recurring_transactions` table exists in the schema but there is no code to read it, generate due transactions, or manage schedules.
- **Budgets table exists but has no UI.** The `budgets` table is in the schema (keyed by account + month + currency) but no MCP tool, CLI command, or analysis module uses it.
- **Fidelity holdings import is extraction-only.** `parse_fidelity_holdings` extracts holdings data from PDFs but does not create opening balance transactions or lot positions from it. Useful for reference but not wired into the import pipeline.
- **Frost Bank parser is a stub.** `parse_frost` returns an empty list -- registered for institution detection but does not extract transactions.
- **Transaction dedup uses float comparison.** The dedup query in `file_importer.py` uses `CAST(p.amount AS REAL)` for amount matching, which could miss edge cases with amounts that have many decimal places. The rest of the codebase correctly uses Decimal.
- **No OFX/QFX support.** The archive module recognizes `.ofx` and `.qfx` extensions for file type detection, but there is no parser for these formats.
- **Column mapping must be pre-configured.** If no mapping is provided and the file is not a recognized PDF, raw rows are stored but no transactions are created. The user gets back `needs_mapping: true` and must re-import with a mapping.
- **Single-user only.** All data lives in one directory with one database file. No multi-user isolation or access control.

---

## Future Ideas

### Import and Parsing

- More PDF institution parsers: Schwab, Vanguard, Amex, Bank of America, Wells Fargo, Discover [small each]
- OFX/QFX import support -- standard format used by most US banks for download [medium]
- India bank PDF parsers: HDFC, SBI, ICICI, Axis [small each]
- India brokerage import: Zerodha contract notes, Groww, Kite CSV [medium]
- Auto-detect column mappings from CSV headers using heuristics [medium]
- Interactive mapping builder -- prompt user to assign columns when headers don't match [medium]
- Direct bank feeds via Plaid (US) and Account Aggregator (India) for fully automated transaction import [large]
- OCR for scanned documents and photos (receipts, paper pay stubs) via Tesseract or cloud OCR [medium]

### Categorization

- Ship a default rule set covering common US merchants (Amazon, Walmart, Uber, etc.) [small]
- Interactive categorization review -- show uncategorized transactions and let the user assign categories in bulk [medium]
- Learn from user corrections -- auto-generate rules from manually categorized transactions [medium]
- Multi-account categorization -- split a single transaction across multiple expense categories [medium]

### Budgeting

- Budget CRUD via MCP tool and CLI (create, update, delete monthly budgets per account) [small]
- Budget vs. actual comparison in spending analysis [small]
- Budget alerts -- flag categories that exceed their budget [small]
- Rollover budgets -- carry unused budget forward to the next month [small]

### Recurring Transactions

- Implement recurring transaction generation from the existing `recurring_transactions` table [medium]
- Recurrence patterns: monthly, biweekly, weekly, quarterly, annual [small]
- Auto-submit due transactions on `finkit init` or a dedicated `finkit generate-recurring` command [small]

### Analysis and Reporting

- Cash flow analysis -- income vs. expenses over time with net savings rate [small]
- Year-over-year spending comparison [small]
- Tax-loss harvesting suggestions -- identify positions with unrealized losses [medium]
- Dividend income tracking and reporting [medium]
- Custom report builder via SQL templates [medium]

### Data Quality

- Fix the float comparison in transaction dedup to use Decimal/TEXT comparison [small]
- Wire Fidelity holdings import into the opening balance workflow [medium]
- Implement the Frost Bank parser (or remove the stub) [small]

### Multi-Currency and International

- India-specific tax reporting (Section 112A, Section 111A for equity gains) [medium]
- ELSS lock-in period enforcement using the existing `lock_until` field on lots [small]
- Multi-currency net worth consolidation with configurable base currency (partially done via `s_net_worth.exchange_rate_to_base`) [medium]

### User Experience

- Web UI / dashboard for browsing transactions, balances, and charts [large]
- TUI (terminal UI) for interactive transaction entry and review [medium]
- Multi-user support with separate data directories and profiles [medium]
- Encrypted database or at-rest encryption for the SQLite file [medium]
- Notifications/alerts for large transactions, low balances, or budget overruns [medium]

### Integration

- Plaid integration for automatic bank statement download [large]
- Beancount/hledger export for interoperability with other plain-text accounting tools [medium]
- Google Sheets sync for shared family finance tracking [medium]

---

*Last updated: 2026-05-14*
