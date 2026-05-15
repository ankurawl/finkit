from __future__ import annotations

import pytest

from finkit.config import Settings
from finkit.importers.template_engine import extract_with_template
from finkit.importers.template_store import (
    delete_template,
    find_matching_template,
    list_templates,
    load_template,
    save_template,
    update_last_used,
)
from finkit.models import DocumentTemplate
from finkit.operations import init_ledger


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def ledger_db(settings):
    db = init_ledger(settings)
    yield db
    db.close()


# ---------------------------------------------------------------------------
# Template store CRUD
# ---------------------------------------------------------------------------


def test_save_and_load_template(ledger_db):
    t = DocumentTemplate(
        name="test-payslip",
        institution="Meta",
        document_type="payslip",
        match_keywords=["Acme Corp", "Pay Date"],
        template_json={"mode": "field", "fields": []},
        account_mapping={"gross": {"account": "Income:Salary", "sign": "negative"}},
    )
    template_id = save_template(ledger_db, t)
    assert template_id is not None

    loaded = load_template(ledger_db, "test-payslip")
    assert loaded is not None
    assert loaded.name == "test-payslip"
    assert loaded.institution == "Meta"
    assert loaded.match_keywords == ["Acme Corp", "Pay Date"]
    assert loaded.template_json == {"mode": "field", "fields": []}
    assert loaded.account_mapping == {"gross": {"account": "Income:Salary", "sign": "negative"}}


def test_save_template_update(ledger_db):
    t1 = DocumentTemplate(
        name="test-update",
        document_type="payslip",
        match_keywords=["v1"],
        template_json={"mode": "field", "fields": []},
    )
    id1 = save_template(ledger_db, t1)

    t2 = DocumentTemplate(
        name="test-update",
        document_type="bank_statement",
        match_keywords=["v2"],
        template_json={"mode": "table", "sections": []},
    )
    id2 = save_template(ledger_db, t2)
    assert id1 == id2

    loaded = load_template(ledger_db, "test-update")
    assert loaded.document_type == "bank_statement"
    assert loaded.match_keywords == ["v2"]


def test_list_templates(ledger_db):
    save_template(ledger_db, DocumentTemplate(
        name="t1", institution="Meta", document_type="payslip",
        match_keywords=["k1"], template_json={},
    ))
    save_template(ledger_db, DocumentTemplate(
        name="t2", institution="Chase", document_type="statement",
        match_keywords=["k2"], template_json={},
    ))

    all_templates = list_templates(ledger_db)
    assert len(all_templates) == 2

    meta_templates = list_templates(ledger_db, institution="Meta")
    assert len(meta_templates) == 1
    assert meta_templates[0].name == "t1"


def test_delete_template(ledger_db):
    save_template(ledger_db, DocumentTemplate(
        name="to-delete", document_type="test",
        match_keywords=["x"], template_json={},
    ))
    assert delete_template(ledger_db, "to-delete") is True
    assert load_template(ledger_db, "to-delete") is None
    assert delete_template(ledger_db, "nonexistent") is False


def test_find_matching_template(ledger_db):
    save_template(ledger_db, DocumentTemplate(
        name="meta-payslip", document_type="payslip",
        match_keywords=["Acme Corp", "Pay Date", "Gross Pay"],
        template_json={},
    ))
    save_template(ledger_db, DocumentTemplate(
        name="chase-statement", document_type="statement",
        match_keywords=["Chase", "Account Summary"],
        template_json={},
    ))

    text = "Acme Corp Inc\nPay Date: 01/15/2024\nGross Pay: $10,000"
    matched = find_matching_template(ledger_db, text)
    assert matched is not None
    assert matched.name == "meta-payslip"

    text2 = "Chase Bank\nAccount Summary\nChecking Account"
    matched2 = find_matching_template(ledger_db, text2)
    assert matched2 is not None
    assert matched2.name == "chase-statement"

    text3 = "Completely unrelated document text"
    assert find_matching_template(ledger_db, text3) is None


def test_find_matching_template_conflict_resolution(ledger_db):
    save_template(ledger_db, DocumentTemplate(
        name="generic", document_type="statement",
        match_keywords=["Bank"],
        template_json={},
    ))
    save_template(ledger_db, DocumentTemplate(
        name="specific", document_type="statement",
        match_keywords=["Bank", "Account Number", "Routing"],
        template_json={},
    ))

    text = "Bank Statement\nAccount Number: 123\nRouting: 456"
    matched = find_matching_template(ledger_db, text)
    assert matched.name == "specific"


def test_update_last_used(ledger_db):
    t = DocumentTemplate(
        name="track-usage", document_type="test",
        match_keywords=["x"], template_json={},
    )
    tid = save_template(ledger_db, t)

    loaded = load_template(ledger_db, "track-usage")
    assert loaded.use_count == 0

    update_last_used(ledger_db, tid)
    loaded = load_template(ledger_db, "track-usage")
    assert loaded.use_count == 1
    assert loaded.last_used_at is not None


# ---------------------------------------------------------------------------
# extract_with_template (pure function tests)
# ---------------------------------------------------------------------------


def test_extract_field_mode():
    template = DocumentTemplate(
        name="test",
        document_type="payslip",
        match_keywords=[],
        template_json={
            "mode": "field",
            "fields": [
                {"name": "gross_pay", "pattern": r"Gross Pay[:\s]*\$?([\d,]+\.\d{2})", "type": "amount", "required": True},
                {"name": "net_pay", "pattern": r"Net Pay[:\s]*\$?([\d,]+\.\d{2})", "type": "amount", "required": True},
                {"name": "federal_tax", "pattern": r"Federal Tax[:\s]*\$?([\d,]+\.\d{2})", "type": "amount"},
            ],
            "date_field": {"pattern": r"Pay Date[:\s]*(\d{2}/\d{2}/\d{4})", "format": "%m/%d/%Y"},
        },
    )

    text = """
    Acme Corp Inc
    Pay Date: 01/15/2024
    Gross Pay: $10,500.00
    Federal Tax: $2,100.00
    Net Pay: $7,350.00
    """

    result = extract_with_template(text, template)
    assert result["mode"] == "field"
    assert result["fields"]["gross_pay"] == "10500.00"
    assert result["fields"]["net_pay"] == "7350.00"
    assert result["fields"]["federal_tax"] == "2100.00"
    assert result["fields"]["_date"] == "2024-01-15"
    assert result["fields_extracted"] == 3
    assert result["confidence"] == 1.0


def test_extract_table_mode():
    template = DocumentTemplate(
        name="test",
        document_type="statement",
        match_keywords=[],
        template_json={
            "mode": "table",
            "sections": [{
                "name": "transactions",
                "start_pattern": r"^Date\s+Description\s+Amount",
                "end_pattern": r"^Total",
                "row_pattern": r"(\d{2}/\d{2})\s+(.+?)\s+(-?\d+\.\d{2})$",
                "fields": {
                    "date": {"group": 1},
                    "payee": {"group": 2},
                    "amount": {"group": 3},
                },
            }],
            "skip_patterns": ["PAYMENT THANK"],
        },
    )

    text = """Chase Bank Statement
Date        Description              Amount
01/15       WHOLE FOODS #123         -52.30
01/16       PAYMENT THANK YOU         500.00
01/17       AMAZON.COM               -29.99
Total                                417.71
"""

    result = extract_with_template(text, template)
    assert result["mode"] == "table"
    assert len(result["rows"]) == 2
    assert result["rows"][0]["payee"] == "WHOLE FOODS #123"
    assert result["rows"][0]["amount"] == "-52.30"
    assert result["rows"][1]["payee"] == "AMAZON.COM"


def test_extract_field_mode_partial():
    template = DocumentTemplate(
        name="test",
        document_type="payslip",
        match_keywords=[],
        template_json={
            "mode": "field",
            "fields": [
                {"name": "gross", "pattern": r"Gross[:\s]*\$?([\d.]+)", "type": "amount"},
                {"name": "tax", "pattern": r"Tax[:\s]*\$?([\d.]+)", "type": "amount"},
                {"name": "benefits", "pattern": r"Benefits[:\s]*\$?([\d.]+)", "type": "amount"},
            ],
        },
    )

    text = "Gross: $5000.00\nTax: $1000.00"

    result = extract_with_template(text, template)
    assert result["fields_extracted"] == 2
    assert result["fields_expected"] == 3
    assert result["confidence"] == pytest.approx(0.67, abs=0.01)


def test_confidence_levels():
    template = DocumentTemplate(
        name="test", document_type="test", match_keywords=[],
        template_json={
            "mode": "field",
            "fields": [
                {"name": "a", "pattern": r"A: (\d+)"},
            ],
        },
    )

    result = extract_with_template("A: 100", template)
    assert result["confidence"] == 1.0

    result = extract_with_template("No match here", template)
    assert result["confidence"] == 0.0


def test_year_inference():
    from finkit.importers.template_engine import _infer_year

    template = DocumentTemplate(
        name="test", document_type="statement", match_keywords=[],
        template_json={
            "year_inference": {"method": "filename_pattern", "pattern": r"(\d{4})"},
        },
    )

    assert _infer_year("/path/to/chase_2024_jan.pdf", template) == "2024"
    assert _infer_year("/path/to/statement.pdf", template) is None

    template_no_inference = DocumentTemplate(
        name="test2", document_type="test", match_keywords=[],
        template_json={},
    )
    assert _infer_year("/path/2024.pdf", template_no_inference) is None
