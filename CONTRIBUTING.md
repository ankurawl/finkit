# Contributing to FinKit

## Setting Up the Development Environment

```bash
# Clone the repository
git clone https://github.com/your-org/finkit.git
cd finkit/finkit

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with all development extras
pip install -e ".[dev,market,excel,agent]"
```

Requires Python 3.10 or later.

## Running Tests

```bash
# Run the full test suite
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_validation.py -v

# Run tests matching a pattern
python -m pytest tests/ -k "test_lot" -v
```

Tests are written alongside each module, not deferred. When adding a new feature, include tests in the same pull request.

## Code Conventions

### Decimal Precision

All monetary amounts must use `decimal.Decimal` in Python and `TEXT` in SQLite. Never use `float` for money anywhere in the codebase.

```python
# Correct
from decimal import Decimal
amount = Decimal("10.50")
assert result == Decimal("157.50")

# WRONG - introduces float imprecision
amount = Decimal(10.50)
amount = 10.50
```

When reading amounts from JSON (including `raw_extractions.raw_data`), convert via the string representation:

```python
# Correct
amount = Decimal(str(json_value))

# WRONG - float intermediary
amount = Decimal(json_value)
```

### Double-Entry Invariant

Every transaction's postings must sum to zero within currency-aware tolerance. When a posting has a `price` field, its weight for balancing is `amount * price` in `price_currency`. This is enforced by `engine/validation.py` and must never be bypassed.

### Atomic Writes with Summary Refresh

Every write operation must wrap core table changes AND summary refresh in a single `db.transaction()`:

```python
with db.transaction():
    # 1. Write to core tables
    # 2. Build RefreshContext with affected accounts/dates/commodities
    # 3. registry.refresh_all(db, context)
```

If summary refresh fails, the entire operation rolls back. No partial state is acceptable.

### Python Style

- Target Python 3.10+. Use `from __future__ import annotations` where needed.
- Type hints on all public functions.
- Pydantic v2 for models that cross API boundaries. Dataclasses for internal-only structures.
- No comments unless the WHY is non-obvious. No docstrings that repeat the function signature.
- Raise specific exceptions (`UnbalancedTransactionError`, `DuplicateImportError`, `AccountNotFoundError`) rather than generic `ValueError`.

### SQLite

- WAL mode enabled on every connection.
- All dates stored as ISO 8601 TEXT.
- Foreign keys enforced (`PRAGMA foreign_keys = ON`).
- UUIDs are 8-char hex strings.

## Adding a New Summary Table

1. Create `src/finkit/summaries/my_summary.py`.
2. Define the table schema with a `CREATE TABLE` statement using the `s_` prefix.
3. Implement `rebuild(db)` --- full recompute from core tables. Must be idempotent.
4. Implement `refresh(db, context: RefreshContext)` --- incremental update using the context to scope the recomputation.
5. Register with the decorator: `@registry.register("s_my_table")`.
6. Run `finkit rebuild` to populate.
7. Add tests verifying that rebuild and incremental refresh produce identical results.

`RefreshContext` is defined in `summaries/registry.py` only, not in `models.py`.

## Adding a New Importer

### Supporting a new institution

1. Add a column mapping entry as JSON per the Column Mapping Schema in `plan2.md`. The mapping specifies which CSV columns correspond to date, payee, amount, etc.
2. Add categorization rules for common payee patterns from that institution.
3. Test with a sample file. Verify:
   - All original fields are preserved in `raw_extractions`
   - SHA-256 dedup works (re-importing is a no-op)
   - Categorization rules are applied
   - Summaries are refreshed atomically

### Supporting a new file format

1. Implement parsing logic in `importers/file_importer.py` (or a new module if the format is significantly different).
2. Ensure all original data is stored in `raw_extractions` as JSON.
3. The import must copy the file to `statements/{year}/` --- never move or delete the original.
4. Wrap everything in `db.transaction()` with `registry.refresh_all()`.

## Adding a New MCP Tool

1. Implement the backing function in the appropriate module:
   - Write operations: `operations.py`
   - Read operations: `queries.py`
   - Analysis: `analysis/*.py`
2. Wire it up in `mcp/server.py` with `Annotated` type descriptions for each parameter.
3. Add a matching CLI subcommand in `cli.py`.
4. Both the MCP tool and CLI subcommand must call the same backing function.

## Supporting a New Currency

1. Add a row to the `currency_tolerances` table with the appropriate precision.
2. No code changes needed --- tolerance lookup is dynamic.
