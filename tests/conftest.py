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
