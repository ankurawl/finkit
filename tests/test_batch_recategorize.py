from __future__ import annotations

import pytest

from finkit.categorize.batch import find_matching_transactions
from finkit.operations import (
    batch_recategorize,
    init_ledger,
    open_account,
    submit_transaction,
)


@pytest.fixture
def settings(tmp_path):
    from finkit.config import Settings
    return Settings(data_dir=tmp_path)


@pytest.fixture
def ledger_db(settings):
    db = init_ledger(settings)
    yield db
    db.close()


@pytest.fixture
def seeded_db(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Uncategorized", type="Expenses")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    open_account(ledger_db, name="Expenses:Dining", type="Expenses")
    ledger_db.conn.commit()

    submit_transaction(
        ledger_db, date="2024-01-01", payee="Whole Foods Market",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "50.00", "currency": "USD"},
        ],
    )
    submit_transaction(
        ledger_db, date="2024-01-02", payee="Whole Foods",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-30.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "30.00", "currency": "USD"},
        ],
    )
    submit_transaction(
        ledger_db, date="2024-01-03", payee="Whole Foods Online",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-20.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "20.00", "currency": "USD"},
        ],
    )
    submit_transaction(
        ledger_db, date="2024-01-04", payee="Chipotle",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-15.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "15.00", "currency": "USD"},
        ],
    )
    submit_transaction(
        ledger_db, date="2024-01-05", payee="Taco Bell",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-8.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "8.00", "currency": "USD"},
        ],
    )
    return ledger_db


def test_batch_recategorize_dry_run(seeded_db):
    matches = find_matching_transactions(
        seeded_db, "Whole Foods", "substring", "Expenses:Uncategorized"
    )
    assert len(matches) == 3
    txn_count_before = seeded_db.fetchone(
        "SELECT COUNT(*) as c FROM postings p JOIN accounts a ON p.account_id = a.id "
        "WHERE a.name = 'Expenses:Uncategorized'"
    )
    assert txn_count_before["c"] == 5


def test_batch_recategorize_apply(seeded_db):
    count = batch_recategorize(
        seeded_db, "Whole Foods", "substring", "Expenses:Uncategorized", "Expenses:Groceries"
    )
    assert count == 3

    remaining = seeded_db.fetchone(
        "SELECT COUNT(*) as c FROM postings p JOIN accounts a ON p.account_id = a.id "
        "WHERE a.name = 'Expenses:Uncategorized'"
    )
    assert remaining["c"] == 2

    groceries = seeded_db.fetchone(
        "SELECT COUNT(*) as c FROM postings p JOIN accounts a ON p.account_id = a.id "
        "WHERE a.name = 'Expenses:Groceries'"
    )
    assert groceries["c"] == 3


def test_batch_recategorize_regex(seeded_db):
    count = batch_recategorize(
        seeded_db, r"^(Chipotle|Taco)", "regex", "Expenses:Uncategorized", "Expenses:Dining"
    )
    assert count == 2


def test_batch_recategorize_no_matches(seeded_db):
    count = batch_recategorize(
        seeded_db, "Nonexistent Store", "substring", "Expenses:Uncategorized", "Expenses:Groceries"
    )
    assert count == 0


def test_batch_recategorize_noop(seeded_db):
    count = batch_recategorize(
        seeded_db, "Whole Foods", "substring", "Expenses:Uncategorized", "Expenses:Uncategorized"
    )
    assert count == 0


def test_batch_recategorize_lot_tracked(seeded_db):
    open_account(
        seeded_db, name="Assets:Fidelity:Brokerage", type="Assets",
        booking_method="FIFO",
    )
    seeded_db.conn.commit()

    with pytest.raises(ValueError, match="lot-tracked"):
        batch_recategorize(
            seeded_db, "Whole Foods", "substring",
            "Expenses:Uncategorized", "Assets:Fidelity:Brokerage"
        )
