"""Tests for ledger operations — load, write, append, find_by_uuid, validate."""

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from personalfinance.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_ledger(tmp_path):
    """Copy simple.beancount to a temp dir and configure finkit to use it."""
    ledger = tmp_path / "main.beancount"
    shutil.copy(FIXTURES / "simple.beancount", ledger)
    load_config(tmp_path)
    return ledger


@pytest.fixture
def empty_ledger(tmp_path):
    ledger = tmp_path / "main.beancount"
    shutil.copy(FIXTURES / "empty.beancount", ledger)
    load_config(tmp_path)
    return ledger


class TestLoadFile:
    def test_load_simple(self, tmp_ledger):
        from personalfinance.ledger import load_file
        entries, errors, options = load_file(tmp_ledger)
        assert len(entries) > 0
        assert isinstance(options, dict)

    def test_load_nonexistent(self, tmp_path):
        from personalfinance.ledger import load_file
        with pytest.raises(FileNotFoundError):
            load_file(tmp_path / "nonexistent.beancount")

    def test_load_empty(self, empty_ledger):
        from personalfinance.ledger import load_file
        entries, errors, options = load_file(empty_ledger)
        assert len(entries) == 0


class TestGetAccounts:
    def test_discovers_accounts(self, tmp_ledger):
        from personalfinance.ledger import load_file, get_accounts
        entries, _, _ = load_file(tmp_ledger)
        accounts = get_accounts(entries)
        assert "Assets:Checking" in accounts
        assert "Expenses:Food:Groceries" in accounts
        assert len(accounts) == 9

    def test_empty_ledger_no_accounts(self, empty_ledger):
        from personalfinance.ledger import load_file, get_accounts
        entries, _, _ = load_file(empty_ledger)
        accounts = get_accounts(entries)
        assert accounts == []


class TestFindEntryByUuid:
    def test_find_existing(self, tmp_ledger):
        from personalfinance.ledger import load_file, find_entry_by_uuid
        entries, _, _ = load_file(tmp_ledger)
        entry = find_entry_by_uuid(entries, "00000002")
        assert entry is not None
        assert entry.payee == "Whole Foods"

    def test_find_nonexistent(self, tmp_ledger):
        from personalfinance.ledger import load_file, find_entry_by_uuid
        entries, _, _ = load_file(tmp_ledger)
        entry = find_entry_by_uuid(entries, "ffffffff")
        assert entry is None


class TestAppendText:
    def test_append(self, tmp_ledger):
        from personalfinance.ledger import append_text
        original_size = tmp_ledger.stat().st_size
        append_text(tmp_ledger, "2024-03-01 open Assets:NewAccount USD")
        assert tmp_ledger.stat().st_size > original_size
        assert "Assets:NewAccount" in tmp_ledger.read_text()


class TestFormatDirectives:
    def test_format_open(self):
        from personalfinance.ledger import format_open_directive
        result = format_open_directive("Assets:Test", date(2024, 1, 1), ["USD"], "FIFO")
        assert '2024-01-01 open Assets:Test USD "FIFO"' == result

    def test_format_transaction(self, tmp_ledger):
        from personalfinance.ledger import format_transaction
        result = format_transaction(
            date_=date(2024, 3, 1),
            payee="Test",
            narration="Test transaction",
            postings=[
                {"account": "Expenses:Food:Groceries", "amount": "50.00", "currency": "USD"},
                {"account": "Assets:Checking", "amount": "-50.00", "currency": "USD"},
            ],
            tags={"uuid-test1234"},
        )
        assert "2024-03-01" in result
        assert "Test" in result
        assert "#uuid-test1234" in result
        assert "50.00 USD" in result

    def test_format_balance(self, tmp_ledger):
        from personalfinance.ledger import format_balance_directive
        result = format_balance_directive("Assets:Checking", date(2024, 1, 31), Decimal("5000.00"), "USD")
        assert "2024-01-31 balance Assets:Checking" in result

    def test_format_price(self):
        from personalfinance.ledger import format_price_directive
        result = format_price_directive(date(2024, 1, 1), "AAPL", Decimal("150.00"), "USD")
        assert "2024-01-01 price AAPL  150.00 USD" == result


class TestRemoveEntry:
    def test_remove_by_uuid(self, tmp_ledger):
        from personalfinance.ledger import load_file, find_entry_by_uuid, remove_entry_text
        entries, _, _ = load_file(tmp_ledger)
        entry = find_entry_by_uuid(entries, "00000003")
        assert entry is not None
        success = remove_entry_text(tmp_ledger, entry)
        assert success
        content = tmp_ledger.read_text()
        assert "uuid-00000003" not in content
        assert "uuid-00000002" in content
