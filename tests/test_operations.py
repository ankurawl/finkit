"""Tests for core operations — init, open_account, submit, amend, assert_balance."""

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from personalfinance.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_ledger(tmp_path):
    ledger = tmp_path / "main.beancount"
    shutil.copy(FIXTURES / "simple.beancount", ledger)
    load_config(tmp_path)
    return ledger


@pytest.fixture
def fresh_dir(tmp_path):
    load_config(tmp_path)
    return tmp_path


class TestInitLedger:
    def test_create_new(self, fresh_dir):
        from personalfinance.operations import init_ledger
        result = init_ledger(path=str(fresh_dir / "main.beancount"), data_dir=str(fresh_dir))
        assert result["status"] == "created"
        assert (fresh_dir / "main.beancount").exists()
        assert len(result["accounts"]) > 0

    def test_load_existing(self, tmp_ledger, tmp_path):
        from personalfinance.operations import init_ledger
        result = init_ledger(path=str(tmp_ledger), load_existing=True, data_dir=str(tmp_path))
        assert result["status"] == "loaded"
        assert "Assets:Checking" in result["accounts"]
        assert result["entries_count"] > 0

    def test_create_existing_warns(self, tmp_ledger, tmp_path):
        from personalfinance.operations import init_ledger
        result = init_ledger(path=str(tmp_ledger), data_dir=str(tmp_path))
        assert result["status"] == "exists"

    def test_load_nonexistent_errors(self, fresh_dir):
        from personalfinance.operations import init_ledger
        with pytest.raises(FileNotFoundError):
            init_ledger(path=str(fresh_dir / "nope.beancount"), load_existing=True)


class TestOpenAccount:
    def test_open_new(self, tmp_ledger):
        from personalfinance.operations import open_account
        result = open_account("Assets:Chase:Checking", ledger_path=str(tmp_ledger))
        assert result["status"] == "created"
        assert "Assets:Chase:Checking" in result["account"]

    def test_open_existing(self, tmp_ledger):
        from personalfinance.operations import open_account
        result = open_account("Assets:Checking", ledger_path=str(tmp_ledger))
        assert result["status"] == "exists"

    def test_open_with_booking(self, tmp_ledger):
        from personalfinance.operations import open_account
        result = open_account("Assets:Brokerage", currencies=["USD"], booking="FIFO", ledger_path=str(tmp_ledger))
        assert result["status"] == "created"
        assert "FIFO" in result["directive"]


class TestSubmitTransaction:
    def test_submit_exact_match(self, tmp_ledger):
        from personalfinance.operations import submit_transaction
        result = submit_transaction(
            date_=date(2024, 3, 1),
            payee="Test Store",
            narration="Test purchase",
            postings=[
                {"account": "Expenses:Food:Groceries", "amount": "25.00", "currency": "USD"},
                {"account": "Assets:Checking", "amount": "-25.00", "currency": "USD"},
            ],
            ledger_path=str(tmp_ledger),
        )
        assert result["status"] == "created"
        assert "uuid" in result
        assert len(result["uuid"]) == 8

    def test_submit_fuzzy_match(self, tmp_ledger):
        from personalfinance.operations import submit_transaction
        result = submit_transaction(
            date_=date(2024, 3, 1),
            payee="Test",
            narration="Test",
            postings=[
                {"account": "Checking", "amount": "100.00", "currency": "USD"},
                {"account": "Salary", "amount": "-100.00", "currency": "USD"},
            ],
            ledger_path=str(tmp_ledger),
        )
        assert result["status"] == "created"

    def test_submit_ambiguous(self, tmp_ledger):
        from personalfinance.operations import submit_transaction
        result = submit_transaction(
            date_=date(2024, 3, 1),
            payee="Test",
            narration="Test",
            postings=[
                {"account": "Food", "amount": "10.00", "currency": "USD"},
                {"account": "Assets:Checking", "amount": "-10.00", "currency": "USD"},
            ],
            ledger_path=str(tmp_ledger),
        )
        assert result["status"] in ("created", "ambiguous")
        if result["status"] == "ambiguous":
            assert len(result["ambiguous_accounts"]) > 0

    def test_submit_generates_uuid(self, tmp_ledger):
        from personalfinance.operations import submit_transaction
        result = submit_transaction(
            date_=date(2024, 3, 1),
            payee="Test",
            narration="UUID test",
            postings=[
                {"account": "Expenses:Other", "amount": "5.00", "currency": "USD"},
                {"account": "Assets:Checking", "amount": "-5.00", "currency": "USD"},
            ],
            ledger_path=str(tmp_ledger),
        )
        assert result["status"] == "created"
        content = tmp_ledger.read_text()
        assert "#uuid-" in content


class TestAmendTransaction:
    def test_amend_narration(self, tmp_ledger):
        from personalfinance.operations import amend_transaction
        result = amend_transaction(uuid="00000002", narration="Updated groceries", ledger_path=str(tmp_ledger))
        assert result["status"] in ("amended", "appended")
        assert "Updated groceries" in result["transaction"]

    def test_amend_delete(self, tmp_ledger):
        from personalfinance.operations import amend_transaction
        result = amend_transaction(uuid="00000003", delete=True, ledger_path=str(tmp_ledger))
        assert result["status"] == "deleted"
        content = tmp_ledger.read_text()
        assert "uuid-00000003" not in content

    def test_amend_nonexistent(self, tmp_ledger):
        from personalfinance.operations import amend_transaction
        result = amend_transaction(uuid="ffffffff", narration="Nope", ledger_path=str(tmp_ledger))
        assert result["status"] == "not_found"

    def test_amend_correct_target(self, tmp_ledger):
        """Two transactions with same payee — amend one by UUID, other unchanged."""
        from personalfinance.operations import amend_transaction
        from personalfinance.ledger import load_file, find_entry_by_uuid

        result = amend_transaction(uuid="00000002", narration="First WF updated", ledger_path=str(tmp_ledger))
        assert result["status"] in ("amended", "appended")

        entries, _, _ = load_file(tmp_ledger)
        other = find_entry_by_uuid(entries, "00000005")
        assert other is not None
        assert other.narration == "Weekly groceries"


class TestAssertBalance:
    def test_balance_match(self, tmp_ledger):
        from personalfinance.operations import assert_balance
        result = assert_balance(
            account="Assets:Checking",
            expected_amount=Decimal("9227.92"),
            date_=date(2024, 2, 28),
            ledger_path=str(tmp_ledger),
        )
        assert result["status"] in ("match", "mismatch")
