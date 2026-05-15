# FinKit

Privacy-first personal finance toolkit. SQLite + double-entry accounting +
MCP tools. See `README.md` for features and installation.

## Use MCP tools, not CLI

The MCP server is auto-configured via `.mcp.json`. Prefer MCP tools over
running CLI commands via Bash. See `docs/tools_reference.md` for all 39 tools.

## Documentation map

| Doc | What's in it |
|-----|-------------|
| `README.md` | Features, installation, quick start, configuration |
| `docs/architecture.md` | System design, data flow, import pipeline, lot tracking |
| `docs/schema_reference.md` | All database tables with column definitions and example queries |
| `docs/tools_reference.md` | All 39 MCP tools and CLI commands with parameters and examples |
| `docs/roadmap.md` | Completed features, known limitations, future ideas |
| `CONTRIBUTING.md` | Code conventions, how to add importers/tools/summaries |
| `example/quickstart.md` | Step-by-step walkthrough from install to portfolio analysis |
| `CHANGELOG.md` | What changed in each release |

## Critical invariants

These rules prevent data corruption. Violating them causes silent bugs.

- **Never use `float` for money.** Use `Decimal("10.50")`, not `Decimal(10.50)`.
  Convert from JSON via `Decimal(str(value))`.
- **Postings must sum to zero.** When a posting has a `price` field, its weight
  is `amount * price` in `price_currency`.
- **Every write operation** must wrap core table changes AND summary refresh in
  a single `db.transaction()`. If the refresh fails, everything rolls back.
- **Import never moves or deletes** the user's original files. Copy only.
- **`query` tool** must set `PRAGMA query_only = ON` before executing user SQL.

## Common mistakes

- `json.loads()` returns float → always `Decimal(str(value))`, not `Decimal(value)`
- New write operation missing `registry.refresh_all()` inside the transaction
- `s_monthly_spending` is keyed by expense account, not the bank account
- `lots.quantity` is mutable; `lots.original_quantity` is immutable (used by rebuild)
- `source_files.path` is relative to `statements/`; `original_path` is absolute
- Posting with `price` must auto-record to the `prices` table
- Wash sale: check ±30 calendar days on LOSS dispositions only

## Running tests

```bash
python -m pytest tests/ -v
```

## LLM-assisted document import workflow

For documents without a built-in parser (payslips, tax forms, receipts, etc.):

1. `ingest_document(file_path)` — archives file, extracts text, classifies type, returns hints
2. LLM interprets the extracted content using the type-specific hints
3. `submit_transactions(transactions, source_file_id=N)` — batch-commits with provenance
4. `undo_import(source_file_id=N)` — reverses everything if needed

For payslips specifically: call `setup_payroll_accounts(employer)` first to create
the account hierarchy, then use `submit_transactions` with the payslip line items.

For tax documents: call `reconcile_tax_document(form_type, year, fields)` to compare
form data against the ledger. Use `tax_readiness_report(year)` for gap analysis.

## Template-based document import

For documents where a template exists (learn once, apply forever):

1. `learn_template(file_path, template_name)` — extracts text and returns hints
2. LLM generates regex patterns → calls `save_document_template(...)` to save
3. `apply_template(file_path, dry_run=True)` — auto-matches template, previews extraction
4. `apply_template(file_path, dry_run=False)` — submits transactions

## Post-import cleanup

- `batch_recategorize(pattern, old_account, new_account)` — bulk recategorize by payee
- `find_duplicates()` → `merge_duplicates(keep, delete)` — cross-source duplicate cleanup
- `detect_transfers()` → `link_transfer(from, to)` — link inter-account transfers
- `import_report()` — health check for uncategorized, duplicates, anomalies, gaps
