from __future__ import annotations

from decimal import Decimal

import pytest

from finkit.db import Database
from finkit.categorize.rules import (
    add_rule,
    categorize_transactions,
    list_rules,
    load_rules,
    match_transaction,
    remove_rule,
)
from finkit.models import CategorizationRule, Posting, Transaction


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    database.create_schema()
    database.execute("INSERT INTO currency_tolerances VALUES ('USD', '0.01')")
    database.execute("INSERT INTO currency_tolerances VALUES ('INR', '0.01')")
    database.execute("INSERT INTO currency_tolerances VALUES ('BTC', '0.00000001')")
    database.conn.commit()
    yield database
    database.close()


def _create_account(db, name, type_, currency="USD", **kwargs):
    db.execute(
        "INSERT INTO accounts (name, type, currency, booking_method, institution, asset_class, jurisdiction, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, '2024-01-01')",
        (name, type_, currency, kwargs.get("booking_method"), kwargs.get("institution"), kwargs.get("asset_class"), kwargs.get("jurisdiction")),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_substring_match(db):
    add_rule(db, "AMAZON", "Expenses:Shopping", pattern_type="substring")
    rules = load_rules(db)
    result = match_transaction("Amazon.com Purchase", rules)
    assert result == "Expenses:Shopping"


def test_regex_match(db):
    add_rule(db, r"WAL.?MART", "Expenses:Groceries", pattern_type="regex")
    rules = load_rules(db)

    assert match_transaction("WALMART", rules) == "Expenses:Groceries"
    assert match_transaction("WAL MART", rules) == "Expenses:Groceries"


def test_exact_match(db):
    add_rule(db, "Netflix", "Expenses:Subscriptions", pattern_type="exact")
    rules = load_rules(db)

    assert match_transaction("Netflix", rules) == "Expenses:Subscriptions"
    assert match_transaction("netflix", rules) == "Expenses:Subscriptions"
    assert match_transaction("Netflix Inc", rules) is None


def test_priority_ordering(db):
    add_rule(db, "AMAZON", "Expenses:Shopping", pattern_type="substring", priority=1)
    add_rule(db, "AMAZON", "Expenses:Groceries:AmazonFresh", pattern_type="substring", priority=10)
    rules = load_rules(db)

    result = match_transaction("AMAZON FRESH DELIVERY", rules)
    assert result == "Expenses:Groceries:AmazonFresh"


def test_no_match(db):
    add_rule(db, "TARGET", "Expenses:Shopping", pattern_type="substring")
    rules = load_rules(db)

    result = match_transaction("Costco Wholesale", rules)
    assert result is None


def test_add_remove_rule(db):
    rule_id = add_rule(db, "STARBUCKS", "Expenses:Coffee", pattern_type="substring")
    rules = list_rules(db)
    assert any(r.id == rule_id for r in rules)

    removed = remove_rule(db, rule_id)
    assert removed is True

    rules = list_rules(db)
    assert not any(r.id == rule_id for r in rules)

    removed_again = remove_rule(db, rule_id)
    assert removed_again is False


def test_categorize_transactions(db):
    _create_account(db, "Assets:Chase:Checking", "Assets")
    _create_account(db, "Expenses:Uncategorized", "Expenses")

    add_rule(db, "WHOLE FOODS", "Expenses:Groceries", pattern_type="substring")

    txn = Transaction(
        uuid="test0001",
        date="2024-03-15",
        payee="WHOLE FOODS MARKET",
        postings=[
            Posting(
                account_id=1,
                account_name="Assets:Chase:Checking",
                amount=Decimal("-75.00"),
                currency="USD",
            ),
            Posting(
                account_id=2,
                account_name="Expenses:Uncategorized",
                amount=Decimal("75.00"),
                currency="USD",
            ),
        ],
    )

    result = categorize_transactions(db, [txn])
    assert len(result) == 1

    categorized_posting = result[0].postings[1]
    assert categorized_posting.account_name == "Expenses:Groceries"

    unchanged_posting = result[0].postings[0]
    assert unchanged_posting.account_name == "Assets:Chase:Checking"
