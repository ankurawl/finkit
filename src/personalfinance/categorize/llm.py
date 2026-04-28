"""Ollama-based LLM-assisted transaction categorization."""

from __future__ import annotations

from typing import Any

from personalfinance.config import get_config


def categorize_with_llm(
    descriptions: list[str],
    available_accounts: list[str],
) -> list[dict[str, Any]]:
    """
    Use local Ollama to suggest account categories for transaction descriptions.

    Returns a list of suggestions, one per description.
    Falls back gracefully if Ollama is unavailable.
    """
    config = get_config()
    if not config.ollama.enabled:
        return [{"description": d, "suggestion": None, "reason": "Ollama not enabled"} for d in descriptions]

    try:
        from ollama import Client
    except ImportError:
        return [{"description": d, "suggestion": None, "reason": "ollama package not installed"} for d in descriptions]

    client = Client(host=config.ollama.base_url)
    accounts_str = "\n".join(available_accounts)
    results = []

    for desc in descriptions:
        prompt = (
            f"You are a personal finance categorizer. Given a transaction description, "
            f"suggest the most appropriate account from the list below.\n\n"
            f"Available accounts:\n{accounts_str}\n\n"
            f"Transaction: {desc}\n\n"
            f"Respond with ONLY the account name, nothing else."
        )

        try:
            response = client.chat(
                model=config.ollama.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1},
            )
            suggestion = response["message"]["content"].strip()
            if suggestion in available_accounts:
                results.append({
                    "description": desc,
                    "suggestion": suggestion,
                    "confidence": "high",
                })
            else:
                best = _fuzzy_match_account(suggestion, available_accounts)
                results.append({
                    "description": desc,
                    "suggestion": best,
                    "llm_raw": suggestion,
                    "confidence": "medium",
                })
        except Exception as e:
            results.append({
                "description": desc,
                "suggestion": None,
                "reason": f"Ollama error: {str(e)}",
            })

    return results


def _fuzzy_match_account(suggestion: str, accounts: list[str]) -> str | None:
    """Find the closest matching account from the suggestion."""
    suggestion_lower = suggestion.lower()
    for account in accounts:
        if suggestion_lower in account.lower() or account.lower() in suggestion_lower:
            return account

    parts = suggestion_lower.split(":")
    for part in reversed(parts):
        for account in accounts:
            if part in account.lower():
                return account

    return None
