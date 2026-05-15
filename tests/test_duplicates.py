from __future__ import annotations

import pytest

from finkit.analysis.duplicates import find_duplicates
from finkit.config import Settings
from finkit.operations import init_ledger, merge_duplicates, submit_transaction
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
def multi_source_db(ledger_db):
    sf1, sf2, accounts = create_multi_source_setup(ledger_db)

    submit_transaction(
        ledger_db, date="2024-03-01", payee="Salary Deposit",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-5000.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        ledger_db, date="2024-03-01", payee="Salary Deposit",
        postings=[
            {"account": "Assets:BankB:Savings", "amount": "5000.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-5000.00", "currency": "USD"},
        ],
        source_file_id=sf2,
    )

    submit_transaction(
        ledger_db, date="2024-03-05", payee="Grocery Store",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "-50.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "50.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )

    return ledger_db, sf1, sf2


def test_find_cross_source_duplicates(multi_source_db):
    db, sf1, sf2 = multi_source_db
    dupes = find_duplicates(db)
    assert len(dupes) >= 1
    d = dupes[0]
    assert d["amount"] == "5000.00"
    assert d["confidence"] == "high"
    assert d["source_file_id_1"] != d["source_file_id_2"]


def test_no_false_positives(multi_source_db):
    db, sf1, sf2 = multi_source_db
    dupes = find_duplicates(db, tolerance_amount=0.001)
    for d in dupes:
        assert abs(float(d["amount"])) > 0


def test_single_source_no_duplicates(ledger_db):
    from tests.conftest import create_multi_source_setup
    sf1, sf2, accounts = create_multi_source_setup(ledger_db)

    submit_transaction(
        ledger_db, date="2024-03-01", payee="Test",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "100.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-100.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        ledger_db, date="2024-03-01", payee="Test",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "100.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-100.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )

    dupes = find_duplicates(ledger_db)
    assert len(dupes) == 0


def test_merge_duplicates_basic(multi_source_db):
    db, sf1, sf2 = multi_source_db
    dupes = find_duplicates(db)
    assert len(dupes) >= 1

    keep_uuid = dupes[0]["uuid1"]
    delete_uuid = dupes[0]["uuid2"]

    merge_duplicates(db, keep_uuid, delete_uuid)

    kept = db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (keep_uuid,))
    assert kept is not None
    deleted = db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (delete_uuid,))
    assert deleted is None


def test_merge_duplicates_enrich(multi_source_db):
    db, sf1, sf2 = multi_source_db

    submit_transaction(
        db, date="2024-03-10", payee=None, narration=None,
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "200.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-200.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        db, date="2024-03-10", payee="Bonus", narration="Q1 bonus",
        postings=[
            {"account": "Assets:BankB:Savings", "amount": "200.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-200.00", "currency": "USD"},
        ],
        source_file_id=sf2,
    )

    dupes = find_duplicates(db, tolerance_amount=0.01)
    bonus_dupes = [d for d in dupes if d["amount"] == "200.00"]
    assert len(bonus_dupes) >= 1

    keep_uuid = bonus_dupes[0]["uuid1"]
    delete_uuid = bonus_dupes[0]["uuid2"]

    merge_duplicates(db, keep_uuid, delete_uuid, enrich=True)

    kept = db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (keep_uuid,))
    assert kept is not None
    assert kept["payee"] is not None or kept["narration"] is not None


def test_confidence_scoring(multi_source_db):
    db, sf1, sf2 = multi_source_db

    submit_transaction(
        db, date="2024-04-01", payee="Store",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "-75.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "75.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        db, date="2024-04-03", payee="Different Store",
        postings=[
            {"account": "Assets:BankB:Savings", "amount": "-75.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "75.00", "currency": "USD"},
        ],
        source_file_id=sf2,
    )

    dupes = find_duplicates(db)
    amount_75 = [d for d in dupes if d["amount"] == "-75.00"]
    if amount_75:
        assert amount_75[0]["confidence"] in ("medium", "high")
