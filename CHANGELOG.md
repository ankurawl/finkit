# Changelog

All notable changes to FinKit are documented here.

## [Unreleased]

### Added
- **Posting-level amend** — new `recategorize_posting` MCP tool and CLI command changes
  one posting's account without rebuilding all postings. Supports posting ID
  disambiguation and lot-tracked account guard.
- **Batch recategorize** — new `batch_recategorize` MCP tool and CLI command recategorizes
  all transactions matching a payee pattern (substring, regex, or exact) in one operation.
- **Payee normalizer** — new `payee_rules` and `normalize_existing_payees` MCP tools.
  Maps raw bank payees (e.g., "ACH Deposit ACME 9876543210") to canonical names
  (e.g., "Meta") via rule-based pattern matching. Stores normalized names in a new
  `normalized_payee` column, preserving the original payee. Categorization and queries
  prefer normalized names when available.
- **Cross-source duplicate detector** — new `find_duplicates` and `merge_duplicates`
  MCP tools detect and merge duplicate transactions across different source files
  using amount/date matching with configurable tolerances and confidence scoring.
- **Transfer detector and linker** — new `detect_transfers` and `link_transfer` MCP
  tools find inter-account transfers that appear as two separate transactions with
  Uncategorized contra postings and merge them into single A-to-B transactions.
- **Import reconciliation report** — new `import_report` MCP tool generates a post-import
  health report: uncategorized transactions, potential duplicates, balance anomalies,
  missing periods, and orphaned source files.
- **Document template engine** — learn-once-apply-forever document import. New MCP tools:
  `learn_template`, `save_document_template`, `apply_template`, `list_templates`,
  `delete_template`. Supports table-mode (bank/CC statements) and field-mode
  (payslips, tax forms) extraction with confidence scoring.
- **Schema v2 migration** — automatic migration adds `payee_normalization_rules` and
  `document_templates` tables plus `normalized_payee` column on transactions.
  Runs on connection via `ensure_schema_v2()`.
- **New DB tables** — `payee_normalization_rules` for payee normalization rules and
  `document_templates` for reusable extraction templates.
- **New dataclasses** — `PayeeNormalizationRule` and `DocumentTemplate` in `models.py`.
- **13 new CLI commands** — `recategorize-posting`, `batch-recategorize`, `payee-rules`,
  `normalize-payees`, `find-duplicates`, `merge-duplicates`, `detect-transfers`,
  `link-transfer`, `import-report`, `learn-template`, `apply-template`,
  `list-templates`, `delete-template`.
- **6 new test files** with 49 new tests (334 total): `test_batch_recategorize.py`,
  `test_payee_normalizer.py`, `test_duplicates.py`, `test_transfers.py`,
  `test_import_report.py`, `test_template_engine.py`.
- **Shared test fixture** — `create_multi_source_setup()` in `conftest.py` for
  cross-source tests.
- **LLM-powered document ingestion** — new `ingest_document` MCP tool archives any
  financial document, extracts content, classifies document type (15 types including
  payslip, tax forms, receipts), and returns structured hints for LLM interpretation.
- **Batch transaction submission** — new `submit_transactions` MCP tool commits
  multiple transactions atomically with shared source file linkage.
- **Document provenance** — `submit_transaction` now accepts `source_file_id` to
  link transactions to source documents, enabling bulk undo via `undo_import`.
- **Payslip decomposition** — new `setup_payroll_accounts` MCP tool creates the
  standard payroll account hierarchy (US and India). Payslips decompose into
  balanced multi-posting transactions covering gross pay, taxes, benefits, and net pay.
- **Tax document reconciliation** — new `reconcile_tax_document` MCP tool compares
  W-2, 1099-INT/DIV/B, and Form 16 data against the ledger. Returns field-by-field
  comparisons and suggested transactions for missing income.
- **Tax readiness report** — new `tax_readiness_report` MCP tool generates a
  comprehensive gap analysis for any tax year.
- **Document type classifier** (`src/finkit/importers/document_classifier.py`) —
  keyword-based classification of 15 financial document types with extraction hints.
- **PDF statement import** — `import_file` now accepts PDF files alongside CSV/XLSX.
  Institution-specific text parsers extract transactions from PDF statements
  using pdfplumber for text extraction and regex-based parsing.
- **PDF parser module** (`src/finkit/importers/pdf_parsers.py`) with parsers for
  8 institutions: Marcus (Goldman Sachs), Alliant Credit Union, FirstTech Federal,
  Frost Bank, Chase (credit cards), Capital One (credit cards), Citi (credit cards),
  and Fidelity (investment accounts).
- **PDF auto-detection** — institution is identified automatically from PDF text
  content via keyword matching. Can be overridden with `--institution` flag.
- **Fidelity holdings parser** — `parse_fidelity_holdings()` extracts investment
  positions (ticker, quantity, price, cost basis, gain/loss) from Fidelity statements.
- **`FINKIT_DATA_DIR` environment variable** — overrides the default `~/finance`
  data directory. Supported in `config.py` via `load_settings()`. Set in `.env`
  for local configuration.
- **MCP server auto-configuration** — `.mcp.json` at project root configures the
  finkit MCP server for Claude Code. `.claude/settings.json` enables it with
  `enableAllProjectMcpServers: true`.
- **`CLAUDE.md` in repo root** — agent-facing documentation with MCP tool table,
  project structure, invariants, and patterns for adding new features.
- **PDF parser tests** (`tests/test_pdf_parsers.py`) — 30 tests covering all
  institution parsers, auto-detection, and edge cases.
- **Architecture doc** (`docs/architecture.md`) — living design document covering
  system architecture, data flow, and key design decisions.
- **Roadmap doc** (`docs/roadmap.md`) — completed features, known limitations,
  and future ideas.

### Changed
- **Dedup improvement** — transaction dedup now normalizes whitespace in payee
  strings before comparison (collapses multiple spaces to single space). Also
  compares amounts numerically (`CAST AS REAL`) instead of exact string match,
  so `"2621.01000"` matches `"2621.01"`.
- **MCP server parameter names** — fixed `account` → `account_name` mismatch in
  6 MCP tools (`get_balances`, `get_transactions`, `assert_balance`, `import_file`,
  `what_if_sell`, `import_directory`) to match backing function signatures.
- **MCP `query` tool** — removed `params` parameter (union type `list | dict | None`
  was not serializable for MCP JSON schema).
- **MCP `import_file` docstring** — updated to mention PDF support.
- **MCP `import_pdf` docstring** — clarified as extraction-only; use `import_file`
  for full import pipeline.

### Fixed
- **`.gitignore`** — added `.claude/settings.local.json` and `.claude/internet-mode-*`
  to prevent committing user-specific Claude Code state.
- **`CONTRIBUTING.md`** — removed stale reference to `plan2.md`.
