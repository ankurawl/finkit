from __future__ import annotations

from finkit.db import Database
from finkit.engine.validation import AccountNotFoundError


def _levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if not s2:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insert = prev_row[j + 1] + 1
            delete = curr_row[j] + 1
            substitute = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(insert, delete, substitute))
        prev_row = curr_row

    return prev_row[-1]


def _similarity_score(s1: str, s2: str) -> float:
    if not s1 and not s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    return 1.0 - (_levenshtein_distance(s1, s2) / max_len)


def match_account(
    db: Database, query: str, threshold: float = 0.85, top_n: int = 5
) -> list[tuple[str, float]]:
    rows = db.fetchall("SELECT name FROM accounts")
    if not rows:
        return []

    query_lower = query.lower()
    scored: list[tuple[str, float]] = []

    for row in rows:
        name: str = row["name"]
        name_lower = name.lower()

        if name_lower == query_lower:
            scored.append((name, 1.0))
            continue

        if name_lower.startswith(query_lower):
            scored.append((name, 0.95))
            continue

        segments = name_lower.split(":")
        if any(query_lower in seg for seg in segments):
            scored.append((name, 0.90))
            continue

        score = _similarity_score(query_lower, name_lower)
        if score >= threshold:
            scored.append((name, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]


def resolve_account(db: Database, name_or_query: str) -> int:
    row = db.fetchone("SELECT id FROM accounts WHERE name = ?", (name_or_query,))
    if row is not None:
        return row["id"]

    matches = match_account(db, name_or_query)
    if not matches:
        raise AccountNotFoundError(f"No account matching '{name_or_query}'")

    best_name, _ = matches[0]
    row = db.fetchone("SELECT id FROM accounts WHERE name = ?", (best_name,))
    if row is None:
        raise AccountNotFoundError(f"No account matching '{name_or_query}'")
    return row["id"]
