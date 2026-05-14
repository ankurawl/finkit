from __future__ import annotations

import pytest

from finkit.importers.document_ingester import ingest_document
from finkit.operations import open_account


class TestIngestCsv:
    def test_ingest_csv(self, ledger_db, chase_csv, settings):
        result = ingest_document(ledger_db, settings, chase_csv)

        assert result["is_new"] is True
        assert result["file_type"] == "csv"
        assert isinstance(result["rows"], list)
        assert len(result["rows"]) > 0
        assert isinstance(result["headers"], list)
        assert len(result["headers"]) > 0
        assert isinstance(result["source_file_id"], int)
        assert isinstance(result["existing_accounts"], list)
        assert isinstance(result["document_type"], str)
        assert isinstance(result["extraction_hints"], dict)


class TestIngestDuplicate:
    def test_ingest_duplicate(self, ledger_db, chase_csv, settings):
        first = ingest_document(ledger_db, settings, chase_csv)
        assert first["is_new"] is True

        second = ingest_document(ledger_db, settings, chase_csv)
        assert second["is_new"] is False
        assert "message" in second


class TestIngestNonexistentFile:
    def test_ingest_nonexistent_file(self, ledger_db, settings, tmp_path):
        fake = tmp_path / "does_not_exist.csv"
        with pytest.raises(FileNotFoundError):
            ingest_document(ledger_db, settings, fake)


class TestIngestStoresRawExtractions:
    def test_ingest_stores_raw_extractions(self, ledger_db, chase_csv, settings):
        result = ingest_document(ledger_db, settings, chase_csv)
        source_file_id = result["source_file_id"]

        raw_rows = ledger_db.fetchall(
            "SELECT * FROM raw_extractions WHERE source_file_id = ? ORDER BY row_index",
            (source_file_id,),
        )
        assert len(raw_rows) > 0
        assert raw_rows[0]["source_file_id"] == source_file_id


class TestIngestStoresSourceFile:
    def test_ingest_stores_source_file(self, ledger_db, chase_csv, settings):
        result = ingest_document(ledger_db, settings, chase_csv)
        source_file_id = result["source_file_id"]

        row = ledger_db.fetchone(
            "SELECT * FROM source_files WHERE id = ?", (source_file_id,)
        )
        assert row is not None
        assert row["file_type"] == "csv"
        assert row["sha256"] is not None
        assert len(row["sha256"]) == 64


class TestIngestReturnsExistingAccounts:
    def test_ingest_returns_existing_accounts(self, ledger_db, chase_csv, settings):
        open_account(
            ledger_db, "Assets:Chase:Checking", "Assets",
            currency="USD", institution="chase",
        )
        open_account(
            ledger_db, "Expenses:Groceries", "Expenses", currency="USD",
        )
        ledger_db.conn.commit()

        result = ingest_document(ledger_db, settings, chase_csv)

        assert "Assets:Chase:Checking" in result["existing_accounts"]
        assert "Expenses:Groceries" in result["existing_accounts"]


class TestIngestCsvHasNoPdfFields:
    def test_ingest_csv_has_no_pdf_fields(self, ledger_db, chase_csv, settings):
        result = ingest_document(ledger_db, settings, chase_csv)

        assert result["text"] is None
        assert result["tables"] is None
        assert result["pages"] is None
