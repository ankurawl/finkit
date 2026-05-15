from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class Account:
    id: int | None = None
    name: str = ""
    type: str = ""
    currency: str = "USD"
    booking_method: str | None = None
    institution: str | None = None
    asset_class: str | None = None
    jurisdiction: str | None = None
    opened_at: str = ""
    closed_at: str | None = None


@dataclass
class Posting:
    id: int | None = None
    transaction_id: int | None = None
    account_id: int = 0
    account_name: str = ""
    amount: Decimal = Decimal("0")
    currency: str = "USD"
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    cost_date: str | None = None
    price: Decimal | None = None
    price_currency: str | None = None
    lot_id: int | None = None


@dataclass
class Transaction:
    id: int | None = None
    uuid: str = ""
    date: str = ""
    payee: str | None = None
    narration: str | None = None
    normalized_payee: str | None = None
    status: str = "cleared"
    source_file_id: int | None = None
    raw_extraction_id: int | None = None
    created_at: str = ""
    modified_at: str | None = None
    postings: list[Posting] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class Lot:
    id: int | None = None
    account_id: int = 0
    commodity: str = ""
    quantity: Decimal = Decimal("0")
    original_quantity: Decimal = Decimal("0")
    cost_price: Decimal = Decimal("0")
    cost_currency: str = "USD"
    acquired_date: str = ""
    label: str | None = None
    lock_until: str | None = None
    source_transaction_id: int | None = None
    disposed: int = 0


@dataclass
class LotDisposition:
    id: int | None = None
    lot_id: int = 0
    sell_transaction_id: int = 0
    quantity: Decimal = Decimal("0")
    proceeds_per_unit: Decimal = Decimal("0")
    proceeds_currency: str = "USD"
    gain_loss: Decimal = Decimal("0")
    gain_loss_currency: str = "USD"
    term: str = "short"
    wash_sale: int = 0
    wash_sale_adjustment: Decimal | None = None


@dataclass
class Price:
    id: int | None = None
    commodity: str = ""
    currency: str = "USD"
    price: Decimal = Decimal("0")
    date: str = ""
    source: str | None = None


@dataclass
class SourceFile:
    id: int | None = None
    path: str = ""
    original_path: str | None = None
    sha256: str = ""
    institution: str | None = None
    file_type: str | None = None
    imported_at: str = ""
    original_filename: str | None = None


@dataclass
class RawExtraction:
    id: int | None = None
    source_file_id: int = 0
    row_index: int | None = None
    raw_data: str = ""
    extraction_date: str = ""


@dataclass
class BalanceAssertion:
    id: int | None = None
    account_id: int = 0
    date: str = ""
    expected_amount: Decimal = Decimal("0")
    actual_amount: Decimal = Decimal("0")
    currency: str = "USD"
    matches: bool = True
    difference: Decimal | None = None
    asserted_at: str = ""


@dataclass
class ColumnMapping:
    id: int | None = None
    name: str = ""
    institution: str | None = None
    mapping: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class CategorizationRule:
    id: int | None = None
    pattern: str = ""
    pattern_type: str = "substring"
    target_account: str = ""
    institution: str | None = None
    priority: int = 0
    created_at: str = ""


@dataclass
class Budget:
    account_id: int = 0
    year_month: str = ""
    amount: Decimal = Decimal("0")
    currency: str = "USD"


@dataclass
class RecurringTransaction:
    id: int | None = None
    frequency: str = "monthly"
    next_date: str = ""
    payee: str | None = None
    narration: str | None = None
    template_postings: list[dict] = field(default_factory=list)
    active: int = 1
    created_at: str = ""


@dataclass
class CurrencyTolerance:
    currency: str = "USD"
    tolerance: Decimal = Decimal("0.01")


@dataclass
class PayeeNormalizationRule:
    id: int | None = None
    pattern: str = ""
    pattern_type: str = "substring"
    canonical_name: str = ""
    priority: int = 0
    created_at: str = ""


@dataclass
class DocumentTemplate:
    id: int | None = None
    name: str = ""
    institution: str | None = None
    document_type: str = ""
    match_keywords: list[str] = field(default_factory=list)
    template_json: dict = field(default_factory=dict)
    account_mapping: dict | None = None
    created_at: str = ""
    last_used_at: str | None = None
    use_count: int = 0
