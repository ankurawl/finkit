from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from finkit.config import Settings
from finkit.db import Database
from finkit.operations import init_ledger, open_account

# Import summary builders so they register themselves
import finkit.summaries.daily_balances  # noqa: F401
import finkit.summaries.monthly_spending  # noqa: F401
import finkit.summaries.monthly_balances  # noqa: F401
import finkit.summaries.portfolio_holdings  # noqa: F401
import finkit.summaries.capital_gains  # noqa: F401
import finkit.summaries.net_worth  # noqa: F401


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "finance"


@pytest.fixture
def settings(data_dir):
    return Settings(data_dir=data_dir)


@pytest.fixture
def ledger_db(settings) -> Database:
    db = init_ledger(settings)
    yield db
    db.close()


@pytest.fixture
def chase_csv() -> Path:
    return FIXTURES_DIR / "chase_checking.csv"


@pytest.fixture
def hdfc_csv() -> Path:
    return FIXTURES_DIR / "hdfc_savings.csv"


@pytest.fixture
def schwab_csv() -> Path:
    return FIXTURES_DIR / "schwab_brokerage.csv"


CHASE_MAPPING = {
    "date_col": "Posting Date",
    "payee_col": "Description",
    "amount_col": "Amount",
    "amount_sign": "negative_is_debit",
    "date_format": "%m/%d/%Y",
    "default_currency": "USD",
}

HDFC_MAPPING = {
    "date_col": "Date",
    "narration_col": "Narration",
    "amount_sign": "separate_columns",
    "debit_col": "Withdrawal Amt.",
    "credit_col": "Deposit Amt.",
    "date_format": "%d/%m/%Y",
    "default_currency": "INR",
}


def create_multi_source_setup(db):
    """Creates 2 source files and standard accounts for cross-source tests.
    Returns (source_file_id_1, source_file_id_2, account_ids dict).
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    accounts = {}
    for name, acct_type in [
        ("Assets:BankA:Checking", "Assets"),
        ("Assets:BankB:Savings", "Assets"),
        ("Expenses:Uncategorized", "Expenses"),
        ("Income:Uncategorized", "Income"),
    ]:
        row = db.fetchone("SELECT id FROM accounts WHERE name = ?", (name,))
        if row is None:
            cursor = db.execute(
                "INSERT INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
                (name, acct_type, "USD", now),
            )
            accounts[name] = cursor.lastrowid
        else:
            accounts[name] = row["id"]

    c1 = db.execute(
        "INSERT INTO source_files (path, original_path, sha256, file_type, imported_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("2024/bankA.csv", "/tmp/bankA.csv", "sha_source1", "csv", now),
    )
    sf1 = c1.lastrowid

    c2 = db.execute(
        "INSERT INTO source_files (path, original_path, sha256, file_type, imported_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("2024/bankB.csv", "/tmp/bankB.csv", "sha_source2", "csv", now),
    )
    sf2 = c2.lastrowid

    db.conn.commit()
    return sf1, sf2, accounts
