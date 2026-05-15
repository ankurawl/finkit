# FinKit Utilities Implementation Plan

**Status: COMPLETE** — All 7 utilities implemented and tested.

## Context

During a real-world session importing 220 financial documents (bank statements, CC statements, payslips, brokerage statements) and categorizing 1,700+ transactions, we identified key bottlenecks where the LLM performed mechanical work that software should handle. This plan adds 7 utilities to eliminate those bottlenecks, ordered by impact and simplicity.

**Key pain points addressed:**
- Amending one posting required reconstructing all postings (Utility 1)
- Recategorizing 1,500+ transactions one-by-one (Utility 2)
- Raw bank payees like "ACH Deposit ACME 9876543210 PP - DIRECT DEP" needed manual normalization (Utility 3)
- Salary deposits appeared in both bank CSV and payslip imports — no automated detection (Utility 4)
- CC payments appeared in both bank and CC statements — manual matching needed (Utility 5)
- No post-import health check for duplicates, anomalies, or gaps (Utility 6)
- Every new institution/document type required either a hard-coded parser or full LLM interpretation per file (Utility 7)

---

## Implementation Order

| # | Utility | Size | New Files | New DB Tables |
|---|---------|------|-----------|---------------|
| 1 | Posting-Level Amend | S | 0 | 0 |
| 2 | Batch Recategorize | S | 2 | 0 |
| 3 | Payee Normalizer | M | 2 | 1 |
| 4 | Cross-Source Duplicate Detector | M | 2 | 0 |
| 5 | Transfer Detector & Linker | M | 2 | 0 |
| 6 | Import Reconciliation Report | M | 2 | 0 |
| 7 | Document Template Engine | L | 3 | 1 |

**Files modified across all utilities** (touched repeatedly):
- `src/finkit/mcp/server.py` — new MCP tools
- `src/finkit/cli.py` — new CLI commands
- `docs/tools_reference.md` — tool documentation
- `src/finkit/db.py` — new tables (utilities 3, 7 only)
- `src/finkit/models.py` — new dataclasses (utilities 3, 7 only)

---

## Utility 1: Posting-Level Amend

**Size: S | Files: 0 new, 4 modified | No schema changes**

### Problem
To change one posting's account (e.g., `Expenses:Uncategorized` → `Expenses:Groceries`), the current `amend_transaction` requires querying all postings, rebuilding the full array, and resubmitting. For a 7-posting payslip transaction, that's error-prone.

### Implementation

**Add to `src/finkit/operations.py`:**
```python
def recategorize_posting(db, uuid, old_account, new_account) -> dict
```
- Look up transaction by uuid
- Find the posting where `account_id` matches `resolve_account(db, old_account)`
- Resolve `new_account` to account_id
- Within `db.transaction()`: UPDATE the single posting's `account_id`, set `modified_at`, call `registry.refresh_all()`
- Amounts do NOT change — only the account. No re-validation of balance needed.

**MCP tool** in `src/finkit/mcp/server.py`:
```python
@mcp.tool()
def recategorize_posting(uuid, old_account, new_account) -> dict
```

**CLI** in `src/finkit/cli.py`:
```
finkit recategorize-posting UUID --old-account NAME --new-account NAME
```

### Tests — add to `tests/test_operations.py`
- `TestRecategorizePosting`: change Expenses:Uncategorized → Expenses:Groceries, verify DB
- `TestRecategorizePostingNotFound`: bad uuid → error
- `TestRecategorizePostingNoMatch`: old_account not in transaction → error

### Docs
- Add section 26 to `docs/tools_reference.md`

---

## Utility 2: Batch Recategorize

**Size: S | 2 new files | No schema changes**

### Problem
Recategorizing 1,500+ transactions required individual amend calls. A single command that changes the account on all matching transactions would have saved ~60% of cleanup time.

### Implementation

**Create `src/finkit/categorize/batch.py`:**
```python
def batch_recategorize(db, pattern, pattern_type, old_account, new_account, dry_run=True) -> dict
```
- Resolve old/new accounts
- Query transactions where payee matches pattern AND has a posting to old_account
- Use same pattern-matching logic as `categorize/rules.py` (substring/regex/exact)
- `dry_run=True`: return `{"matches": [...], "count": N}` without changing anything
- `dry_run=False`: within single `db.transaction()`, UPDATE all matching postings, refresh summaries
- Return `{"updated": N}`

**MCP tool**: `batch_recategorize(pattern, pattern_type, old_account, new_account, dry_run)`
**CLI**: `finkit batch-recategorize PATTERN --old OLD --new NEW [--pattern-type substring] [--apply]`

### Tests — create `tests/test_batch_recategorize.py`
- `TestBatchRecategorizeDryRun`: 5 transactions, 3 match → count=3, no DB changes
- `TestBatchRecategorizeApply`: apply, verify 3 changed, 2 unchanged
- `TestBatchRecategorizeRegex`: regex pattern
- `TestBatchRecategorizeNoMatches`: returns count=0

### Docs
- Add section 27 to `docs/tools_reference.md`

---

## Utility 3: Payee Normalizer

**Size: M | 2 new files | 1 new table**

### Problem
The same payee appears as "ACH Deposit ACME 9876543210 PP - DIRECT DEP", "ACH Deposit ACME 9876543210 PP - PAYROLL", and "Acme". Downstream categorization and duplicate detection need clean names.

### Implementation

**Add to `src/finkit/db.py` (`_CORE_SCHEMA`):**
```sql
CREATE TABLE IF NOT EXISTS payee_normalization_rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    pattern_type TEXT DEFAULT 'substring',
    canonical_name TEXT NOT NULL,
    institution TEXT,
    priority INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
```

**Add to `src/finkit/models.py`:**
```python
@dataclass
class PayeeNormalizationRule:
    id, pattern, pattern_type, canonical_name, institution, priority, created_at
```

**Create `src/finkit/categorize/payee_normalizer.py`:**
```python
def normalize_payee(raw_payee, rules) -> str
def load_normalization_rules(db, institution=None) -> list
def manage_payee_rules(db, action, pattern?, canonical_name?, ...) -> dict
def normalize_existing_payees(db, dry_run=True) -> dict  # retroactive
```

**Integration**: In `src/finkit/importers/file_importer.py`, call `normalize_payee()` after `apply_mapping()` and before `categorize_transactions()`.

**MCP tools**: `payee_rules(action, pattern?, canonical_name?, ...)`, `normalize_existing_payees(dry_run?)`
**CLI**: `finkit payee-rules add|remove|list ...`, `finkit normalize-payees [--apply]`

### Tests — create `tests/test_payee_normalizer.py`
- Matching logic (substring/regex/exact), priority ordering
- Integration with import pipeline
- CRUD for rules
- Retroactive normalization

### Docs
- Add section 28-29 to `docs/tools_reference.md`
- Add table to `docs/schema_reference.md`

---

## Utility 4: Cross-Source Duplicate Detector

**Size: M | 2 new files | No schema changes**

### Problem
After importing from multiple sources (bank CSV + payslips + brokerage), duplicates appeared. Manual matching by amount/date across source files was tedious.

### Implementation

**Create `src/finkit/analysis/duplicates.py`:**
```python
def find_duplicates(db, tolerance_days=3, tolerance_amount="0.01", account_name=None) -> list[dict]
def merge_duplicates(db, keep_uuid, delete_uuid, enrich=False) -> dict
```

**`find_duplicates` algorithm:**
- Self-join transactions × postings where `source_file_id` differs
- Match on `ABS(amount1 - amount2) <= tolerance` AND `ABS(julianday(date1) - julianday(date2)) <= days`
- Score confidence: exact amount + exact date + similar payee = high; amount match + date window = medium
- Return grouped pairs with confidence and suggested action

**`merge_duplicates`**: delete one transaction, optionally copy narration/payee to the kept one, refresh summaries.

**MCP tools**: `find_duplicates(tolerance_days?, tolerance_amount?, account_name?)`, `merge_duplicates(keep_uuid, delete_uuid, enrich?)`
**CLI**: `finkit find-duplicates [--days 3] [--tolerance 0.01]`, `finkit merge-duplicates KEEP DELETE [--enrich]`

### Tests — create `tests/test_duplicates.py`
- Cross-source detection (2 source files, overlapping transactions)
- No false positives (different amounts or far-apart dates)
- Merge with enrichment
- Confidence scoring

### Docs
- Add sections 30-31 to `docs/tools_reference.md`

---

## Utility 5: Transfer Detector & Linker

**Size: M | 2 new files | No schema changes**

### Problem
A transfer from FirstTech to Marcus creates two transactions (one per bank import) with Uncategorized contra accounts. Manual matching and linking was required.

### Implementation

**Create `src/finkit/analysis/transfers.py`:**
```python
def detect_transfers(db, tolerance_days=3) -> list[dict]
def link_transfer(db, uuid_from, uuid_to) -> dict
```

**`detect_transfers` algorithm:**
- Find debit-side candidates: posting to Assets/Liabilities (negative) + posting to Uncategorized (positive)
- Find credit-side candidates: posting to Assets/Liabilities (positive) + posting to Uncategorized (negative)
- Match pairs by absolute amount + date window
- Return pairs with confidence and account names

**`link_transfer`**: keep `uuid_from`, replace its Uncategorized posting with the real account from `uuid_to`, delete `uuid_to`, refresh summaries.

**MCP tools**: `detect_transfers(tolerance_days?)`, `link_transfer(uuid_from, uuid_to)`
**CLI**: `finkit detect-transfers [--days 3]`, `finkit link-transfer UUID_FROM UUID_TO`

### Tests — create `tests/test_transfers.py`
- Create $1000 transfer imported from both sides, verify detection
- Link and verify single A→B transaction remains
- No false positives (expenses with matching amounts)

### Docs
- Add sections 32-33 to `docs/tools_reference.md`

---

## Utility 6: Import Reconciliation Report

**Size: M | 2 new files | No schema changes**

### Problem
After importing 138 files, there was no summary of overlaps, missing data, or anomalies. Problems were discovered only when querying income totals.

### Implementation

**Create `src/finkit/analysis/import_report.py`:**
```python
def import_report(db, source_file_id=None) -> dict
```

**Read-only analysis that returns:**
1. **Source file summary**: files imported, transaction counts per file
2. **Uncategorized count**: transactions with Uncategorized postings
3. **Potential duplicates**: same amount + date + account across different source files
4. **Balance anomalies**: negative Asset balances, positive Liability balances (sign errors)
5. **Missing periods**: months with no transactions between min/max dates per account
6. **Summary stats**: date range, total transactions, by status, by account type

**MCP tool**: `import_report(source_file_id?)`
**CLI**: `finkit import-report [SOURCE_FILE_ID]`

### Tests — create `tests/test_import_report.py`
- Basic report structure
- Uncategorized detection
- Known duplicates appear
- Negative asset balance flagged
- Missing month detection

### Docs
- Add section 34 to `docs/tools_reference.md`

---

## Utility 7: Document Template Engine

**Size: L | 3 new files | 1 new table | Broken into 5 sub-phases**

### Problem
Every new institution required either a hard-coded Python parser or full LLM interpretation per file. In this session, the LLM interpreted ~125 PDFs. After the first file from each source, it was doing the same mechanical regex extraction repeatedly.

### Design: Learn Once, Apply Forever
- **Phase 1 (learn)**: LLM examines one document → generates regex patterns + field-to-account mapping → saved as a template
- **Phase 2 (apply)**: New documents from same source → template auto-matched → regex extraction → transactions created. No LLM needed.

### Sub-Phase 7A: Schema & Storage (S)

**Add to `src/finkit/db.py` (`_CORE_SCHEMA`):**
```sql
CREATE TABLE IF NOT EXISTS document_templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL DEFAULT 1,
    institution TEXT,
    document_type TEXT NOT NULL,
    mode TEXT NOT NULL,
    match_keywords TEXT NOT NULL,
    template_json TEXT NOT NULL,
    account_mapping TEXT,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    use_count INTEGER DEFAULT 0
);
```

**Add to `src/finkit/models.py`:** `DocumentTemplate` dataclass.

**Create `src/finkit/importers/template_store.py`:**
```python
def save_template(db, template) -> int
def load_template(db, name) -> DocumentTemplate | None
def list_templates(db, institution=None) -> list
def delete_template(db, name) -> bool
def find_matching_template(db, text) -> DocumentTemplate | None
def update_last_used(db, template_id) -> None
```

### Sub-Phase 7B: Template Format (M)

Two modes in `template_json`:

**Table-mode** (bank/CC statements — multiple transactions per document):
```json
{
    "mode": "table",
    "sections": [{"name": "...", "start_pattern": "...", "end_pattern": "...",
                   "row_pattern": "regex", "fields": {"date": {}, "payee": {}, "amount": {}}}],
    "year_inference": {"method": "filename_pattern", "pattern": "..."},
    "skip_patterns": ["PAYMENTS AND"]
}
```

**Field-mode** (payslips, mortgage — one multi-posting transaction per document):
```json
{
    "mode": "field",
    "fields": [{"name": "gross_pay", "pattern": "regex", "type": "amount", "required": true}],
    "date_field": {"pattern": "regex", "format": "%m/%d/%Y"}
}
```

**Account mapping** (shared): `{"gross_pay": {"account": "Income:Salary:Meta", "sign": "negative"}}`

### Sub-Phase 7C: Application Engine (M)

**Create `src/finkit/importers/template_engine.py`:**
```python
def apply_template(db, file_path, template_name=None, password=None, dry_run=True, settings=None) -> dict
```
- Extract text → match template (or use specified name) → run regex patterns → build transactions → confidence score → submit if not dry_run
- Confidence = fields_extracted / fields_expected. High ≥ 90%, Medium ≥ 70%, Low < 70%.

### Sub-Phase 7D: Learning Interface (M)

```python
def learn_template(db, file_path, template_name, institution=None, ...) -> dict
```
- Extracts text, classifies document, returns text + hints + instructions for LLM to generate template JSON
- LLM calls `save_document_template()` MCP tool with the generated template
- User confirms via `apply_template(dry_run=True)` preview

### Sub-Phase 7E: MCP Tools & CLI (S)

**MCP tools**: `learn_template`, `save_document_template`, `apply_template`, `list_templates`, `delete_template`
**CLI**: `finkit learn-template`, `finkit apply-template`, `finkit list-templates`, `finkit delete-template`

### Tests — create `tests/test_template_engine.py`
- Template store CRUD
- Keyword matching for auto-detection
- Table-mode extraction with mock statement text
- Field-mode extraction with mock payslip text
- Confidence scoring at various levels
- Full pipeline: apply → submit → verify DB
- Year inference from filenames

### Docs
- Add sections 35-39 to `docs/tools_reference.md`
- Add table to `docs/schema_reference.md`
- Add template engine section to `docs/architecture.md`

---

## Cross-Cutting: DB Migration

For existing databases, add a migration check called from `_get_db()` in `mcp/server.py` and CLI handlers:
```python
def ensure_new_tables(db):
    db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS payee_normalization_rules (...);
        CREATE TABLE IF NOT EXISTS document_templates (...);
    """)
```

## Verification Strategy

After each utility:
1. `python -m pytest tests/ -v` — all tests pass
2. Manual test with real data via CLI
3. MCP tool test via the MCP server

After all utilities:
1. Re-import a sample of the 220 documents using the new tools
2. Verify the template engine can learn from one Meta payslip and apply to all 36 others
3. Verify batch_recategorize can do in one command what took 800+ individual amends
4. Verify find_duplicates catches the salary/CC/RSU duplicates we found manually
