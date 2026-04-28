"""Core ledger operations — init, open account, submit/amend transactions, assert balance."""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from personalfinance.config import get_config, get_ledger_path, load_config, resolve_path
from personalfinance.ledger import (
    append_text,
    find_entry_by_uuid,
    format_balance_directive,
    format_open_directive,
    format_transaction,
    get_accounts,
    get_commodities,
    load_file,
    remove_entry_text,
    replace_entry_text,
)
from personalfinance.matching import resolve_account
from personalfinance.uuids import generate_uuid_tag


STARTER_TEMPLATE = Path(__file__).parent.parent.parent / "example" / "starter.beancount"


def init_ledger(
    path: str | None = None,
    load_existing: bool = False,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """
    Initialize a new ledger or load an existing one.

    New mode: copies starter.beancount template.
    Load mode: validates existing file, discovers accounts/commodities.
    """
    if data_dir:
        load_config(data_dir)

    if path is None:
        path = str(get_ledger_path())
    target = Path(path)

    if load_existing:
        if not target.exists():
            raise FileNotFoundError(f"Ledger not found: {target}")
        entries, errors, options = load_file(target)
        accounts = get_accounts(entries)
        commodities = get_commodities(entries)
        return {
            "status": "loaded",
            "path": str(target),
            "accounts": accounts,
            "commodities": commodities,
            "entries_count": len(entries),
            "errors": [str(e) for e in errors[:10]],
        }

    if target.exists():
        return {
            "status": "exists",
            "path": str(target),
            "message": "Ledger already exists. Use load_existing=True to load it.",
        }

    target.parent.mkdir(parents=True, exist_ok=True)

    if STARTER_TEMPLATE.exists():
        shutil.copy2(STARTER_TEMPLATE, target)
    else:
        currency = get_config().general.default_currency
        target.write_text(
            f'; Personal Finance Ledger\n; Created by finkit\n\noption "operating_currency" "{currency}"\n\n'
            f"2020-01-01 open Assets:Checking           {currency}\n"
            f"2020-01-01 open Assets:Savings            {currency}\n"
            f"2020-01-01 open Liabilities:CreditCard    {currency}\n"
            f"2020-01-01 open Income:Salary             {currency}\n"
            f"2020-01-01 open Expenses:Other            {currency}\n"
            f"2020-01-01 open Equity:Opening-Balances   {currency}\n"
        )

    entries, errors, options = load_file(target)
    return {
        "status": "created",
        "path": str(target),
        "accounts": get_accounts(entries),
        "commodities": get_commodities(entries),
    }


def open_account(
    account: str,
    currencies: list[str] | None = None,
    booking: str | None = None,
    date_: date | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """Open a new account in the ledger."""
    if ledger_path is None:
        ledger_path = str(get_ledger_path())
    path = Path(ledger_path)

    if not path.exists():
        raise FileNotFoundError(f"Ledger not found: {path}. Run init_ledger first.")

    entries, errors, options = load_file(path)
    existing = get_accounts(entries)
    if account in existing:
        return {"status": "exists", "account": account, "message": "Account already exists."}

    if currencies is None:
        currencies = [get_config().general.default_currency]

    directive = format_open_directive(account, date_=date_, currencies=currencies, booking=booking)
    append_text(path, directive)

    return {"status": "created", "account": account, "directive": directive}


def submit_transaction(
    date_: date,
    payee: str | None,
    narration: str,
    postings: list[dict],
    tags: set[str] | None = None,
    links: set[str] | None = None,
    metadata: dict[str, str] | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Add a transaction to the ledger.

    Uses fuzzy account matching with confidence gate.
    Adds a UUID tag for stable identification.
    """
    if ledger_path is None:
        ledger_path = str(get_ledger_path())
    path = Path(ledger_path)

    if not path.exists():
        raise FileNotFoundError(f"Ledger not found: {path}. Run init_ledger first.")

    entries, errors, options = load_file(path)
    existing_accounts = get_accounts(entries)

    uuid_tag = generate_uuid_tag()
    if tags is None:
        tags = set()
    tags.add(uuid_tag)

    resolved_postings = []
    ambiguous = []

    for p in postings:
        account_query = p["account"]
        resolved, candidates = resolve_account(account_query, existing_accounts)

        if resolved:
            resolved_postings.append({**p, "account": resolved})
        else:
            ambiguous.append({
                "query": account_query,
                "candidates": [
                    {"account": c.account, "score": round(c.score, 3), "method": c.method}
                    for c in candidates
                ],
            })

    if ambiguous:
        return {
            "status": "ambiguous",
            "uuid": uuid_tag,
            "message": "Some accounts could not be resolved confidently. Please select from candidates.",
            "ambiguous_accounts": ambiguous,
            "resolved_postings": resolved_postings,
        }

    text = format_transaction(
        date_=date_,
        payee=payee,
        narration=narration,
        postings=resolved_postings,
        tags=tags,
        links=links,
        metadata=metadata,
    )
    append_text(path, text)

    return {
        "status": "created",
        "uuid": uuid_tag.replace("uuid-", ""),
        "transaction": text,
    }


def amend_transaction(
    uuid: str,
    date_: date | None = None,
    payee: str | None = None,
    narration: str | None = None,
    postings: list[dict] | None = None,
    delete: bool = False,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Edit or delete a transaction by UUID.

    If delete=True, removes the transaction entirely.
    Otherwise, replaces fields provided (keeps original fields for anything not specified).
    """
    if ledger_path is None:
        ledger_path = str(get_ledger_path())
    path = Path(ledger_path)

    entries, errors, options = load_file(path)
    entry = find_entry_by_uuid(entries, uuid)

    if entry is None:
        return {"status": "not_found", "uuid": uuid, "message": f"No transaction with UUID {uuid} found."}

    if delete:
        success = remove_entry_text(path, entry)
        return {
            "status": "deleted" if success else "error",
            "uuid": uuid,
        }

    new_date = date_ if date_ is not None else entry.date
    new_payee = payee if payee is not None else entry.payee
    new_narration = narration if narration is not None else entry.narration

    if postings is not None:
        new_postings = postings
    else:
        new_postings = []
        for p in entry.postings:
            posting_dict: dict[str, Any] = {"account": p.account}
            if p.units:
                posting_dict["amount"] = str(p.units.number) if p.units.number else None
                posting_dict["currency"] = p.units.currency
            new_postings.append(posting_dict)

    from personalfinance.uuids import TAG_PREFIX
    tags = set(entry.tags) if entry.tags else set()
    uuid_tags = {t for t in tags if t.startswith(TAG_PREFIX)}
    if not uuid_tags:
        uuid_tags = {f"{TAG_PREFIX}{uuid}"}
        tags.update(uuid_tags)

    new_text = format_transaction(
        date_=new_date,
        payee=new_payee,
        narration=new_narration,
        postings=new_postings,
        tags=tags,
        links=set(entry.links) if entry.links else None,
    )

    success = replace_entry_text(path, entry, new_text)
    if not success:
        append_text(path, new_text)
        return {
            "status": "appended",
            "uuid": uuid,
            "message": "Could not find original text to replace; appended updated version.",
            "transaction": new_text,
        }

    return {
        "status": "amended",
        "uuid": uuid,
        "transaction": new_text,
    }


def assert_balance(
    account: str,
    expected_amount: Decimal | str,
    date_: date | None = None,
    currency: str | None = None,
    ledger_path: str | None = None,
    write_directive: bool = True,
) -> dict[str, Any]:
    """
    Assert an account balance and optionally write a balance directive.

    Returns match/mismatch status with the difference.
    """
    if ledger_path is None:
        ledger_path = str(get_ledger_path())
    path = Path(ledger_path)

    if currency is None:
        currency = get_config().general.default_currency
    if date_ is None:
        date_ = date.today()

    expected = Decimal(str(expected_amount))

    directive = format_balance_directive(account, date_, expected, currency)
    if write_directive:
        append_text(path, directive)

    entries, errors, options = load_file(path)

    balance_errors = [e for e in errors if "balance" in str(e).lower() and account in str(e)]

    if balance_errors:
        error_msg = str(balance_errors[0])
        import re
        nums = re.findall(r'[-+]?\d*\.?\d+', error_msg)
        actual = Decimal(nums[-1]) if nums else None
        diff = expected - actual if actual else None
        return {
            "status": "mismatch",
            "account": account,
            "expected": str(expected),
            "actual": str(actual) if actual else "unknown",
            "difference": str(diff) if diff else "unknown",
            "currency": currency,
            "date": date_.isoformat(),
            "directive": directive,
        }

    return {
        "status": "match",
        "account": account,
        "balance": str(expected),
        "currency": currency,
        "date": date_.isoformat(),
        "directive": directive,
    }
