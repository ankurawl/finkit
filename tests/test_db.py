from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from finkit.db import Database, SCHEMA_VERSION
from finkit.config import Settings


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    database.create_schema()
    yield database
    database.close()


def test_create_database(tmp_path):
    path = tmp_path / "new.db"
    database = Database(path)
    database.connect()
    assert path.exists()
    database.close()


def test_wal_mode(db):
    result = db.fetchone("PRAGMA journal_mode")
    assert result["journal_mode"] == "wal"


def test_foreign_keys_enabled(db):
    result = db.fetchone("PRAGMA foreign_keys")
    assert result["foreign_keys"] == 1


_CORE_TABLES = [
    "source_files",
    "raw_extractions",
    "accounts",
    "transactions",
    "postings",
    "lots",
    "lot_dispositions",
    "prices",
    "categorization_rules",
    "balance_assertions",
    "column_mappings",
    "currency_tolerances",
    "recurring_transactions",
    "budgets",
    "transaction_tags",
    "schema_version",
]


def test_schema_creation(db):
    tables = {
        row["name"]
        for row in db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 's\\__%' ESCAPE '\\'"
        )
    }
    for table in _CORE_TABLES:
        assert table in tables, f"Missing core table: {table}"


_SUMMARY_TABLES = [
    "s_daily_balances",
    "s_monthly_spending",
    "s_portfolio_holdings",
    "s_account_monthly_balances",
    "s_net_worth",
    "s_yearly_capital_gains",
]


def test_summary_tables_created(db):
    tables = {
        row["name"]
        for row in db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 's_%'"
        )
    }
    for table in _SUMMARY_TABLES:
        assert table in tables, f"Missing summary table: {table}"


_EXPECTED_INDEXES = [
    "idx_transactions_date",
    "idx_postings_account",
    "idx_postings_transaction",
    "idx_transactions_uuid",
    "idx_transactions_payee",
    "idx_transactions_source",
    "idx_source_files_institution",
    "idx_raw_extractions_source",
    "idx_accounts_type",
    "idx_lots_account_commodity",
    "idx_lots_commodity_disposed",
    "idx_lot_dispositions_sell",
    "idx_prices_commodity_date",
    "idx_cat_rules_priority",
]


def test_indexes_exist(db):
    indexes = {
        row["name"]
        for row in db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    for idx in _EXPECTED_INDEXES:
        assert idx in indexes, f"Missing index: {idx}"


def test_schema_version(db):
    row = db.fetchone("SELECT version FROM schema_version WHERE version = ?", (SCHEMA_VERSION,))
    assert row is not None
    assert row["version"] == 1


def test_transaction_rollback(db):
    db.execute(
        "INSERT INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
        ("Assets:Test:Checking", "Assets", "USD", "2024-01-01"),
    )
    db.conn.commit()

    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
                ("Assets:Test:Savings", "Assets", "USD", "2024-01-01"),
            )
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    rows = db.fetchall("SELECT name FROM accounts WHERE name = 'Assets:Test:Savings'")
    assert len(rows) == 0

    rows = db.fetchall("SELECT name FROM accounts WHERE name = 'Assets:Test:Checking'")
    assert len(rows) == 1


def test_query_readonly(db):
    db.execute(
        "INSERT INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
        ("Assets:Bank:Checking", "Assets", "USD", "2024-01-01"),
    )
    db.conn.commit()

    results = db.query_readonly("SELECT name FROM accounts WHERE name = 'Assets:Bank:Checking'")
    assert len(results) == 1
    assert results[0]["name"] == "Assets:Bank:Checking"

    with pytest.raises(sqlite3.OperationalError):
        db.query_readonly(
            "INSERT INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
            ("Assets:Bank:Savings", "Assets", "USD", "2024-01-01"),
        )


def test_connection_reuse(db):
    conn1 = db.conn
    conn2 = db.conn
    assert conn1 is conn2


def test_backup(tmp_path, db):
    db.execute(
        "INSERT INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
        ("Assets:Chase:Checking", "Assets", "USD", "2024-01-01"),
    )
    db.execute(
        "INSERT INTO currency_tolerances (currency, tolerance) VALUES (?, ?)",
        ("USD", str(Decimal("0.01"))),
    )
    db.conn.commit()

    backup_path = tmp_path / "backups" / "backup.db"
    db.backup(backup_path)

    assert backup_path.exists()

    backup_db = Database(backup_path, read_only=True)
    backup_db.connect()
    try:
        rows = backup_db.fetchall("SELECT name FROM accounts WHERE name = 'Assets:Chase:Checking'")
        assert len(rows) == 1

        tol = backup_db.fetchone("SELECT tolerance FROM currency_tolerances WHERE currency = 'USD'")
        assert tol is not None
        assert Decimal(tol["tolerance"]) == Decimal("0.01")

        integrity = backup_db.fetchone("PRAGMA integrity_check")
        assert integrity["integrity_check"] == "ok"
    finally:
        backup_db.close()
