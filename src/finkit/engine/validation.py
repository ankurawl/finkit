from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from finkit.db import Database
from finkit.models import Posting, Transaction

_DEFAULT_FIAT_TOLERANCE = Decimal("0.01")
_DEFAULT_CRYPTO_TOLERANCE = Decimal("0.00000001")

_CRYPTO_CURRENCIES = frozenset({"BTC", "ETH", "SOL", "DOGE", "ADA", "XRP", "DOT", "AVAX", "MATIC", "LINK"})


class UnbalancedTransactionError(Exception):
    pass


class AccountNotFoundError(Exception):
    pass


class AccountClosedError(Exception):
    pass


class CurrencyMismatchError(Exception):
    pass


def get_tolerances(db: Database) -> dict[str, Decimal]:
    rows = db.fetchall("SELECT currency, tolerance FROM currency_tolerances")
    return {row["currency"]: Decimal(str(row["tolerance"])) for row in rows}


def _tolerance_for(currency: str, tolerances: dict[str, Decimal]) -> Decimal:
    if currency in tolerances:
        return tolerances[currency]
    if currency in _CRYPTO_CURRENCIES:
        return _DEFAULT_CRYPTO_TOLERANCE
    return _DEFAULT_FIAT_TOLERANCE


def check_balance(postings: list[Posting], tolerances: dict[str, Decimal]) -> None:
    sums: dict[str, Decimal] = defaultdict(Decimal)

    for p in postings:
        if p.price is not None and p.price_currency is not None:
            # Weight is amount * price, counted in price_currency
            weight = p.amount * p.price
            sums[p.price_currency] += weight
        else:
            sums[p.currency] += p.amount

    for currency, total in sums.items():
        tol = _tolerance_for(currency, tolerances)
        if abs(total) > tol:
            raise UnbalancedTransactionError(
                f"Postings do not balance in {currency}: residual {total} exceeds tolerance {tol}"
            )


def _check_accounts_exist(db: Database, postings: list[Posting]) -> dict[int, dict]:
    accounts: dict[int, dict] = {}
    for p in postings:
        if p.account_id in accounts:
            continue
        row = db.fetchone(
            "SELECT id, name, type, currency, booking_method, closed_at FROM accounts WHERE id = ?",
            (p.account_id,),
        )
        if row is None:
            # Try by name as fallback
            if p.account_name:
                row = db.fetchone(
                    "SELECT id, name, type, currency, booking_method, closed_at FROM accounts WHERE name = ?",
                    (p.account_name,),
                )
            if row is None:
                identifier = p.account_name or str(p.account_id)
                raise AccountNotFoundError(f"Account not found: {identifier}")
        accounts[p.account_id] = dict(row)
    return accounts


def _check_accounts_open(transaction_date: str, postings: list[Posting], accounts: dict[int, dict]) -> None:
    for p in postings:
        acct = accounts[p.account_id]
        closed_at = acct.get("closed_at")
        if closed_at is not None and transaction_date >= closed_at:
            raise AccountClosedError(
                f"Account '{acct['name']}' was closed on {closed_at}, "
                f"cannot post on {transaction_date}"
            )


def _is_investment_account(acct: dict) -> bool:
    return acct.get("booking_method") is not None


def _check_currency_constraints(postings: list[Posting], accounts: dict[int, dict]) -> None:
    for p in postings:
        acct = accounts[p.account_id]
        if _is_investment_account(acct):
            continue
        acct_currency = acct.get("currency", "USD")
        if p.currency != acct_currency:
            raise CurrencyMismatchError(
                f"Posting currency {p.currency} does not match "
                f"account '{acct['name']}' currency {acct_currency}"
            )


def validate_transaction(db: Database, transaction: Transaction) -> None:
    if not transaction.postings:
        raise UnbalancedTransactionError("Transaction has no postings")

    tolerances = get_tolerances(db)
    check_balance(transaction.postings, tolerances)

    accounts = _check_accounts_exist(db, transaction.postings)
    _check_accounts_open(transaction.date, transaction.postings, accounts)
    _check_currency_constraints(transaction.postings, accounts)
