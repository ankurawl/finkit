from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finkit.config import Settings, load_settings
from finkit.db import Database
from finkit.importers.template_store import (
    find_matching_template,
    load_template,
    update_last_used,
)
from finkit.models import DocumentTemplate


def extract_with_template(text: str, template: DocumentTemplate) -> dict:
    tmpl = template.template_json
    mode = tmpl.get("mode", "field")

    if mode == "table":
        return _extract_table_mode(text, tmpl)
    elif mode == "field":
        return _extract_field_mode(text, tmpl)
    else:
        return {"error": f"Unknown template mode: {mode}", "fields_extracted": 0, "fields_expected": 0}


def _extract_table_mode(text: str, tmpl: dict) -> dict:
    sections = tmpl.get("sections", [])
    skip_patterns = tmpl.get("skip_patterns", [])
    all_rows = []
    fields_expected = 0
    fields_extracted = 0

    for section in sections:
        start_pat = section.get("start_pattern")
        end_pat = section.get("end_pattern")
        row_pattern = section.get("row_pattern")
        fields = section.get("fields", {})

        if not row_pattern:
            continue

        section_text = text
        if start_pat:
            m = re.search(start_pat, text, re.MULTILINE)
            if m:
                section_text = text[m.end():]
        if end_pat and section_text:
            m = re.search(end_pat, section_text, re.MULTILINE)
            if m:
                section_text = section_text[:m.start()]

        for line in section_text.split("\n"):
            line = line.strip()
            if not line:
                continue

            should_skip = False
            for sp in skip_patterns:
                if sp.lower() in line.lower():
                    should_skip = True
                    break
            if should_skip:
                continue

            match = re.search(row_pattern, line)
            if match:
                row_data = {}
                for field_name, field_spec in fields.items():
                    group = field_spec.get("group", field_name)
                    try:
                        val = match.group(group)
                        if val is not None:
                            row_data[field_name] = val.strip()
                            fields_extracted += 1
                    except (IndexError, KeyError):
                        pass
                    fields_expected += 1

                if row_data:
                    all_rows.append(row_data)

    total_expected = max(fields_expected, 1)
    confidence = fields_extracted / total_expected if total_expected > 0 else 0

    return {
        "mode": "table",
        "rows": all_rows,
        "fields_extracted": fields_extracted,
        "fields_expected": fields_expected,
        "confidence": round(confidence, 2),
    }


def _extract_field_mode(text: str, tmpl: dict) -> dict:
    fields = tmpl.get("fields", [])
    date_field = tmpl.get("date_field")

    extracted = {}
    fields_expected = len(fields)
    fields_extracted = 0

    for f in fields:
        name = f["name"]
        pattern = f["pattern"]
        field_type = f.get("type", "text")
        required = f.get("required", False)

        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if match:
            val = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
            val = val.strip()

            if field_type == "amount":
                val = val.replace(",", "").replace("$", "").replace("₹", "")
                try:
                    Decimal(val)
                except InvalidOperation:
                    if required:
                        continue

            extracted[name] = val
            fields_extracted += 1

    if date_field:
        date_pattern = date_field.get("pattern", "")
        date_format = date_field.get("format", "%m/%d/%Y")
        match = re.search(date_pattern, text, re.MULTILINE)
        if match:
            raw_date = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
            raw_date = raw_date.strip()
            try:
                parsed = datetime.strptime(raw_date, date_format)
                extracted["_date"] = parsed.strftime("%Y-%m-%d")
            except ValueError:
                extracted["_date_raw"] = raw_date

    confidence = fields_extracted / fields_expected if fields_expected > 0 else 0

    return {
        "mode": "field",
        "fields": extracted,
        "fields_extracted": fields_extracted,
        "fields_expected": fields_expected,
        "confidence": round(confidence, 2),
    }


def _build_transactions_from_table(
    extraction: dict, template: DocumentTemplate, year: str | None = None,
) -> list[dict]:
    mapping = template.account_mapping or {}
    transactions = []

    for row in extraction.get("rows", []):
        date_str = row.get("date", "")
        if date_str and year and len(date_str.split("/")) == 2:
            date_str = f"{date_str}/{year}"

        try:
            for fmt in ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m/%d"]:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    if fmt == "%m/%d" and year:
                        dt = dt.replace(year=int(year))
                    date_str = dt.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
        except Exception:
            continue

        payee = row.get("payee", "")
        amount_str = row.get("amount", "0")
        amount_str = amount_str.replace(",", "").replace("$", "")
        try:
            amount = Decimal(amount_str)
        except InvalidOperation:
            continue

        default_account = mapping.get("_default_account", {}).get("account", "Expenses:Uncategorized")

        if amount < 0:
            postings = [
                {"account": mapping.get("_bank_account", {}).get("account", "Assets:Uncategorized"),
                 "amount": str(amount), "currency": "USD"},
                {"account": default_account, "amount": str(-amount), "currency": "USD"},
            ]
        else:
            postings = [
                {"account": mapping.get("_bank_account", {}).get("account", "Assets:Uncategorized"),
                 "amount": str(amount), "currency": "USD"},
                {"account": mapping.get("_income_account", {}).get("account", "Income:Uncategorized"),
                 "amount": str(-amount), "currency": "USD"},
            ]

        transactions.append({
            "date": date_str,
            "payee": payee,
            "postings": postings,
        })

    return transactions


def _build_transactions_from_fields(
    extraction: dict, template: DocumentTemplate,
) -> list[dict]:
    mapping = template.account_mapping or {}
    fields = extraction.get("fields", {})
    date = fields.get("_date", fields.get("_date_raw", ""))

    postings = []
    for field_name, value in fields.items():
        if field_name.startswith("_"):
            continue
        if field_name not in mapping:
            continue

        acct_spec = mapping[field_name]
        account = acct_spec.get("account", "Expenses:Uncategorized")
        sign = acct_spec.get("sign", "positive")

        try:
            amount = Decimal(value.replace(",", "").replace("$", "").replace("₹", ""))
        except (InvalidOperation, AttributeError):
            continue

        if sign == "negative":
            amount = -abs(amount)
        else:
            amount = abs(amount)

        postings.append({
            "account": account,
            "amount": str(amount),
            "currency": acct_spec.get("currency", "USD"),
        })

    if not postings:
        return []

    return [{
        "date": date,
        "narration": f"Template: {template.name}",
        "postings": postings,
    }]


def _infer_year(file_path: str, template: DocumentTemplate) -> str | None:
    tmpl = template.template_json
    year_spec = tmpl.get("year_inference")
    if not year_spec:
        return None

    method = year_spec.get("method", "filename_pattern")
    pattern = year_spec.get("pattern", r"(\d{4})")

    if method == "filename_pattern":
        m = re.search(pattern, Path(file_path).name)
        if m:
            return m.group(1)
    return None


def apply_template(
    db: Database, file_path: str, template_name: str | None = None,
    password: str | None = None, dry_run: bool = True,
    settings: Settings | None = None,
) -> dict:
    if settings is None:
        settings = load_settings()

    from finkit.importers.document_ingester import ingest_document

    ingestion = ingest_document(db, settings=settings, file_path=file_path, password=password)
    if "error" in ingestion:
        return ingestion

    text = ingestion.get("extracted_text", "")
    source_file_id = ingestion.get("source_file_id")

    if template_name:
        template = load_template(db, template_name)
        if template is None:
            return {"error": f"Template '{template_name}' not found"}
    else:
        template = find_matching_template(db, text)
        if template is None:
            return {
                "error": "No matching template found",
                "source_file_id": source_file_id,
                "hint": "Use learn_template to create one, or specify template_name",
            }

    extraction = extract_with_template(text, template)
    mode = extraction.get("mode", "field")

    year = _infer_year(file_path, template)

    if mode == "table":
        transactions = _build_transactions_from_table(extraction, template, year)
    else:
        transactions = _build_transactions_from_fields(extraction, template)

    confidence = extraction.get("confidence", 0)
    confidence_label = "high" if confidence >= 0.9 else "medium" if confidence >= 0.7 else "low"

    result = {
        "template": template.name,
        "mode": mode,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "fields_extracted": extraction.get("fields_extracted", 0),
        "fields_expected": extraction.get("fields_expected", 0),
        "transaction_count": len(transactions),
        "source_file_id": source_file_id,
    }

    if dry_run:
        result["status"] = "dry_run"
        result["transactions"] = transactions
        return result

    if not transactions:
        result["status"] = "ok"
        result["message"] = "No transactions extracted"
        return result

    from finkit.operations import submit_transactions
    uuids = submit_transactions(db, transactions, source_file_id=source_file_id, settings=settings)

    if template.id is not None:
        update_last_used(db, template.id)

    result["status"] = "ok"
    result["uuids"] = uuids
    return result


def learn_template(
    db: Database, file_path: str, template_name: str,
    institution: str | None = None, password: str | None = None,
    settings: Settings | None = None,
) -> dict:
    if settings is None:
        settings = load_settings()

    from finkit.importers.document_ingester import ingest_document

    ingestion = ingest_document(
        db, settings=settings, file_path=file_path,
        password=password, institution=institution,
    )
    if "error" in ingestion:
        return ingestion

    text = ingestion.get("extracted_text", "")
    doc_type = ingestion.get("classification", {}).get("document_type", "unknown")
    source_file_id = ingestion.get("source_file_id")

    return {
        "status": "ready_for_template",
        "template_name": template_name,
        "institution": institution,
        "document_type": doc_type,
        "source_file_id": source_file_id,
        "text_preview": text[:3000],
        "text_length": len(text),
        "instructions": (
            "Examine the text above and create a template by calling "
            "save_document_template() with:\n"
            "- match_keywords: distinctive phrases that identify this document type\n"
            "- template_json: regex patterns to extract data\n"
            "- account_mapping: field-to-account mappings\n"
            f"Use mode='field' for single-transaction docs (payslips, tax forms) "
            f"or mode='table' for multi-transaction docs (bank/CC statements)."
        ),
    }
