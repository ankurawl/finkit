"""Fuzzy account matching with confidence scoring and threshold gate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MatchResult:
    account: str
    score: float
    method: str  # exact, prefix, substring, edit_distance


CONFIDENCE_THRESHOLD = 0.85


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(b)]


def match_account(query: str, accounts: list[str], top_n: int = 3) -> list[MatchResult]:
    """
    Match a query string against a list of account names.

    Matching priority: exact > prefix > substring > edit distance.
    Returns up to top_n results sorted by score (highest first).
    """
    if not accounts:
        return []

    query_lower = query.lower()
    results: list[MatchResult] = []

    for account in accounts:
        account_lower = account.lower()

        if account_lower == query_lower:
            results.append(MatchResult(account=account, score=1.0, method="exact"))
            continue

        parts = account_lower.split(":")
        if any(part == query_lower for part in parts):
            results.append(MatchResult(account=account, score=0.95, method="prefix"))
            continue

        if query_lower in account_lower:
            ratio = len(query) / len(account)
            score = 0.7 + (0.2 * ratio)
            results.append(MatchResult(account=account, score=score, method="substring"))
            continue

        last_part = parts[-1] if parts else account_lower
        dist = _edit_distance(query_lower, last_part)
        max_len = max(len(query_lower), len(last_part))
        if max_len > 0:
            similarity = 1.0 - (dist / max_len)
            if similarity > 0.4:
                score = similarity * 0.8
                results.append(MatchResult(account=account, score=score, method="edit_distance"))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


def resolve_account(query: str, accounts: list[str]) -> tuple[str | None, list[MatchResult]]:
    """
    Resolve a query to an account name.

    Returns (account, candidates):
    - If top match >= CONFIDENCE_THRESHOLD: returns (matched_account, [top_match])
    - If below threshold: returns (None, top_3_candidates) for user to pick
    - If no matches: returns (None, [])
    """
    matches = match_account(query, accounts)
    if not matches:
        return None, []

    if matches[0].score >= CONFIDENCE_THRESHOLD:
        return matches[0].account, [matches[0]]

    return None, matches
