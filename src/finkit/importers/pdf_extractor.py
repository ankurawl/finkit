from __future__ import annotations

from pathlib import Path
from typing import Any


def _require_pdfplumber():
    try:
        import pdfplumber
        return pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber is required for PDF extraction. Install with: pip install pdfplumber"
        )


def extract_pdf(
    file_path: Path,
    password: str | None = None,
) -> dict[str, Any]:
    pdfplumber = _require_pdfplumber()

    open_kwargs: dict[str, Any] = {}
    if password:
        open_kwargs["password"] = password

    full_text_parts: list[str] = []
    all_tables: list[list[list[str | None]]] = []
    page_count = 0

    with pdfplumber.open(file_path, **open_kwargs) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text_parts.append(text)

            tables = page.extract_tables()
            if tables:
                all_tables.extend(tables)

    return {
        "text": "\n\n".join(full_text_parts),
        "tables": all_tables,
        "pages": page_count,
    }


def extract_tables_as_csv(
    file_path: Path,
    password: str | None = None,
) -> list[str]:
    result = extract_pdf(file_path, password)
    csv_strings: list[str] = []

    for table in result["tables"]:
        lines: list[str] = []
        for row in table:
            cells = [
                str(cell).replace(",", ";") if cell is not None else ""
                for cell in row
            ]
            lines.append(",".join(cells))
        csv_strings.append("\n".join(lines))

    return csv_strings


def extract_structured(
    file_path: Path,
    password: str | None = None,
) -> dict[str, Any]:
    pdfplumber = _require_pdfplumber()

    open_kwargs: dict[str, Any] = {}
    if password:
        open_kwargs["password"] = password

    text_by_page: list[str] = []
    tables_by_page: list[list[list[list[str | None]]]] = []
    metadata: dict[str, Any] = {}

    with pdfplumber.open(file_path, **open_kwargs) as pdf:
        metadata = {
            "pages": len(pdf.pages),
            "metadata": pdf.metadata or {},
        }

        for page in pdf.pages:
            text = page.extract_text()
            text_by_page.append(text or "")

            tables = page.extract_tables()
            tables_by_page.append(tables if tables else [])

    return {
        "text_by_page": text_by_page,
        "tables_by_page": tables_by_page,
        "metadata": metadata,
    }
