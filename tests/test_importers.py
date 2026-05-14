from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from finkit.config import Settings
from finkit.db import Database
from finkit.importers.archive import archive_file, compute_sha256
from finkit.importers.file_importer import (
    apply_mapping,
    dedup_transactions,
    detect_format,
    extract_rows,
    import_file,
    save_column_mapping,
)
from finkit.importers.directory_importer import import_directory
from finkit.operations import init_ledger, open_account

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CHASE_MAPPING = {
    "date_col": "Posting Date",
    "payee_col": "Description",
    "amount_col": "Amount",
    "amount_sign": "negative_is_debit",
    "date_format": "%m/%d/%Y",
    "default_currency": "USD",
}

HDFC_MAPPING = {
    "date_col": "Date",
    "narration_col": "Narration",
    "amount_sign": "separate_columns",
    "debit_col": "Withdrawal Amt.",
    "credit_col": "Deposit Amt.",
    "date_format": "%d/%m/%Y",
    "default_currency": "INR",
}


# ---------------------------------------------------------------------------
# archive tests
# ---------------------------------------------------------------------------


class TestSha256Computation:
    def test_sha256_computation(self, chase_csv):
        h = compute_sha256(chase_csv)
        assert isinstance(h, str)
        assert len(h) == 64
        assert h == compute_sha256(chase_csv)


class TestArchiveCopiesFile:
    def test_archive_copies_file(self, ledger_db, chase_csv, settings):
        source_file_id, is_new = archive_file(
            ledger_db, chase_csv, institution="chase", settings=settings,
        )
        assert is_new is True
        assert source_file_id > 0

        row = ledger_db.fetchone(
            "SELECT * FROM source_files WHERE id = ?", (source_file_id,)
        )
        assert row is not None
        assert row["institution"] == "chase"
        assert row["file_type"] == "csv"
        assert row["original_filename"] == "chase_checking.csv"

        archived_path = settings.statements_dir / row["path"]
        assert archived_path.exists()

        assert chase_csv.exists()


class TestArchiveDedup:
    def test_archive_dedup(self, ledger_db, chase_csv, settings):
        id1, new1 = archive_file(
            ledger_db, chase_csv, institution="chase", settings=settings,
        )
        id2, new2 = archive_file(
            ledger_db, chase_csv, institution="chase", settings=settings,
        )
        assert new1 is True
        assert new2 is False
        assert id1 == id2


# ---------------------------------------------------------------------------
# detect / extract tests
# ---------------------------------------------------------------------------


class TestDetectCsvFormat:
    def test_detect_csv_format(self, chase_csv):
        fmt = detect_format(chase_csv)
        assert fmt["type"] == "csv"
        assert fmt["delimiter"] == ","
        assert "encoding" in fmt


class TestExtractCsvRows:
    def test_extract_csv_rows(self, chase_csv):
        rows = extract_rows(chase_csv)
        assert len(rows) == 8
        first = rows[0]
        assert "Posting Date" in first
        assert "Description" in first
        assert "Amount" in first

    def test_extract_hdfc_rows(self, hdfc_csv):
        rows = extract_rows(hdfc_csv)
        assert len(rows) == 6
        assert "Date" in rows[0]
        assert "Narration" in rows[0]
        assert "Withdrawal Amt." in rows[0]
        assert "Deposit Amt." in rows[0]


# ---------------------------------------------------------------------------
# apply_mapping tests
# ---------------------------------------------------------------------------


class TestApplyChaseMapping:
    def test_apply_chase_mapping(self, chase_csv):
        rows = extract_rows(chase_csv)
        transactions = apply_mapping(rows, CHASE_MAPPING, default_currency="USD")

        assert len(transactions) == 8

        amazon = transactions[0]
        assert amazon.date == "2024-01-15"
        assert amazon.payee == "AMAZON.COM"
        assert len(amazon.postings) == 2

        bank_posting = amazon.postings[0]
        assert bank_posting.amount == Decimal("-45.99")
        assert bank_posting.currency == "USD"

        counter_posting = amazon.postings[1]
        assert counter_posting.amount == Decimal("45.99")
        assert counter_posting.account_name == "Expenses:Uncategorized"

        payroll = transactions[2]
        assert payroll.payee == "DIRECT DEPOSIT PAYROLL"
        assert payroll.postings[0].amount == Decimal("5000.00")
        assert payroll.postings[1].account_name == "Income:Uncategorized"

    def test_apply_hdfc_mapping(self, hdfc_csv):
        rows = extract_rows(hdfc_csv)
        transactions = apply_mapping(rows, HDFC_MAPPING, default_currency="INR")

        assert len(transactions) == 6

        salary = transactions[0]
        assert salary.date == "2024-01-15"
        assert salary.postings[0].amount == Decimal("150000.00")
        assert salary.postings[0].currency == "INR"

        bigbasket = transactions[1]
        assert bigbasket.postings[0].amount == Decimal("-2500.00")
        assert bigbasket.postings[1].account_name == "Expenses:Uncategorized"


# ---------------------------------------------------------------------------
# import_file end-to-end
# ---------------------------------------------------------------------------


class TestImportFileEndToEnd:
    def test_import_file_end_to_end(self, ledger_db, chase_csv, settings):
        open_account(
            ledger_db, "Assets:Chase:Checking", "Assets",
            currency="USD", institution="chase",
        )
        open_account(
            ledger_db, "Expenses:Uncategorized", "Expenses", currency="USD",
        )
        open_account(
            ledger_db, "Income:Uncategorized", "Income", currency="USD",
        )
        ledger_db.conn.commit()

        save_column_mapping(ledger_db, "chase_checking", CHASE_MAPPING, institution="chase")
        ledger_db.conn.commit()

        result = import_file(
            ledger_db,
            file_path=chase_csv,
            account_name="Assets:Chase:Checking",
            mapping_name="chase_checking",
            institution="chase",
            settings=settings,
        )

        assert result["imported"] > 0
        assert result.get("duplicate_file") is not True

        txn_rows = ledger_db.fetchall("SELECT * FROM transactions")
        assert len(txn_rows) > 0

        posting_rows = ledger_db.fetchall("SELECT * FROM postings")
        assert len(posting_rows) > 0


class TestDedupOnReimport:
    def test_dedup_on_reimport(self, ledger_db, chase_csv, settings):
        open_account(
            ledger_db, "Assets:Chase:Checking", "Assets",
            currency="USD", institution="chase",
        )
        open_account(
            ledger_db, "Expenses:Uncategorized", "Expenses", currency="USD",
        )
        open_account(
            ledger_db, "Income:Uncategorized", "Income", currency="USD",
        )
        ledger_db.conn.commit()

        save_column_mapping(ledger_db, "chase_checking", CHASE_MAPPING, institution="chase")
        ledger_db.conn.commit()

        result1 = import_file(
            ledger_db,
            file_path=chase_csv,
            account_name="Assets:Chase:Checking",
            mapping_name="chase_checking",
            institution="chase",
            settings=settings,
        )

        result2 = import_file(
            ledger_db,
            file_path=chase_csv,
            account_name="Assets:Chase:Checking",
            mapping_name="chase_checking",
            institution="chase",
            settings=settings,
        )

        assert result2.get("duplicate_file") is True
        assert result2["imported"] == 0


# ---------------------------------------------------------------------------
# directory import
# ---------------------------------------------------------------------------


class TestImportDirectory:
    def test_import_directory(self, ledger_db, settings, tmp_path):
        open_account(
            ledger_db, "Assets:Chase:Checking", "Assets",
            currency="USD", institution="chase",
        )
        open_account(
            ledger_db, "Expenses:Uncategorized", "Expenses", currency="USD",
        )
        open_account(
            ledger_db, "Income:Uncategorized", "Income", currency="USD",
        )
        ledger_db.conn.commit()

        save_column_mapping(ledger_db, "chase_checking", CHASE_MAPPING, institution="chase")
        ledger_db.conn.commit()

        import_dir = tmp_path / "statements_to_import"
        import_dir.mkdir()

        src1 = FIXTURES_DIR / "chase_checking.csv"
        dest1 = import_dir / "chase_jan.csv"
        shutil.copy2(src1, dest1)

        dest2 = import_dir / "chase_feb.csv"
        with open(dest2, "w") as f:
            f.write("Posting Date,Description,Amount,Type,Balance\n")
            f.write("02/15/2024,GROCERY STORE,-55.00,Sale,-55.00\n")
            f.write("02/20/2024,PAYROLL DEPOSIT,4500.00,Credit,4445.00\n")

        result = import_directory(
            ledger_db,
            source_dir=import_dir,
            account_name="Assets:Chase:Checking",
            institution="chase",
            glob_pattern="*.csv",
            mapping_name="chase_checking",
            settings=settings,
        )

        assert result["imported_files"] == 2
        assert result["total_transactions"] > 0


# ---------------------------------------------------------------------------
# raw_extractions
# ---------------------------------------------------------------------------


class TestRawExtractionsPreserved:
    def test_raw_extractions_preserved(self, ledger_db, chase_csv, settings):
        open_account(
            ledger_db, "Assets:Chase:Checking", "Assets",
            currency="USD", institution="chase",
        )
        open_account(
            ledger_db, "Expenses:Uncategorized", "Expenses", currency="USD",
        )
        open_account(
            ledger_db, "Income:Uncategorized", "Income", currency="USD",
        )
        ledger_db.conn.commit()

        save_column_mapping(ledger_db, "chase_checking", CHASE_MAPPING, institution="chase")
        ledger_db.conn.commit()

        import_file(
            ledger_db,
            file_path=chase_csv,
            account_name="Assets:Chase:Checking",
            mapping_name="chase_checking",
            institution="chase",
            settings=settings,
        )

        raw_rows = ledger_db.fetchall("SELECT * FROM raw_extractions ORDER BY row_index")
        assert len(raw_rows) == 8

        first_raw = json.loads(raw_rows[0]["raw_data"])
        assert "Posting Date" in first_raw
        assert "Description" in first_raw
        assert "Amount" in first_raw
        assert first_raw["Description"] == "AMAZON.COM"
