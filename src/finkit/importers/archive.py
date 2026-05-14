from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from finkit.config import Settings, load_settings
from finkit.db import Database
from finkit.models import SourceFile


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def determine_year(file_path: Path) -> str:
    date_pattern = re.compile(
        r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})"
        r"|(\d{1,2}[-/]\d{1,2}[-/]\d{4})"
    )
    date_formats = [
        "%Y-%m-%d", "%Y/%m/%d",
        "%m-%d-%Y", "%m/%d/%Y",
        "%d-%m-%Y", "%d/%m/%Y",
    ]

    try:
        with open(file_path, "r", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= 50:
                    break
                for match in date_pattern.finditer(line):
                    text = match.group(0)
                    for fmt in date_formats:
                        try:
                            dt = datetime.strptime(text, fmt)
                            if 1990 <= dt.year <= 2100:
                                return str(dt.year)
                        except ValueError:
                            continue
    except (OSError, UnicodeDecodeError):
        pass

    mtime = file_path.stat().st_mtime
    return str(datetime.fromtimestamp(mtime, tz=timezone.utc).year)


def _file_type_from_extension(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    type_map = {
        ".csv": "csv",
        ".xlsx": "xlsx",
        ".xls": "xls",
        ".pdf": "pdf",
        ".ofx": "ofx",
        ".qfx": "qfx",
        ".json": "json",
        ".tsv": "tsv",
    }
    return type_map.get(ext, ext.lstrip(".") if ext else "unknown")


def archive_file(
    db: Database,
    file_path: Path,
    institution: str | None = None,
    settings: Settings | None = None,
) -> tuple[int, bool]:
    if settings is None:
        settings = load_settings()

    file_path = file_path.resolve()
    sha256 = compute_sha256(file_path)

    existing = db.fetchone(
        "SELECT id FROM source_files WHERE sha256 = ?", (sha256,)
    )
    if existing is not None:
        return (existing["id"], False)

    year = determine_year(file_path)
    statements_dir = settings.statements_dir
    year_dir = statements_dir / year
    year_dir.mkdir(parents=True, exist_ok=True)

    dest = year_dir / file_path.name
    if dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        dest = year_dir / f"{stem}_{sha256[:8]}{suffix}"

    shutil.copy2(file_path, dest)

    rel_path = dest.relative_to(statements_dir)

    now = _now_iso()
    cursor = db.execute(
        "INSERT INTO source_files (path, original_path, sha256, institution, file_type, imported_at, original_filename) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            str(rel_path),
            str(file_path),
            sha256,
            institution,
            _file_type_from_extension(file_path),
            now,
            file_path.name,
        ),
    )
    source_file_id: int = cursor.lastrowid  # type: ignore[assignment]
    return (source_file_id, True)
