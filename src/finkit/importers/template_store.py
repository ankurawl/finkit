from __future__ import annotations

import json
from datetime import datetime, timezone

from finkit.db import Database
from finkit.models import DocumentTemplate


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_template(db: Database, template: DocumentTemplate) -> int:
    now = _now_iso()
    keywords_json = json.dumps(template.match_keywords)
    template_json = json.dumps(template.template_json)
    mapping_json = json.dumps(template.account_mapping) if template.account_mapping else None

    existing = db.fetchone(
        "SELECT id FROM document_templates WHERE name = ?", (template.name,)
    )
    if existing:
        db.execute(
            """UPDATE document_templates
               SET institution = ?, document_type = ?, match_keywords = ?,
                   template_json = ?, account_mapping = ?
               WHERE id = ?""",
            (template.institution, template.document_type, keywords_json,
             template_json, mapping_json, existing["id"]),
        )
        db.conn.commit()
        return existing["id"]

    cursor = db.execute(
        """INSERT INTO document_templates
           (name, institution, document_type, match_keywords, template_json,
            account_mapping, created_at, use_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (template.name, template.institution, template.document_type,
         keywords_json, template_json, mapping_json, now),
    )
    db.conn.commit()
    return cursor.lastrowid


def _row_to_template(row: dict) -> DocumentTemplate:
    return DocumentTemplate(
        id=row["id"],
        name=row["name"],
        institution=row["institution"],
        document_type=row["document_type"],
        match_keywords=json.loads(row["match_keywords"]),
        template_json=json.loads(row["template_json"]),
        account_mapping=json.loads(row["account_mapping"]) if row["account_mapping"] else None,
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        use_count=row["use_count"],
    )


def load_template(db: Database, name: str) -> DocumentTemplate | None:
    row = db.fetchone("SELECT * FROM document_templates WHERE name = ?", (name,))
    if row is None:
        return None
    return _row_to_template(row)


def list_templates(db: Database, institution: str | None = None) -> list[DocumentTemplate]:
    if institution:
        rows = db.fetchall(
            "SELECT * FROM document_templates WHERE institution = ? ORDER BY name",
            (institution,),
        )
    else:
        rows = db.fetchall("SELECT * FROM document_templates ORDER BY name")
    return [_row_to_template(r) for r in rows]


def delete_template(db: Database, name: str) -> bool:
    cursor = db.execute("DELETE FROM document_templates WHERE name = ?", (name,))
    db.conn.commit()
    return cursor.rowcount > 0


def find_matching_template(db: Database, text: str) -> DocumentTemplate | None:
    rows = db.fetchall("SELECT * FROM document_templates")
    if not rows:
        return None

    text_lower = text.lower()
    best_template = None
    best_score = (0, 0)

    for row in rows:
        keywords = json.loads(row["match_keywords"])
        match_count = sum(1 for kw in keywords if kw.lower() in text_lower)
        if match_count == 0:
            continue

        score = (match_count, row["use_count"] or 0)
        if score > best_score:
            best_score = score
            best_template = row

    if best_template is None:
        return None
    return _row_to_template(best_template)


def update_last_used(db: Database, template_id: int) -> None:
    now = _now_iso()
    db.execute(
        "UPDATE document_templates SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
        (now, template_id),
    )
    db.conn.commit()
