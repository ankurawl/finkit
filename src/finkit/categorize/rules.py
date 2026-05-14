from __future__ import annotations

import re
from datetime import datetime, timezone

from finkit.db import Database
from finkit.models import CategorizationRule, Transaction


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_rule(row: dict) -> CategorizationRule:
    return CategorizationRule(
        id=row["id"],
        pattern=row["pattern"],
        pattern_type=row["pattern_type"],
        target_account=row["target_account"],
        institution=row["institution"],
        priority=row["priority"],
        created_at=row["created_at"],
    )


def load_rules(db: Database, institution: str | None = None) -> list[CategorizationRule]:
    if institution is not None:
        rows = db.fetchall(
            "SELECT * FROM categorization_rules WHERE institution = ? OR institution IS NULL "
            "ORDER BY priority DESC",
            (institution,),
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM categorization_rules ORDER BY priority DESC"
        )
    return [_row_to_rule(r) for r in rows]


def match_transaction(text: str, rules: list[CategorizationRule]) -> str | None:
    for rule in rules:
        if rule.pattern_type == "substring":
            if rule.pattern.lower() in text.lower():
                return rule.target_account
        elif rule.pattern_type == "regex":
            if re.search(rule.pattern, text):
                return rule.target_account
        elif rule.pattern_type == "exact":
            if rule.pattern.lower() == text.lower():
                return rule.target_account
    return None


def _is_uncategorized(account_name: str) -> bool:
    lower = account_name.lower()
    return "uncategorized" in lower or "unknown" in lower


def categorize_transactions(
    db: Database,
    transactions: list[Transaction],
    institution: str | None = None,
) -> list[Transaction]:
    rules = load_rules(db, institution)
    if not rules:
        return transactions

    for txn in transactions:
        text = txn.payee or txn.narration or ""
        if not text:
            continue
        for posting in txn.postings:
            if _is_uncategorized(posting.account_name):
                matched = match_transaction(text, rules)
                if matched is not None:
                    posting.account_name = matched
    return transactions


def add_rule(
    db: Database,
    pattern: str,
    target_account: str,
    pattern_type: str = "substring",
    institution: str | None = None,
    priority: int = 0,
) -> int:
    cursor = db.execute(
        "INSERT INTO categorization_rules (pattern, pattern_type, target_account, institution, priority, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pattern, pattern_type, target_account, institution, priority, _now_iso()),
    )
    db.conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def remove_rule(db: Database, rule_id: int) -> bool:
    cursor = db.execute(
        "DELETE FROM categorization_rules WHERE id = ?",
        (rule_id,),
    )
    db.conn.commit()
    return cursor.rowcount > 0


def list_rules(db: Database, institution: str | None = None) -> list[CategorizationRule]:
    return load_rules(db, institution)
