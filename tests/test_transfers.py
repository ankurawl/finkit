from __future__ import annotations

import pytest

from finkit.analysis.transfers import detect_transfers
from finkit.config import Settings
from finkit.operations import init_ledger, link_transfer, submit_transaction
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
def transfer_db(ledger_db):
    sf1, sf2, accounts = create_multi_source_setup(ledger_db)

    submit_transaction(
        ledger_db, date="2024-03-01", payee="Transfer Out",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "-1000.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "1000.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        ledger_db, date="2024-03-01", payee="Transfer In",
        postings=[
            {"account": "Assets:BankB:Savings", "amount": "1000.00", "currency": "USD"},
            {"account": "Income:Uncategorized", "amount": "-1000.00", "currency": "USD"},
        ],
        source_file_id=sf2,
    )

    return ledger_db, sf1, sf2


def test_detect_transfers(transfer_db):
    db, sf1, sf2 = transfer_db
    transfers = detect_transfers(db)
    assert len(transfers) == 1
    t = transfers[0]
    assert t["outgoing_account"] == "Assets:BankA:Checking"
    assert t["incoming_account"] == "Assets:BankB:Savings"
    assert t["confidence"] == "high"


def test_link_transfer(transfer_db):
    db, sf1, sf2 = transfer_db
    transfers = detect_transfers(db)
    assert len(transfers) == 1

    out_uuid = transfers[0]["outgoing_uuid"]
    in_uuid = transfers[0]["incoming_uuid"]

    link_transfer(db, out_uuid, in_uuid)

    kept = db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (out_uuid,))
    assert kept is not None

    deleted = db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (in_uuid,))
    assert deleted is None

    postings = db.fetchall(
        "SELECT p.*, a.name AS account_name FROM postings p "
        "JOIN accounts a ON p.account_id = a.id "
        "WHERE p.transaction_id = ?",
        (kept["id"],),
    )
    account_names = {p["account_name"] for p in postings}
    assert "Assets:BankA:Checking" in account_names
    assert "Assets:BankB:Savings" in account_names
    assert "Expenses:Uncategorized" not in account_names


def test_no_false_positive_expenses(transfer_db):
    db, sf1, sf2 = transfer_db

    submit_transaction(
        db, date="2024-03-05", payee="Store A",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "-75.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "75.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )
    submit_transaction(
        db, date="2024-03-05", payee="Store B",
        postings=[
            {"account": "Assets:BankB:Savings", "amount": "-75.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "75.00", "currency": "USD"},
        ],
        source_file_id=sf2,
    )

    transfers = detect_transfers(db)
    transfer_amounts = [abs(float(t["outgoing_amount"])) for t in transfers]
    assert 75.0 not in transfer_amounts


def test_partial_transfer_no_match(ledger_db):
    sf1, sf2, accounts = create_multi_source_setup(ledger_db)

    submit_transaction(
        ledger_db, date="2024-03-01", payee="Transfer Out",
        postings=[
            {"account": "Assets:BankA:Checking", "amount": "-500.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "500.00", "currency": "USD"},
        ],
        source_file_id=sf1,
    )

    transfers = detect_transfers(ledger_db)
    assert len(transfers) == 0
