from __future__ import annotations

import re

from finkit.db import Database


def _match_payee(payee: str, pattern: str, pattern_type: str) -> bool:
    if not payee:
        return False
    if pattern_type == "substring":
        return pattern.lower() in payee.lower()
    elif pattern_type == "regex":
        return bool(re.search(pattern, payee))
    elif pattern_type == "exact":
        return pattern.lower() == payee.lower()
    return False


def find_matching_transactions(
    db: Database, pattern: str, pattern_type: str, old_account: str,
) -> list[dict]:
    old_row = db.fetchone(
        "SELECT id FROM accounts WHERE name = ?", (old_account,)
    )
    if old_row is None:
        raise ValueError(f"Account '{old_account}' not found")
    old_account_id = old_row["id"]

    rows = db.fetchall(
        """
        SELECT DISTINCT t.uuid, t.payee, t.date, p.id AS posting_id, p.amount
        FROM transactions t
        JOIN postings p ON p.transaction_id = t.id
        WHERE p.account_id = ?
        ORDER BY t.date
        """,
        (old_account_id,),
    )

    matches = []
    for row in rows:
        payee = row["payee"] or ""
        if _match_payee(payee, pattern, pattern_type):
            matches.append({
                "uuid": row["uuid"],
                "payee": row["payee"],
                "date": row["date"],
                "posting_id": row["posting_id"],
                "amount": row["amount"],
            })
    return matches
