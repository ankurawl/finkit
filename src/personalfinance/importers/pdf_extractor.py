"""PDF text and table extraction for bank/brokerage statements."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


def extract_pdf(
    file_path: str,
    password: str | None = None,
    passwords: list[str] | None = None,
) -> dict[str, Any]:
    """
    Extract text and tables from a PDF file.

    Supports password-protected PDFs (password used in-memory only, never stored).
    Returns structured content for LLM interpretation or CSV dump.
    """
    import pdfplumber

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    candidates = []
    if password:
        candidates.append(password)
    if passwords:
        candidates.extend(passwords)
    candidates.append(None)

    pdf = None
    used_password = None
    for pwd in candidates:
        try:
            pdf = pdfplumber.open(str(path), password=pwd)
            used_password = pwd
            break
        except Exception:
            continue

    if pdf is None:
        return {
            "status": "error",
            "message": "Could not open PDF. If password-protected, provide the correct password.",
        }

    try:
        result = _extract_content(pdf)
        result["status"] = "extracted"
        result["file"] = str(path)
        result["page_count"] = len(pdf.pages)
        result["password_protected"] = used_password is not None
        return result
    finally:
        pdf.close()


def _extract_content(pdf: Any) -> dict[str, Any]:
    """Extract text and tables from all pages."""
    all_text = []
    all_tables = []

    for i, page in enumerate(pdf.pages):
        page_num = i + 1

        text = page.extract_text()
        if text:
            all_text.append({"page": page_num, "text": text})

        tables = page.extract_tables()
        if tables:
            for j, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue

                headers = [str(cell).strip() if cell else "" for cell in table[0]]
                rows = []
                for row in table[1:]:
                    cells = [str(cell).strip() if cell else "" for cell in row]
                    if any(c for c in cells):
                        rows.append(cells)

                if rows:
                    all_tables.append({
                        "page": page_num,
                        "table_index": j,
                        "headers": headers,
                        "rows": rows,
                        "row_count": len(rows),
                    })

    csv_dumps = []
    for table in all_tables:
        lines = [",".join(f'"{h}"' for h in table["headers"])]
        for row in table["rows"]:
            lines.append(",".join(f'"{c}"' for c in row))
        csv_dumps.append({
            "page": table["page"],
            "csv": "\n".join(lines),
        })

    return {
        "text_pages": all_text,
        "tables": all_tables,
        "csv_dumps": csv_dumps,
        "text_page_count": len(all_text),
        "table_count": len(all_tables),
    }
