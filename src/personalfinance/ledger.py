"""Ledger operations — load, validate, write, and query .beancount files."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from beancount import loader
from beancount.core import data as bc_data
from beancount.core.amount import Amount
from beancount.core.number import D

from personalfinance.config import get_config, get_ledger_path
from personalfinance.uuids import TAG_PREFIX


def load_file(path: str | Path | None = None) -> tuple[list, list, dict]:
    """
    Load and validate a beancount file.

    Returns (entries, errors, options).
    """
    if path is None:
        path = get_ledger_path()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Ledger file not found: {path}")

    entries, errors, options = loader.load_file(str(path))
    return entries, errors, options


def get_accounts(entries: list) -> list[str]:
    """Extract all open account names from entries."""
    accounts = set()
    for entry in entries:
        if isinstance(entry, bc_data.Open):
            accounts.add(entry.account)
    return sorted(accounts)


def get_commodities(entries: list) -> list[str]:
    """Extract all commodities referenced in entries."""
    commodities = set()
    for entry in entries:
        if isinstance(entry, bc_data.Commodity):
            commodities.add(entry.currency)
        elif isinstance(entry, bc_data.Open) and entry.currencies:
            commodities.update(entry.currencies)
        elif isinstance(entry, bc_data.Transaction):
            for posting in entry.postings:
                if posting.units and posting.units.currency:
                    commodities.add(posting.units.currency)
    return sorted(commodities)


def find_entry_by_uuid(entries: list, uuid_str: str) -> Any | None:
    """Find a transaction by its UUID tag."""
    target_tag = f"{TAG_PREFIX}{uuid_str}"
    for entry in entries:
        if isinstance(entry, bc_data.Transaction) and entry.tags:
            if target_tag in entry.tags:
                return entry
    return None


def append_text(path: str | Path | None, text: str) -> None:
    """Append raw text to a beancount file."""
    if path is None:
        path = get_ledger_path()
    path = Path(path)
    with open(path, "a") as f:
        f.write("\n" + text + "\n")


def format_open_directive(
    account: str,
    date_: date | None = None,
    currencies: list[str] | None = None,
    booking: str | None = None,
) -> str:
    """Format an Open directive as beancount text."""
    if date_ is None:
        date_ = date(2020, 1, 1)
    parts = [date_.isoformat(), "open", account]
    if currencies:
        parts.append(",".join(currencies))
    if booking:
        parts.append(f'"{booking}"')
    return " ".join(parts)


def format_transaction(
    date_: date,
    payee: str | None,
    narration: str,
    postings: list[dict],
    tags: set[str] | None = None,
    links: set[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    """
    Format a transaction as beancount text.

    Each posting dict has keys: account, amount (Decimal or str), currency.
    If amount is None, it's an auto-balanced posting.
    """
    tag_str = ""
    if tags:
        tag_str = " " + " ".join(f"#{t}" for t in sorted(tags))
    link_str = ""
    if links:
        link_str = " " + " ".join(f"^{l}" for l in sorted(links))

    if payee:
        header = f'{date_.isoformat()} * "{payee}" "{narration}"{tag_str}{link_str}'
    else:
        header = f'{date_.isoformat()} * "{narration}"{tag_str}{link_str}'

    lines = [header]

    if metadata:
        for key, value in metadata.items():
            lines.append(f'  {key}: "{value}"')

    for p in postings:
        account = p["account"]
        amount = p.get("amount")
        currency = p.get("currency", get_config().general.default_currency)
        if amount is not None:
            amt = Decimal(str(amount))
            lines.append(f"  {account}  {amt} {currency}")
        else:
            lines.append(f"  {account}")

    return "\n".join(lines)


def format_balance_directive(account: str, date_: date, amount: Decimal | str, currency: str | None = None) -> str:
    """Format a balance assertion directive."""
    if currency is None:
        currency = get_config().general.default_currency
    amt = Decimal(str(amount))
    return f"{date_.isoformat()} balance {account}  {amt} {currency}"


def format_price_directive(date_: date, commodity: str, amount: Decimal | str, currency: str) -> str:
    """Format a Price directive."""
    amt = Decimal(str(amount))
    return f"{date_.isoformat()} price {commodity}  {amt} {currency}"


def remove_entry_text(path: str | Path, entry: Any) -> bool:
    """
    Remove a transaction from the file by matching its UUID tag.

    Returns True if the entry was found and removed.
    """
    path = Path(path)
    if not path.exists():
        return False

    content = path.read_text()

    if not isinstance(entry, bc_data.Transaction) or not entry.tags:
        return False

    uuid_tags = [t for t in entry.tags if t.startswith(TAG_PREFIX)]
    if not uuid_tags:
        return False

    uuid_tag = uuid_tags[0]
    pattern = re.compile(
        rf'^(\d{{4}}-\d{{2}}-\d{{2}}\s+\*\s+.*#{re.escape(uuid_tag)}.*\n(?:\s+.*\n)*)',
        re.MULTILINE,
    )
    new_content, count = pattern.subn("", content)
    if count > 0:
        path.write_text(new_content)
        return True
    return False


def replace_entry_text(path: str | Path, old_entry: Any, new_text: str) -> bool:
    """
    Replace a transaction in the file by matching its UUID tag.

    Returns True if the entry was found and replaced.
    """
    path = Path(path)
    if not path.exists():
        return False

    content = path.read_text()

    if not isinstance(old_entry, bc_data.Transaction) or not old_entry.tags:
        return False

    uuid_tags = [t for t in old_entry.tags if t.startswith(TAG_PREFIX)]
    if not uuid_tags:
        return False

    uuid_tag = uuid_tags[0]
    pattern = re.compile(
        rf'^(\d{{4}}-\d{{2}}-\d{{2}}\s+\*\s+.*#{re.escape(uuid_tag)}.*\n(?:\s+.*\n)*)',
        re.MULTILINE,
    )
    new_content, count = pattern.subn(new_text + "\n", content)
    if count > 0:
        path.write_text(new_content)
        return True
    return False
