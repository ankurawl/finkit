from __future__ import annotations

import pytest

from finkit.analysis.import_report import import_report
from finkit.config import Settings
from finkit.operations import init_ledger, open_account, submit_transaction
from tests.conftest import create_multi_source_setup


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def ledger_db(settings):
    db = init_ledger(settings)
    yield db
    db.close()


@pytest.fixture
def report_db(ledger_db):
    sf1, sf2, accounts = create_multi_source_setup(ledger_db)

    submit_transaction(
        ledger_db, date="2024-01-15", payee="Salary",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-5000.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        ledger_db, date="2024-03-15", payee="Salary",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-5000.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        ledger_db, date="2024-01-15", payee="Salary",
        postings=[
            {"account": "Assets:BankB:Savings", "amount": "5000.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-5000.00", "currency": "USD"},
        ],
        source_file_id=sf2,
    )

    return ledger_db, sf1, sf2


def test_report_structure(report_db):
    db, sf1, sf2 = report_db
    report = import_report(db)

    assert "source_files" in report
    assert "uncategorized" in report
    assert "potential_duplicates" in report
    assert "balance_anomalies" in report
    assert "missing_periods" in report
    assert "orphaned_source_files" in report
    assert "summary" in report


def test_uncategorized_detection(report_db):
    db, sf1, sf2 = report_db
    report = import_report(db)
    assert report["uncategorized"]["count"] > 0


def test_duplicates_in_report(report_db):
    db, sf1, sf2 = report_db
    report = import_report(db)
    assert isinstance(report["potential_duplicates"], list)


def test_missing_month_detection(report_db):
    db, sf1, sf2 = report_db
    report = import_report(db)

    bank_a_missing = [
        m for m in report["missing_periods"]
        if m["account"] == "Assets:BankA:Checking"
    ]
    if bank_a_missing:
        assert "2024-02" in bank_a_missing[0]["missing_months"]


def test_source_file_filter(report_db):
    db, sf1, sf2 = report_db
    report = import_report(db, source_file_id=sf1)
    assert len(report["source_files"]) == 1
    assert report["source_files"][0]["id"] == sf1


def test_negative_asset_anomaly(ledger_db):
    open_account(ledger_db, name="Assets:Test:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Test", type="Expenses")
    ledger_db.conn.commit()

    submit_transaction(
        ledger_db, date="2024-01-01", payee="Overdraft",
        postings=[
            {"account": "Assets:Test:Checking", "amount": "-100.00", "currency": "USD"},
            {"account": "Expenses:Test", "amount": "100.00", "currency": "USD"},
        ],
    )

    report = import_report(ledger_db)
    anomalies = [a for a in report["balance_anomalies"] if a["account"] == "Assets:Test:Checking"]
    assert len(anomalies) == 1
    assert anomalies[0]["issue"] == "negative asset"
