from __future__ import annotations

import re
from datetime import datetime, timezone

from finkit.db import Database
from finkit.models import PayeeNormalizationRule


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_normalization_rules(db: Database) -> list[PayeeNormalizationRule]:
    rows = db.fetchall(
        "SELECT * FROM payee_normalization_rules ORDER BY priority DESC, id"
    )
    return [
        PayeeNormalizationRule(
            id=r["id"],
            pattern=r["pattern"],
            pattern_type=r["pattern_type"],
            canonical_name=r["canonical_name"],
            priority=r["priority"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def normalize_payee(raw_payee: str, rules: list[PayeeNormalizationRule]) -> str:
    if not raw_payee:
        return raw_payee
    for rule in rules:
        if rule.pattern_type == "substring":
            if rule.pattern.lower() in raw_payee.lower():
                return rule.canonical_name
        elif rule.pattern_type == "regex":
            if re.search(rule.pattern, raw_payee, re.IGNORECASE):
                return rule.canonical_name
        elif rule.pattern_type == "exact":
            if rule.pattern.lower() == raw_payee.lower():
                return rule.canonical_name
    return raw_payee


def manage_payee_rules(
    db: Database,
    action: str,
    pattern: str | None = None,
    canonical_name: str | None = None,
    pattern_type: str = "substring",
    priority: int = 0,
    rule_id: int | None = None,
) -> dict:
    if action == "add":
        if not pattern or not canonical_name:
            raise ValueError("pattern and canonical_name are required for add")
        existing = db.fetchone(
            "SELECT id FROM payee_normalization_rules WHERE pattern = ? AND pattern_type = ?",
            (pattern, pattern_type),
        )
        if existing:
            raise ValueError(
                f"Duplicate rule: pattern '{pattern}' with type '{pattern_type}' already exists (id={existing['id']})"
            )
        cursor = db.execute(
            "INSERT INTO payee_normalization_rules (pattern, pattern_type, canonical_name, priority, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (pattern, pattern_type, canonical_name, priority, _now_iso()),
        )
        db.conn.commit()
        return {"status": "ok", "rule_id": cursor.lastrowid}

    elif action == "remove":
        if rule_id is None:
            raise ValueError("rule_id is required for remove")
        cursor = db.execute(
            "DELETE FROM payee_normalization_rules WHERE id = ?", (rule_id,)
        )
        db.conn.commit()
        return {"status": "ok", "removed": cursor.rowcount > 0}

    elif action == "list":
        rules = load_normalization_rules(db)
        return {
            "status": "ok",
            "rules": [
                {
                    "id": r.id,
                    "pattern": r.pattern,
                    "pattern_type": r.pattern_type,
                    "canonical_name": r.canonical_name,
                    "priority": r.priority,
                }
                for r in rules
            ],
        }

    raise ValueError(f"Unknown action: {action}. Use add, remove, or list.")


def normalize_existing_payees(db: Database, dry_run: bool = True) -> dict:
    rules = load_normalization_rules(db)
    if not rules:
        return {"status": "ok", "updated": 0, "message": "No normalization rules defined"}

    rows = db.fetchall("SELECT id, payee FROM transactions WHERE payee IS NOT NULL")
    updates = []
    for row in rows:
        normalized = normalize_payee(row["payee"], rules)
        if normalized != row["payee"]:
            updates.append({"id": row["id"], "payee": row["payee"], "normalized_payee": normalized})

    if dry_run:
        return {"status": "dry_run", "count": len(updates), "updates": updates[:50]}

    with db.transaction():
        for u in updates:
            db.execute(
                "UPDATE transactions SET normalized_payee = ? WHERE id = ?",
                (u["normalized_payee"], u["id"]),
            )

    return {"status": "ok", "updated": len(updates)}
