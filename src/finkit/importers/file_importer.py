from __future__ import annotations

import csv
import io
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from finkit.categorize.rules import categorize_transactions
from finkit.config import Settings, load_settings
from finkit.db import Database
from finkit.importers.archive import archive_file
from finkit.matching import resolve_account
from finkit.models import Posting, Transaction
from finkit.summaries.registry import RefreshContext, SummaryRegistry


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gen_uuid() -> str:
    return uuid.uuid4().hex[:8]


def _normalize_payee(payee: str | None) -> str | None:
    if payee is None:
        return None
    return re.sub(r"\s+", " ", payee).strip()


def detect_format(file_path: Path) -> dict:
    ext = file_path.suffix.lower()
    result: dict[str, Any] = {"extension": ext, "type": "unknown"}

    if ext in (".xlsx", ".xls"):
        result["type"] = ext.lstrip(".")
        return result

    if ext in (".csv", ".tsv", ".txt"):
        result["type"] = "csv"
        try:
            with open(file_path, "r", newline="", errors="replace") as f:
                sample = f.read(8192)
            try:
                dialect = csv.Sniffer().sniff(sample)
                result["delimiter"] = dialect.delimiter
            except csv.Error:
                result["delimiter"] = "\t" if ext == ".tsv" else ","
            result["encoding"] = "utf-8"
        except OSError:
            result["delimiter"] = ","
            result["encoding"] = "utf-8"
        return result

    return result


def extract_rows(
    file_path: Path,
    mapping: dict | None = None,
) -> list[dict]:
    ext = file_path.suffix.lower()

    header_row = 0
    skip_footer = 0
    if mapping:
        header_row = mapping.get("header_row", 0)
        skip_footer = mapping.get("skip_footer_rows", 0)

    if ext in (".xlsx",):
        return _extract_xlsx(file_path, header_row, skip_footer)
    elif ext in (".xls",):
        return _extract_xls(file_path, header_row, skip_footer)
    else:
        return _extract_csv(file_path, header_row, skip_footer)


def _extract_csv(file_path: Path, header_row: int, skip_footer: int) -> list[dict]:
    fmt = detect_format(file_path)
    delimiter = fmt.get("delimiter", ",")
    encoding = fmt.get("encoding", "utf-8")

    with open(file_path, "r", newline="", encoding=encoding, errors="replace") as f:
        lines = f.readlines()

    if header_row > 0:
        lines = lines[header_row:]
    if skip_footer > 0:
        lines = lines[:-skip_footer] if skip_footer < len(lines) else []

    if not lines:
        return []

    reader = csv.DictReader(lines, delimiter=delimiter)
    return [dict(row) for row in reader]


def _extract_xlsx(file_path: Path, header_row: int, skip_footer: int) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            "openpyxl is required for XLSX files. Install with: pip install openpyxl"
        )

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        return []

    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if header_row >= len(all_rows):
        return []

    headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(all_rows[header_row])]
    data_rows = all_rows[header_row + 1:]

    if skip_footer > 0:
        data_rows = data_rows[:-skip_footer] if skip_footer < len(data_rows) else []

    result: list[dict] = []
    for row in data_rows:
        row_dict: dict[str, Any] = {}
        for i, val in enumerate(row):
            col_name = headers[i] if i < len(headers) else f"col_{i}"
            row_dict[col_name] = val
        if any(v is not None for v in row_dict.values()):
            result.append(row_dict)
    return result


def _extract_xls(file_path: Path, header_row: int, skip_footer: int) -> list[dict]:
    try:
        import xlrd
    except ImportError:
        raise ImportError(
            "xlrd is required for XLS files. Install with: pip install xlrd"
        )

    wb = xlrd.open_workbook(str(file_path))
    ws = wb.sheet_by_index(0)

    if header_row >= ws.nrows:
        return []

    headers = [str(ws.cell_value(header_row, c)) or f"col_{c}" for c in range(ws.ncols)]
    data_start = header_row + 1
    data_end = ws.nrows - skip_footer if skip_footer > 0 else ws.nrows

    result: list[dict] = []
    for r in range(data_start, data_end):
        row_dict: dict[str, Any] = {}
        for c in range(ws.ncols):
            col_name = headers[c] if c < len(headers) else f"col_{c}"
            row_dict[col_name] = ws.cell_value(r, c)
        result.append(row_dict)
    return result


def _parse_amount(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    s = s.replace(",", "").replace("$", "").replace("₹", "")
    s = s.strip("()")
    if s.startswith("(") or s.endswith(")"):
        s = "-" + s.strip("()")
    if not s or s == "-":
        return Decimal("0")
    return Decimal(s)


def _parse_date(value: Any, date_format: str | None = None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    s = str(value).strip()
    formats = [date_format] if date_format else []
    formats.extend([
        "%m/%d/%Y", "%m-%d-%Y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d/%m/%Y", "%d-%m-%Y",
        "%m/%d/%y", "%d/%m/%y",
    ])

    for fmt in formats:
        if fmt is None:
            continue
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date: {value}")


def apply_mapping(
    raw_rows: list[dict],
    mapping: dict,
    default_currency: str = "USD",
) -> list[Transaction]:
    date_col = mapping["date_col"]
    payee_col = mapping.get("payee_col")
    narration_col = mapping.get("narration_col")
    amount_col = mapping.get("amount_col")
    amount_sign = mapping.get("amount_sign", "negative_is_debit")
    date_format = mapping.get("date_format")
    currency_col = mapping.get("currency_col")
    map_currency = mapping.get("default_currency", default_currency)
    debit_col = mapping.get("debit_col")
    credit_col = mapping.get("credit_col")

    transactions: list[Transaction] = []

    for row in raw_rows:
        try:
            txn_date = _parse_date(row.get(date_col), date_format)
        except (ValueError, TypeError):
            continue

        payee = str(row.get(payee_col, "")).strip() if payee_col and row.get(payee_col) else None
        narration = str(row.get(narration_col, "")).strip() if narration_col and row.get(narration_col) else None

        currency = str(row.get(currency_col, "")).strip() if currency_col and row.get(currency_col) else map_currency

        try:
            if amount_sign == "separate_columns":
                debit_val = row.get(debit_col, "") if debit_col else ""
                credit_val = row.get(credit_col, "") if credit_col else ""
                debit_str = str(debit_val).strip() if debit_val else ""
                credit_str = str(credit_val).strip() if credit_val else ""

                if debit_str and debit_str not in ("", "0", "0.00"):
                    amount = -abs(_parse_amount(debit_str))
                elif credit_str and credit_str not in ("", "0", "0.00"):
                    amount = abs(_parse_amount(credit_str))
                else:
                    continue
            else:
                raw_amount = row.get(amount_col)
                if raw_amount is None or str(raw_amount).strip() == "":
                    continue
                amount = _parse_amount(raw_amount)
                if amount_sign == "positive_is_debit" and amount > 0:
                    amount = -amount
                elif amount_sign == "positive_is_debit" and amount < 0:
                    amount = abs(amount)
        except (InvalidOperation, ValueError):
            continue

        if amount == Decimal("0"):
            continue

        if amount < 0:
            counter_account = "Expenses:Uncategorized"
        else:
            counter_account = "Income:Uncategorized"

        bank_posting = Posting(
            amount=amount,
            currency=currency,
        )
        counter_posting = Posting(
            amount=-amount,
            currency=currency,
            account_name=counter_account,
        )

        txn = Transaction(
            uuid=_gen_uuid(),
            date=txn_date,
            payee=payee,
            narration=narration,
            status="cleared",
            created_at=_now_iso(),
            postings=[bank_posting, counter_posting],
        )
        transactions.append(txn)

    return transactions


def dedup_transactions(
    db: Database,
    transactions: list[Transaction],
    account_id: int,
    window_days: int = 3,
) -> list[Transaction]:
    if not transactions:
        return []

    new_txns: list[Transaction] = []
    for txn in transactions:
        amount = txn.postings[0].amount if txn.postings else Decimal("0")
        try:
            txn_date = datetime.strptime(txn.date, "%Y-%m-%d")
        except ValueError:
            new_txns.append(txn)
            continue

        start_date = (txn_date - timedelta(days=window_days)).strftime("%Y-%m-%d")
        end_date = (txn_date + timedelta(days=window_days)).strftime("%Y-%m-%d")

        candidates = db.fetchall(
            """
            SELECT t.id, t.payee, p.amount FROM transactions t
            JOIN postings p ON p.transaction_id = t.id
            WHERE p.account_id = ?
              AND t.date BETWEEN ? AND ?
              AND CAST(p.amount AS REAL) = CAST(? AS REAL)
            """,
            (account_id, start_date, end_date, str(amount)),
        )

        normalized_payee = _normalize_payee(txn.payee)
        is_dup = any(
            _normalize_payee(c["payee"]) == normalized_payee
            for c in candidates
        )
        if not is_dup:
            new_txns.append(txn)

    return new_txns


def save_column_mapping(
    db: Database,
    name: str,
    mapping: dict,
    institution: str | None = None,
) -> int:
    now = _now_iso()
    mapping_json = json.dumps(mapping)

    existing = db.fetchone(
        "SELECT id FROM column_mappings WHERE name = ?", (name,)
    )
    if existing is not None:
        db.execute(
            "UPDATE column_mappings SET mapping = ?, institution = ? WHERE id = ?",
            (mapping_json, institution, existing["id"]),
        )
        return existing["id"]

    cursor = db.execute(
        "INSERT INTO column_mappings (name, institution, mapping, created_at) VALUES (?, ?, ?, ?)",
        (name, institution, mapping_json, now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def load_column_mapping(db: Database, name: str) -> dict | None:
    row = db.fetchone(
        "SELECT mapping FROM column_mappings WHERE name = ?", (name,)
    )
    if row is None:
        return None
    return json.loads(row["mapping"])


def _ensure_account(db: Database, name: str) -> int:
    row = db.fetchone("SELECT id FROM accounts WHERE name = ?", (name,))
    if row is not None:
        return row["id"]

    parts = name.split(":")
    acct_type = parts[0] if parts else "Expenses"
    now = _now_iso()
    cursor = db.execute(
        "INSERT INTO accounts (name, type, currency, opened_at) VALUES (?, ?, ?, ?)",
        (name, acct_type, "USD", now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def import_file(
    db: Database,
    file_path: Path,
    account_name: str,
    mapping_name: str | None = None,
    institution: str | None = None,
    settings: Settings | None = None,
) -> dict:
    if settings is None:
        settings = load_settings()

    file_path = file_path.resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    is_pdf = file_path.suffix.lower() == ".pdf"

    mapping: dict | None = None
    if mapping_name:
        mapping = load_column_mapping(db, mapping_name)
        if mapping is None:
            raise ValueError(f"Column mapping '{mapping_name}' not found")

    with db.transaction():
        source_file_id, is_new = archive_file(db, file_path, institution, settings)
        if not is_new:
            return {"imported": 0, "skipped": 0, "total": 0, "duplicate_file": True}

        if is_pdf:
            from finkit.importers.pdf_extractor import extract_pdf
            from finkit.importers.pdf_parsers import PDF_STANDARD_MAPPING, parse_pdf_text

            pdf_result = extract_pdf(file_path=file_path)
            raw_rows = parse_pdf_text(
                pdf_result["text"],
                institution=institution,
                filename=file_path.name,
            )
            if mapping is None:
                mapping = PDF_STANDARD_MAPPING
        else:
            raw_rows = extract_rows(file_path, mapping)

        total = len(raw_rows)

        now = _now_iso()
        for i, row in enumerate(raw_rows):
            raw_json = json.dumps(
                {k: str(v) if v is not None else None for k, v in row.items()}
            )
            db.execute(
                "INSERT INTO raw_extractions (source_file_id, row_index, raw_data, extraction_date) "
                "VALUES (?, ?, ?, ?)",
                (source_file_id, i, raw_json, now),
            )

        if mapping is None:
            return {
                "imported": 0,
                "skipped": total,
                "total": total,
                "needs_mapping": True,
                "source_file_id": source_file_id,
            }

        transactions = apply_mapping(
            raw_rows, mapping, settings.default_currency
        )

        account_id = _ensure_account(db, account_name)

        for txn in transactions:
            txn.postings[0].account_name = account_name
            txn.postings[0].account_id = account_id

        transactions = categorize_transactions(db, transactions, institution)

        transactions = dedup_transactions(
            db, transactions, account_id, settings.dedup_window_days
        )

        imported = 0
        affected_dates: list[str] = []
        affected_account_ids: set[int] = {account_id}

        for txn in transactions:
            txn.source_file_id = source_file_id

            cursor = db.execute(
                "INSERT INTO transactions (uuid, date, payee, narration, status, source_file_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (txn.uuid, txn.date, txn.payee, txn.narration, txn.status, source_file_id, txn.created_at),
            )
            txn_id: int = cursor.lastrowid  # type: ignore[assignment]

            for posting in txn.postings:
                post_account_id = _ensure_account(db, posting.account_name)
                affected_account_ids.add(post_account_id)
                db.execute(
                    "INSERT INTO postings (transaction_id, account_id, amount, currency) "
                    "VALUES (?, ?, ?, ?)",
                    (txn_id, post_account_id, str(posting.amount), posting.currency),
                )

            affected_dates.append(txn.date)
            imported += 1

        if affected_dates:
            min_date = min(affected_dates)
            max_date = max(affected_dates)
            context = RefreshContext(
                affected_account_ids=affected_account_ids,
                affected_date_range=(min_date, max_date),
            )
            SummaryRegistry.refresh_all(db, context)

        skipped = total - imported
        return {
            "imported": imported,
            "skipped": skipped,
            "total": total,
            "source_file_id": source_file_id,
        }
