from __future__ import annotations

from decimal import Decimal

import pytest

from finkit.config import Settings
from finkit.db import Database
from finkit.engine.validation import UnbalancedTransactionError
from finkit.operations import (
    amend_transaction,
    assert_balance,
    init_ledger,
    open_account,
    recategorize_posting,
    submit_transaction,
    submit_transactions,
    undo_import,
)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def ledger_db(settings):
    db = init_ledger(settings)
    yield db
    db.close()


def test_init_creates_db(settings):
    db = init_ledger(settings)
    try:
        assert settings.db_path.exists()
        tables = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {r["name"] for r in tables}
        assert "accounts" in table_names
        assert "transactions" in table_names
        assert "postings" in table_names
    finally:
        db.close()


def test_init_existing_db(settings):
    db1 = init_ledger(settings)
    db1.close()

    db2 = init_ledger(settings)
    try:
        assert settings.db_path.exists()
        row = db2.fetchone("SELECT name FROM accounts WHERE name = 'Equity:OpeningBalances'")
        assert row is not None
    finally:
        db2.close()


def test_open_account(ledger_db):
    acct_id = open_account(
        ledger_db,
        name="Assets:Chase:Checking",
        type="Assets",
        currency="USD",
        institution="Chase",
    )
    assert acct_id is not None

    row = ledger_db.fetchone("SELECT * FROM accounts WHERE id = ?", (acct_id,))
    assert row["name"] == "Assets:Chase:Checking"
    assert row["type"] == "Assets"
    assert row["currency"] == "USD"
    assert row["institution"] == "Chase"


def test_open_account_invalid_hierarchy(ledger_db):
    with pytest.raises(ValueError, match="First segment must be one of"):
        open_account(ledger_db, name="Invalid:Account", type="Invalid")


def test_submit_simple_transaction(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-03-15",
        payee="Whole Foods",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "50.00", "currency": "USD"},
        ],
    )

    assert uuid is not None
    assert len(uuid) == 8

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn is not None
    assert txn["payee"] == "Whole Foods"
    assert txn["date"] == "2024-03-15"


def test_submit_opening_balance(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-01-01",
        narration="Opening balance",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Equity:OpeningBalances", "amount": "-5000.00", "currency": "USD"},
        ],
    )

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn is not None

    postings = ledger_db.fetchall(
        "SELECT p.*, a.name AS account_name FROM postings p JOIN accounts a ON p.account_id = a.id WHERE p.transaction_id = ?",
        (txn["id"],),
    )
    assert len(postings) == 2

    account_names = {p["account_name"] for p in postings}
    assert "Equity:OpeningBalances" in account_names
    assert "Assets:Chase:Checking" in account_names


def test_submit_investment_buy(ledger_db):
    open_account(
        ledger_db,
        name="Assets:Fidelity:Brokerage",
        type="Assets",
        currency="USD",
        booking_method="FIFO",
    )
    open_account(ledger_db, name="Assets:Fidelity:Cash", type="Assets")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-02-01",
        narration="Buy AAPL",
        postings=[
            {
                "account": "Assets:Fidelity:Brokerage",
                "amount": "10",
                "currency": "AAPL",
                "price": "150.00",
                "price_currency": "USD",
            },
            {
                "account": "Assets:Fidelity:Cash",
                "amount": "-1500.00",
                "currency": "USD",
            },
        ],
    )

    assert uuid is not None

    lots = ledger_db.fetchall("SELECT * FROM lots")
    assert len(lots) == 1
    assert lots[0]["commodity"] == "AAPL"
    assert Decimal(lots[0]["quantity"]) == Decimal("10")
    assert Decimal(lots[0]["cost_price"]) == Decimal("150.00")


def test_amend_transaction(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-04-01",
        payee="Trader Joes",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-60.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "60.00", "currency": "USD"},
        ],
    )

    amend_transaction(ledger_db, uuid, updates={"payee": "Trader Joe's"})

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn["payee"] == "Trader Joe's"


def test_amend_delete(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Dining", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-04-10",
        payee="Restaurant",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-45.00", "currency": "USD"},
            {"account": "Expenses:Dining", "amount": "45.00", "currency": "USD"},
        ],
    )

    txn_before = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn_before is not None

    amend_transaction(ledger_db, uuid, delete=True)

    txn_after = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn_after is None


def test_assert_balance_match(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    submit_transaction(
        ledger_db,
        date="2024-01-01",
        narration="Opening",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "1000.00", "currency": "USD"},
            {"account": "Equity:OpeningBalances", "amount": "-1000.00", "currency": "USD"},
        ],
    )

    submit_transaction(
        ledger_db,
        date="2024-01-15",
        payee="Grocery Store",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-150.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "150.00", "currency": "USD"},
        ],
    )

    result = assert_balance(
        ledger_db,
        account_name="Assets:Chase:Checking",
        date="2024-01-31",
        expected_amount="850.00",
        currency="USD",
    )

    assert result["matches"] is True
    assert Decimal(result["actual_amount"]) == Decimal("850.00")
    assert Decimal(result["expected_amount"]) == Decimal("850.00")


def test_atomic_rollback(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    with pytest.raises(UnbalancedTransactionError):
        submit_transaction(
            ledger_db,
            date="2024-05-01",
            payee="Bad Transaction",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-100.00", "currency": "USD"},
                {"account": "Expenses:Groceries", "amount": "99.00", "currency": "USD"},
            ],
        )

    txns = ledger_db.fetchall("SELECT * FROM transactions WHERE payee = 'Bad Transaction'")
    assert len(txns) == 0

    postings = ledger_db.fetchall("SELECT * FROM postings")
    assert len(postings) == 0


# ---------------------------------------------------------------------------
# source_file_id tests
# ---------------------------------------------------------------------------


def _create_source_file(db):
    """Insert a fake source_files row for testing provenance linkage."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor = db.execute(
        "INSERT INTO source_files (path, original_path, sha256, file_type, imported_at, original_filename) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2024/test.csv", "/tmp/test.csv", "abc123fake", "csv", now, "test.csv"),
    )
    db.conn.commit()
    return cursor.lastrowid


def test_submit_with_source_file_id(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    sf_id = _create_source_file(ledger_db)

    uuid = submit_transaction(
        ledger_db,
        date="2024-06-01",
        payee="Test Store",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-25.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "25.00", "currency": "USD"},
        ],
        source_file_id=sf_id,
    )

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn["source_file_id"] == sf_id


def test_submit_with_invalid_source_file_id(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    with pytest.raises(ValueError, match="source_file_id 9999 not found"):
        submit_transaction(
            ledger_db,
            date="2024-06-01",
            payee="Test Store",
            postings=[
                {"account": "Assets:Chase:Checking", "amount": "-25.00", "currency": "USD"},
                {"account": "Expenses:Groceries", "amount": "25.00", "currency": "USD"},
            ],
            source_file_id=9999,
        )


def test_submit_without_source_file_id(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-06-01",
        payee="Test Store",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-25.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "25.00", "currency": "USD"},
        ],
    )

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    assert txn["source_file_id"] is None


def test_undo_import_after_submit_with_source_file_id(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    sf_id = _create_source_file(ledger_db)

    submit_transaction(
        ledger_db,
        date="2024-06-01",
        payee="Store A",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-10.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "10.00", "currency": "USD"},
        ],
        source_file_id=sf_id,
    )
    submit_transaction(
        ledger_db,
        date="2024-06-02",
        payee="Store B",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-20.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "20.00", "currency": "USD"},
        ],
        source_file_id=sf_id,
    )

    txns_before = ledger_db.fetchall(
        "SELECT * FROM transactions WHERE source_file_id = ?", (sf_id,)
    )
    assert len(txns_before) == 2

    result = undo_import(ledger_db, source_file_id=sf_id)
    assert result["deleted_transactions"] == 2

    txns_after = ledger_db.fetchall(
        "SELECT * FROM transactions WHERE source_file_id = ?", (sf_id,)
    )
    assert len(txns_after) == 0


# ---------------------------------------------------------------------------
# submit_transactions (batch) tests
# ---------------------------------------------------------------------------


def test_submit_transactions_batch(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    open_account(ledger_db, name="Expenses:Dining", type="Expenses")
    ledger_db.conn.commit()

    sf_id = _create_source_file(ledger_db)

    uuids = submit_transactions(
        ledger_db,
        transactions=[
            {
                "date": "2024-07-01",
                "payee": "Store A",
                "postings": [
                    {"account": "Assets:Chase:Checking", "amount": "-30.00", "currency": "USD"},
                    {"account": "Expenses:Groceries", "amount": "30.00", "currency": "USD"},
                ],
            },
            {
                "date": "2024-07-02",
                "payee": "Restaurant",
                "postings": [
                    {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
                    {"account": "Expenses:Dining", "amount": "50.00", "currency": "USD"},
                ],
            },
            {
                "date": "2024-07-03",
                "payee": "Store B",
                "postings": [
                    {"account": "Assets:Chase:Checking", "amount": "-15.00", "currency": "USD"},
                    {"account": "Expenses:Groceries", "amount": "15.00", "currency": "USD"},
                ],
            },
        ],
        source_file_id=sf_id,
    )

    assert len(uuids) == 3

    for uuid in uuids:
        txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
        assert txn is not None
        assert txn["source_file_id"] == sf_id


def test_submit_transactions_atomic_rollback(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    with pytest.raises(UnbalancedTransactionError):
        submit_transactions(
            ledger_db,
            transactions=[
                {
                    "date": "2024-07-01",
                    "payee": "Good Transaction",
                    "postings": [
                        {"account": "Assets:Chase:Checking", "amount": "-30.00", "currency": "USD"},
                        {"account": "Expenses:Groceries", "amount": "30.00", "currency": "USD"},
                    ],
                },
                {
                    "date": "2024-07-02",
                    "payee": "Bad Transaction",
                    "postings": [
                        {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
                        {"account": "Expenses:Groceries", "amount": "49.00", "currency": "USD"},
                    ],
                },
            ],
        )

    txns = ledger_db.fetchall("SELECT * FROM transactions WHERE payee IN ('Good Transaction', 'Bad Transaction')")
    assert len(txns) == 0


def test_submit_transactions_empty(ledger_db):
    uuids = submit_transactions(ledger_db, transactions=[])
    assert uuids == []


def test_submit_transactions_undo(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    sf_id = _create_source_file(ledger_db)

    uuids = submit_transactions(
        ledger_db,
        transactions=[
            {
                "date": "2024-07-01",
                "payee": "Store",
                "postings": [
                    {"account": "Assets:Chase:Checking", "amount": "-10.00", "currency": "USD"},
                    {"account": "Expenses:Groceries", "amount": "10.00", "currency": "USD"},
                ],
            },
        ],
        source_file_id=sf_id,
    )
    assert len(uuids) == 1

    result = undo_import(ledger_db, source_file_id=sf_id)
    assert result["deleted_transactions"] == 1

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuids[0],))
    assert txn is None


# ---------------------------------------------------------------------------
# recategorize_posting tests
# ---------------------------------------------------------------------------


def test_recategorize_posting(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Uncategorized", type="Expenses")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-08-01",
        payee="Whole Foods",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "50.00", "currency": "USD"},
        ],
    )

    recategorize_posting(ledger_db, uuid, "Expenses:Uncategorized", "Expenses:Groceries")

    txn = ledger_db.fetchone("SELECT * FROM transactions WHERE uuid = ?", (uuid,))
    postings = ledger_db.fetchall(
        "SELECT p.*, a.name AS account_name FROM postings p JOIN accounts a ON p.account_id = a.id "
        "WHERE p.transaction_id = ?",
        (txn["id"],),
    )
    account_names = {p["account_name"] for p in postings}
    assert "Expenses:Groceries" in account_names
    assert "Expenses:Uncategorized" not in account_names


def test_recategorize_posting_not_found(ledger_db):
    with pytest.raises(ValueError, match="not found"):
        recategorize_posting(ledger_db, "deadbeef", "X", "Y")


def test_recategorize_posting_no_match(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Dining", type="Expenses")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    open_account(ledger_db, name="Expenses:Travel", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-08-02",
        payee="Restaurant",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-30.00", "currency": "USD"},
            {"account": "Expenses:Dining", "amount": "30.00", "currency": "USD"},
        ],
    )

    with pytest.raises(ValueError, match="No posting to"):
        recategorize_posting(ledger_db, uuid, "Expenses:Groceries", "Expenses:Travel")


def test_recategorize_posting_multiple_match(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Uncategorized", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-08-03",
        payee="Split Transaction",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-100.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "60.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "40.00", "currency": "USD"},
        ],
    )

    with pytest.raises(ValueError, match="Multiple postings"):
        recategorize_posting(ledger_db, uuid, "Expenses:Uncategorized", "Expenses:Groceries")


def test_recategorize_posting_by_id(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Uncategorized", type="Expenses")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-08-04",
        payee="Split Store",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-100.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "60.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "40.00", "currency": "USD"},
        ],
    )

    txn = ledger_db.fetchone("SELECT id FROM transactions WHERE uuid = ?", (uuid,))
    postings = ledger_db.fetchall(
        "SELECT id, amount FROM postings WHERE transaction_id = ? AND account_id = "
        "(SELECT id FROM accounts WHERE name = 'Expenses:Uncategorized') ORDER BY id",
        (txn["id"],),
    )
    target_id = postings[0]["id"]

    recategorize_posting(ledger_db, uuid, "Expenses:Uncategorized", "Expenses:Groceries", posting_id=target_id)

    updated = ledger_db.fetchone(
        "SELECT a.name FROM postings p JOIN accounts a ON p.account_id = a.id WHERE p.id = ?",
        (target_id,),
    )
    assert updated["name"] == "Expenses:Groceries"

    other = ledger_db.fetchone(
        "SELECT a.name FROM postings p JOIN accounts a ON p.account_id = a.id WHERE p.id = ?",
        (postings[1]["id"],),
    )
    assert other["name"] == "Expenses:Uncategorized"


def test_recategorize_posting_lot_tracked(ledger_db):
    open_account(
        ledger_db, name="Assets:Fidelity:Brokerage", type="Assets",
        booking_method="FIFO",
    )
    open_account(ledger_db, name="Expenses:Uncategorized", type="Expenses")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-08-05",
        payee="Test",
        postings=[
            {"account": "Expenses:Uncategorized", "amount": "100.00", "currency": "USD"},
            {"account": "Expenses:Groceries", "amount": "-100.00", "currency": "USD"},
        ],
    )

    with pytest.raises(ValueError, match="lot-tracked"):
        recategorize_posting(ledger_db, uuid, "Expenses:Groceries", "Assets:Fidelity:Brokerage")


def test_recategorize_posting_modified_at(ledger_db):
    open_account(ledger_db, name="Assets:Chase:Checking", type="Assets")
    open_account(ledger_db, name="Expenses:Uncategorized", type="Expenses")
    open_account(ledger_db, name="Expenses:Groceries", type="Expenses")
    ledger_db.conn.commit()

    uuid = submit_transaction(
        ledger_db,
        date="2024-08-06",
        payee="Store",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-25.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "25.00", "currency": "USD"},
        ],
    )

    txn_before = ledger_db.fetchone("SELECT modified_at FROM transactions WHERE uuid = ?", (uuid,))
    assert txn_before["modified_at"] is None

    recategorize_posting(ledger_db, uuid, "Expenses:Uncategorized", "Expenses:Groceries")

    txn_after = ledger_db.fetchone("SELECT modified_at FROM transactions WHERE uuid = ?", (uuid,))
    assert txn_after["modified_at"] is not None
