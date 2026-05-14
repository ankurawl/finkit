from __future__ import annotations

import json
import logging

from finkit.config import Settings

logger = logging.getLogger(__name__)


def categorize_with_llm(
    descriptions: list[str],
    existing_accounts: list[str],
    settings: Settings,
) -> list[str | None]:
    if not descriptions:
        return []

    if not settings.ollama_enabled:
        return [None] * len(descriptions)

    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed; skipping LLM categorization")
        return [None] * len(descriptions)

    accounts_text = "\n".join(f"- {a}" for a in existing_accounts)
    items_text = "\n".join(f"{i+1}. {d}" for i, d in enumerate(descriptions))

    prompt = (
        "You are a financial transaction categorizer. Given the list of account categories "
        "and transaction descriptions below, assign each transaction to the most appropriate account.\n\n"
        f"Available accounts:\n{accounts_text}\n\n"
        f"Transactions to categorize:\n{items_text}\n\n"
        "Respond with a JSON array of strings, one per transaction, in the same order. "
        "Use the exact account name from the list above. "
        "If you cannot confidently categorize a transaction, use null for that entry.\n\n"
        "Example response: [\"Expenses:Groceries\", null, \"Expenses:Utilities\"]\n"
        "Respond ONLY with the JSON array, no other text."
    )

    url = f"{settings.ollama_base_url}/api/generate"
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
    except (httpx.HTTPError, httpx.ConnectError, OSError) as exc:
        logger.warning("Ollama request failed: %s", exc)
        return [None] * len(descriptions)

    try:
        body = resp.json()
        raw_text = body.get("response", "")
        results = json.loads(raw_text)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse Ollama response: %s", exc)
        return [None] * len(descriptions)

    if not isinstance(results, list):
        return [None] * len(descriptions)

    valid_set = set(existing_accounts)
    output: list[str | None] = []
    for item in results:
        if isinstance(item, str) and item in valid_set:
            output.append(item)
        else:
            output.append(None)

    # Pad or truncate to match input length
    while len(output) < len(descriptions):
        output.append(None)
    output = output[:len(descriptions)]

    return output
