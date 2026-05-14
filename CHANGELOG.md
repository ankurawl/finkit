# Changelog

All notable changes to FinKit are documented here.

## [Unreleased]

### Added
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
