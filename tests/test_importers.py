"""Tests for file importers — CSV auto-detect, deduplication, saved mappings, PDF extraction."""

import json
import shutil
from pathlib import Path

import pytest

from personalfinance.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_env(tmp_path):
    ledger = tmp_path / "main.beancount"
    shutil.copy(FIXTURES / "simple.beancount", ledger)
    load_config(tmp_path)
    return tmp_path


class TestCSVAutoDetect:
    def test_detect_chase_columns(self, tmp_env):
        from personalfinance.importers.file_importer import import_file
        result = import_file(
            file_path=str(FIXTURES / "sample_chase.csv"),
            account="Assets:Checking",
        )
        assert result["status"] == "mapping_proposed"
        mapping = result["detected_mapping"]
        assert "date_col" in mapping
        assert "amount_col" in mapping or ("debit_col" in mapping and "credit_col" in mapping)
        assert mapping["date_col"] == "Posting Date"
        assert result["row_count"] == 7

    def test_detect_shows_sample_rows(self, tmp_env):
        from personalfinance.importers.file_importer import import_file
        result = import_file(
            file_path=str(FIXTURES / "sample_chase.csv"),
            account="Assets:Checking",
        )
        assert len(result["sample_rows"]) <= 3
        assert "Posting Date" in result["headers"]


class TestCSVImport:
    def test_import_with_mapping(self, tmp_env):
        from personalfinance.importers.file_importer import import_file
        mapping = {
            "date_col": "Posting Date",
            "amount_col": "Amount",
            "payee_col": "Description",
            "date_format": "%m/%d/%Y",
        }
        result = import_file(
            file_path=str(FIXTURES / "sample_chase.csv"),
            account="Assets:Checking",
            confirm_mapping=mapping,
            ledger_path=str(tmp_env / "main.beancount"),
        )
        assert result["status"] == "imported"
        assert result["imported_count"] > 0

    def test_deduplication(self, tmp_env):
        from personalfinance.importers.file_importer import import_file
        mapping = {
            "date_col": "Posting Date",
            "amount_col": "Amount",
            "payee_col": "Description",
            "date_format": "%m/%d/%Y",
        }
        result1 = import_file(
            file_path=str(FIXTURES / "sample_chase.csv"),
            account="Assets:Checking",
            confirm_mapping=mapping,
            ledger_path=str(tmp_env / "main.beancount"),
        )
        first_count = result1["imported_count"]

        result2 = import_file(
            file_path=str(FIXTURES / "sample_chase.csv"),
            account="Assets:Checking",
            confirm_mapping=mapping,
            ledger_path=str(tmp_env / "main.beancount"),
        )
        assert result2["duplicate_count"] >= first_count

    def test_saved_mapping(self, tmp_env):
        from personalfinance.importers.file_importer import import_file
        mapping = {
            "date_col": "Posting Date",
            "amount_col": "Amount",
            "payee_col": "Description",
            "date_format": "%m/%d/%Y",
            "save_as": "chase_checking",
        }
        import_file(
            file_path=str(FIXTURES / "sample_chase.csv"),
            account="Assets:Checking",
            confirm_mapping=mapping,
            ledger_path=str(tmp_env / "main.beancount"),
        )
        mapping_file = tmp_env / "mappings" / "chase_checking.json"
        assert mapping_file.exists()
        saved = json.loads(mapping_file.read_text())
        assert saved["date_col"] == "Posting Date"


class TestFileNotFound:
    def test_missing_file(self, tmp_env):
        from personalfinance.importers.file_importer import import_file
        with pytest.raises(FileNotFoundError):
            import_file(file_path="/nonexistent/file.csv", account="Assets:Checking")


class TestPDFExtractor:
    def test_missing_pdf(self):
        from personalfinance.importers.pdf_extractor import extract_pdf
        with pytest.raises(FileNotFoundError):
            extract_pdf(file_path="/nonexistent/statement.pdf")
