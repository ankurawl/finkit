from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from finkit.config import Settings, load_settings
from finkit.db import Database
from finkit.importers.file_importer import import_file

logger = logging.getLogger(__name__)


def import_directory(
    db: Database,
    source_dir: Path,
    account_name: str,
    institution: str | None = None,
    glob_pattern: str = "*.csv",
    recursive: bool = True,
    mapping_name: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if settings is None:
        settings = load_settings()

    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {source_dir}")

    if recursive:
        files = sorted(source_dir.rglob(glob_pattern))
    else:
        files = sorted(source_dir.glob(glob_pattern))

    imported_files = 0
    skipped_files = 0
    total_transactions = 0
    errors: list[dict[str, Any]] = []

    for file_path in files:
        if not file_path.is_file():
            continue

        try:
            result = import_file(
                db=db,
                file_path=file_path,
                account_name=account_name,
                mapping_name=mapping_name,
                institution=institution,
                settings=settings,
            )

            if result.get("duplicate_file"):
                skipped_files += 1
            else:
                imported_files += 1
                total_transactions += result.get("imported", 0)

        except Exception as exc:
            skipped_files += 1
            errors.append({
                "file": str(file_path),
                "error": str(exc),
            })
            logger.warning("Failed to import %s: %s", file_path, exc)

    return {
        "imported_files": imported_files,
        "skipped_files": skipped_files,
        "total_transactions": total_transactions,
        "errors": errors,
    }
