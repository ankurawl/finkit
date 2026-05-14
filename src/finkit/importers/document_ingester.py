from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from finkit.config import Settings
from finkit.db import Database
from finkit.importers.archive import archive_file
from finkit.importers.document_classifier import classify_document, get_extraction_hints
from finkit.importers.file_importer import detect_format, extract_rows
from finkit.importers.pdf_extractor import extract_pdf


def ingest_document(
    db: Database,
    settings: Settings,
    file_path: str | Path,
    password: str | None = None,
    institution: str | None = None,
) -> dict:
    file_path = Path(file_path).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with db.transaction():
        source_file_id, is_new = archive_file(db, file_path, institution, settings)
        if not is_new:
            return {
                "source_file_id": source_file_id,
                "is_new": False,
                "message": "File already archived (duplicate SHA-256)",
            }

        ext = file_path.suffix.lower()
        file_type = {
            ".pdf": "pdf",
            ".csv": "csv",
            ".xlsx": "xlsx",
            ".xls": "xls",
            ".tsv": "tsv",
        }.get(ext, ext.lstrip(".") if ext else "unknown")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        text: str | None = None
        tables: list | None = None
        pages: int | None = None
        rows: list[dict] | None = None
        headers: list[str] | None = None
        row_count: int | None = None

        if file_type == "pdf":
            pdf_result = extract_pdf(file_path=file_path, password=password)
            text = pdf_result["text"]
            tables = pdf_result["tables"]
            pages = pdf_result["pages"]

            raw_data = json.dumps({"text": text[:10000], "pages": pages})
            db.execute(
                "INSERT INTO raw_extractions (source_file_id, row_index, raw_data, extraction_date) "
                "VALUES (?, ?, ?, ?)",
                (source_file_id, 0, raw_data, now),
            )

            classification_text = text
        else:
            rows = extract_rows(file_path)
            headers = list(rows[0].keys()) if rows else []
            row_count = len(rows)

            for i, row in enumerate(rows):
                raw_json = json.dumps(
                    {k: str(v) if v is not None else None for k, v in row.items()}
                )
                db.execute(
                    "INSERT INTO raw_extractions (source_file_id, row_index, raw_data, extraction_date) "
                    "VALUES (?, ?, ?, ?)",
                    (source_file_id, i, raw_json, now),
                )

            classification_text = " ".join(
                str(v) for row in rows for v in row.values() if v is not None
            )

    document_type, confidence = classify_document(classification_text, file_type)
    hints = get_extraction_hints(document_type)
    account_rows = db.fetchall("SELECT name FROM accounts ORDER BY name")

    return {
        "source_file_id": source_file_id,
        "is_new": True,
        "file_type": file_type,
        "document_type": document_type,
        "confidence": confidence,
        "institution": institution,
        "text": text,
        "tables": tables,
        "pages": pages,
        "rows": rows,
        "headers": headers,
        "row_count": row_count,
        "extraction_hints": hints,
        "existing_accounts": [r["name"] for r in account_rows],
    }
