from __future__ import annotations

import pytest

from finkit.categorize.payee_normalizer import (
    load_normalization_rules,
    manage_payee_rules,
    normalize_existing_payees,
    normalize_payee,
)
from finkit.config import Settings
from finkit.models import PayeeNormalizationRule
from finkit.operations import init_ledger, open_account, submit_transaction


@pytest.fixture
def settings(tmp_path):
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
    ledger_db.conn.commit()

    submit_transaction(
        ledger_db, date="2024-01-01",
        payee="ACH Deposit ACME 9876543210 PP - DIRECT DEP",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "-5000.00", "currency": "USD"},
        ],
    )
    submit_transaction(
        ledger_db, date="2024-01-15",
        payee="ACH Deposit ACME 9876543210 PP - PAYROLL",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "5000.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "-5000.00", "currency": "USD"},
        ],
    )
    submit_transaction(
        ledger_db, date="2024-01-20",
        payee="AMAZON.COM AMZN.COM/BILL",
        postings=[
            {"account": "Assets:Chase:Checking", "amount": "-50.00", "currency": "USD"},
            {"account": "Expenses:Uncategorized", "amount": "50.00", "currency": "USD"},
        ],
    )
    return ledger_db


def test_normalize_payee_substring():
    rules = [
        PayeeNormalizationRule(pattern="ACME 9876", canonical_name="Acme Corp"),
        PayeeNormalizationRule(pattern="AMAZON", canonical_name="Amazon"),
    ]
    assert normalize_payee("ACH Deposit ACME 9876543210 PP - DIRECT DEP", rules) == "Acme Corp"
    assert normalize_payee("AMAZON.COM AMZN.COM/BILL", rules) == "Amazon"
    assert normalize_payee("Whole Foods", rules) == "Whole Foods"


def test_normalize_payee_regex():
    rules = [
        PayeeNormalizationRule(pattern=r"ACME\s+\d+", pattern_type="regex", canonical_name="Acme Corp"),
    ]
    assert normalize_payee("ACH Deposit ACME 9876543210 PP", rules) == "Acme Corp"
    assert normalize_payee("No match", rules) == "No match"


def test_normalize_payee_exact():
    rules = [
        PayeeNormalizationRule(pattern="Whole Foods Market", pattern_type="exact", canonical_name="Whole Foods"),
    ]
    assert normalize_payee("Whole Foods Market", rules) == "Whole Foods"
    assert normalize_payee("Whole Foods Market #123", rules) == "Whole Foods Market #123"


def test_normalize_payee_priority():
    rules = [
        PayeeNormalizationRule(pattern="ACME", canonical_name="Acme Salary", priority=10),
        PayeeNormalizationRule(pattern="ACME", canonical_name="Acme (generic)", priority=5),
    ]
    assert normalize_payee("ACME 9876", rules) == "Acme Salary"


def test_manage_payee_rules_crud(seeded_db):
    result = manage_payee_rules(seeded_db, action="add", pattern="ACME", canonical_name="Acme Corp")
    assert result["status"] == "ok"
    rule_id = result["rule_id"]

    result = manage_payee_rules(seeded_db, action="list")
    assert len(result["rules"]) == 1
    assert result["rules"][0]["canonical_name"] == "Acme Corp"

    with pytest.raises(ValueError, match="Duplicate rule"):
        manage_payee_rules(seeded_db, action="add", pattern="ACME", canonical_name="Acme2")

    result = manage_payee_rules(seeded_db, action="remove", rule_id=rule_id)
    assert result["removed"] is True

    result = manage_payee_rules(seeded_db, action="list")
    assert len(result["rules"]) == 0


def test_normalize_existing_payees_dry_run(seeded_db):
    manage_payee_rules(seeded_db, action="add", pattern="ACME 9876", canonical_name="Acme Corp")

    result = normalize_existing_payees(seeded_db, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["count"] == 2

    rows = seeded_db.fetchall("SELECT normalized_payee FROM transactions WHERE normalized_payee IS NOT NULL")
    assert len(rows) == 0


def test_normalize_existing_payees_apply(seeded_db):
    manage_payee_rules(seeded_db, action="add", pattern="ACME 9876", canonical_name="Acme Corp")
    manage_payee_rules(seeded_db, action="add", pattern="AMAZON", canonical_name="Amazon")

    result = normalize_existing_payees(seeded_db, dry_run=False)
    assert result["status"] == "ok"
    assert result["updated"] == 3

    rows = seeded_db.fetchall(
        "SELECT payee, normalized_payee FROM transactions ORDER BY date"
    )
    assert rows[0]["payee"] == "ACH Deposit ACME 9876543210 PP - DIRECT DEP"
    assert rows[0]["normalized_payee"] == "Acme Corp"
    assert rows[2]["normalized_payee"] == "Amazon"


def test_load_normalization_rules(seeded_db):
    manage_payee_rules(seeded_db, action="add", pattern="ACME", canonical_name="Acme Corp", priority=10)
    manage_payee_rules(seeded_db, action="add", pattern="AMAZON", canonical_name="Amazon", priority=5)

    rules = load_normalization_rules(seeded_db)
    assert len(rules) == 2
    assert rules[0].canonical_name == "Acme Corp"
    assert rules[1].canonical_name == "Amazon"
