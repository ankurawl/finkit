from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj: object) -> object:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def export_csv(data: list[dict], file_path: Path | None = None) -> str:
    if not data:
        return ""

    output = io.StringIO()
    fieldnames = list(data[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in data:
        writer.writerow({k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()})

    csv_str = output.getvalue()

    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(csv_str, encoding="utf-8")
        return str(file_path)

    return csv_str


def export_json(
    data: list[dict] | dict,
    file_path: Path | None = None,
    indent: int = 2,
) -> str:
    json_str = json.dumps(data, cls=_DecimalEncoder, indent=indent)

    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json_str, encoding="utf-8")
        return str(file_path)

    return json_str
