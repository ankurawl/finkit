"""Rule-based transaction categorization — merchant to account mapping."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from personalfinance.config import get_config, resolve_path


DEFAULT_RULES = {
    "WHOLEFDS": "Expenses:Food:Groceries",
    "WHOLE FOODS": "Expenses:Food:Groceries",
    "TRADER JOE": "Expenses:Food:Groceries",
    "COSTCO": "Expenses:Food:Groceries",
    "KROGER": "Expenses:Food:Groceries",
    "SAFEWAY": "Expenses:Food:Groceries",
    "WALMART": "Expenses:Food:Groceries",
    "TARGET": "Expenses:Shopping:Clothing",
    "AMAZON": "Expenses:Shopping:Electronics",
    "SHELL": "Expenses:Transport:Gas",
    "CHEVRON": "Expenses:Transport:Gas",
    "EXXON": "Expenses:Transport:Gas",
    "BP ": "Expenses:Transport:Gas",
    "UBER": "Expenses:Transport:Rideshare",
    "LYFT": "Expenses:Transport:Rideshare",
    "NETFLIX": "Expenses:Subscriptions",
    "SPOTIFY": "Expenses:Subscriptions",
    "HULU": "Expenses:Subscriptions",
    "DISNEY+": "Expenses:Subscriptions",
    "APPLE.COM/BILL": "Expenses:Subscriptions",
    "GOOGLE *": "Expenses:Subscriptions",
    "STARBUCKS": "Expenses:Food:Coffee",
    "DUNKIN": "Expenses:Food:Coffee",
    "MCDONALD": "Expenses:Food:DiningOut",
    "CHIPOTLE": "Expenses:Food:DiningOut",
    "DOORDASH": "Expenses:Food:DiningOut",
    "GRUBHUB": "Expenses:Food:DiningOut",
    "UBER EATS": "Expenses:Food:DiningOut",
    "PG&E": "Expenses:Housing:Utilities",
    "COMCAST": "Expenses:Housing:Utilities",
    "AT&T": "Expenses:Housing:Utilities",
    "VERIZON": "Expenses:Housing:Utilities",
    "T-MOBILE": "Expenses:Housing:Utilities",
}


def load_rules(rules_file: str | None = None) -> dict[str, str]:
    """Load categorization rules from JSON file, merged with defaults."""
    rules = dict(DEFAULT_RULES)

    if rules_file is None:
        config = get_config()
        rules_path = resolve_path(config.import_.rules_file)
    else:
        rules_path = Path(rules_file)

    if rules_path.exists():
        custom = json.loads(rules_path.read_text())
        rules.update(custom)

    return rules


def save_rules(rules: dict[str, str], rules_file: str | None = None) -> None:
    """Save categorization rules to JSON file."""
    if rules_file is None:
        config = get_config()
        rules_path = resolve_path(config.import_.rules_file)
    else:
        rules_path = Path(rules_file)

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    custom = {k: v for k, v in rules.items() if k not in DEFAULT_RULES or rules[k] != DEFAULT_RULES.get(k)}
    rules_path.write_text(json.dumps(custom, indent=2))


def categorize_payee(payee: str, rules: dict[str, str] | None = None) -> str | None:
    """
    Match a payee string against categorization rules.

    Returns the mapped account or None if no match.
    """
    if not payee:
        return None

    if rules is None:
        rules = load_rules()

    payee_upper = payee.upper().strip()

    for pattern, account in rules.items():
        if pattern.upper() in payee_upper:
            return account

    return None


def apply_rules(
    rules_file: str | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Apply categorization rules to uncategorized transactions in the ledger.

    Transactions posting to Expenses:Other or Income:Other are considered uncategorized.
    """
    from personalfinance.config import get_ledger_path
    from personalfinance.ledger import load_file

    if ledger_path is None:
        ledger_path = str(get_ledger_path())

    rules = load_rules(rules_file)
    entries, errors, options = load_file(ledger_path)

    from beancount.core import data as bc_data
    categorized = 0
    uncategorized = 0

    path = Path(ledger_path)
    content = path.read_text()

    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
            continue
        if not entry.payee:
            continue

        has_other = any(
            p.account in ("Expenses:Other", "Income:Other")
            for p in entry.postings
        )
        if not has_other:
            continue

        new_account = categorize_payee(entry.payee, rules)
        if new_account:
            for p in entry.postings:
                if p.account in ("Expenses:Other", "Income:Other"):
                    content = content.replace(
                        f"  {p.account}",
                        f"  {new_account}",
                        1,
                    )
                    categorized += 1
                    break
        else:
            uncategorized += 1

    if categorized > 0:
        path.write_text(content)

    return {
        "status": "ok",
        "categorized": categorized,
        "uncategorized": uncategorized,
        "rules_count": len(rules),
    }


def review_uncategorized(ledger_path: str | None = None) -> dict[str, Any]:
    """List all uncategorized transactions for review."""
    from personalfinance.config import get_ledger_path
    from personalfinance.ledger import load_file

    if ledger_path is None:
        ledger_path = str(get_ledger_path())

    entries, errors, options = load_file(ledger_path)
    from beancount.core import data as bc_data

    uncategorized = []
    for entry in entries:
        if not isinstance(entry, bc_data.Transaction):
            continue
        has_other = any(
            p.account in ("Expenses:Other", "Income:Other")
            for p in entry.postings
        )
        if has_other:
            amounts = [
                f"{p.units.number} {p.units.currency}"
                for p in entry.postings
                if p.units and p.units.number and p.units.number > 0
            ]
            uuid_tag = None
            if entry.tags:
                from personalfinance.uuids import TAG_PREFIX
                for t in entry.tags:
                    if t.startswith(TAG_PREFIX):
                        uuid_tag = t[len(TAG_PREFIX):]
                        break
            uncategorized.append({
                "date": entry.date.isoformat(),
                "payee": entry.payee,
                "narration": entry.narration,
                "amount": amounts[0] if amounts else None,
                "uuid": uuid_tag,
            })

    return {
        "status": "ok",
        "uncategorized": uncategorized,
        "count": len(uncategorized),
    }
