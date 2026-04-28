# Contributing to FinKit

## Development Setup

```bash
# Clone the repo
git clone https://github.com/ankuragwl/finkit.git
cd finkit

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode with all extras
pip install -e ".[market,dev]"

# Install Beancount v3 from source if needed
pip install git+https://github.com/beancount/beancount.git
pip install git+https://github.com/beancount/beanquery.git
pip install git+https://github.com/beancount/beangulp.git
```

## Running Tests

```bash
pytest                    # All tests
pytest tests/test_ledger.py  # Specific test file
pytest -v                 # Verbose output
```

## Code Style

- Python 3.10+ with type hints
- `from __future__ import annotations` in every module
- No unnecessary comments — code should be self-documenting
- Functions return dicts with a `status` key for consistent error handling

## Pull Request Process

1. Create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all tests pass: `pytest`
4. Keep PRs focused — one feature or fix per PR
5. Write a clear PR description explaining the "why"

## Architecture Rules

- Core library functions live in `src/personalfinance/`
- MCP server and CLI are thin wrappers — no business logic in either
- Every MCP tool must have a corresponding CLI command
- No personal data in tests — use fixtures with synthetic data
- Market data module must never send personal financial information
