from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from finkit.config import Settings

SCHEMA_VERSION = 1

_CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    original_path TEXT,
    sha256 TEXT NOT NULL UNIQUE,
    institution TEXT,
    file_type TEXT,
    imported_at TEXT NOT NULL,
    original_filename TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_files_institution ON source_files(institution);

CREATE TABLE IF NOT EXISTS raw_extractions (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES source_files(id),
    row_index INTEGER,
    raw_data TEXT NOT NULL,
    extraction_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_extractions_source ON raw_extractions(source_file_id);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    currency TEXT DEFAULT 'USD',
    booking_method TEXT,
    institution TEXT,
    asset_class TEXT,
    jurisdiction TEXT,
    opened_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(type);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    date TEXT NOT NULL,
    payee TEXT,
    narration TEXT,
    status TEXT DEFAULT 'cleared',
    source_file_id INTEGER REFERENCES source_files(id),
    raw_extraction_id INTEGER REFERENCES raw_extractions(id),
    created_at TEXT NOT NULL,
    modified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_uuid ON transactions(uuid);
CREATE INDEX IF NOT EXISTS idx_transactions_payee ON transactions(payee);
CREATE INDEX IF NOT EXISTS idx_transactions_source ON transactions(source_file_id);

CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    commodity TEXT NOT NULL,
    quantity TEXT NOT NULL,
    original_quantity TEXT NOT NULL,
    cost_price TEXT NOT NULL,
    cost_currency TEXT NOT NULL,
    acquired_date TEXT NOT NULL,
    label TEXT,
    lock_until TEXT,
    source_transaction_id INTEGER REFERENCES transactions(id),
    disposed INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lots_account_commodity ON lots(account_id, commodity);
CREATE INDEX IF NOT EXISTS idx_lots_commodity_disposed ON lots(commodity, disposed);

CREATE TABLE IF NOT EXISTS postings (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    cost_amount TEXT,
    cost_currency TEXT,
    cost_date TEXT,
    price TEXT,
    price_currency TEXT,
    lot_id INTEGER REFERENCES lots(id)
);
CREATE INDEX IF NOT EXISTS idx_postings_transaction ON postings(transaction_id);
CREATE INDEX IF NOT EXISTS idx_postings_account ON postings(account_id);

CREATE TABLE IF NOT EXISTS transaction_tags (
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (transaction_id, tag)
);

CREATE TABLE IF NOT EXISTS lot_dispositions (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES lots(id),
    sell_transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    quantity TEXT NOT NULL,
    proceeds_per_unit TEXT NOT NULL,
    proceeds_currency TEXT NOT NULL,
    gain_loss TEXT NOT NULL,
    gain_loss_currency TEXT NOT NULL,
    term TEXT NOT NULL,
    wash_sale INTEGER DEFAULT 0,
    wash_sale_adjustment TEXT
);
CREATE INDEX IF NOT EXISTS idx_lot_dispositions_sell ON lot_dispositions(sell_transaction_id);

CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY,
    commodity TEXT NOT NULL,
    currency TEXT NOT NULL,
    price TEXT NOT NULL,
    date TEXT NOT NULL,
    source TEXT,
    UNIQUE(commodity, currency, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_commodity_date ON prices(commodity, date);

CREATE TABLE IF NOT EXISTS categorization_rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    pattern_type TEXT DEFAULT 'substring',
    target_account TEXT NOT NULL,
    institution TEXT,
    priority INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cat_rules_priority ON categorization_rules(priority DESC);

CREATE TABLE IF NOT EXISTS balance_assertions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    date TEXT NOT NULL,
    expected_amount TEXT NOT NULL,
    actual_amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    matches INTEGER NOT NULL,
    difference TEXT,
    asserted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS column_mappings (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    institution TEXT,
    mapping TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS currency_tolerances (
    currency TEXT PRIMARY KEY,
    tolerance TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recurring_transactions (
    id INTEGER PRIMARY KEY,
    frequency TEXT NOT NULL,
    next_date TEXT NOT NULL,
    payee TEXT,
    narration TEXT,
    template_postings TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budgets (
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    year_month TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (account_id, year_month, currency)
) WITHOUT ROWID;
"""

_SUMMARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS s_daily_balances (
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    date TEXT NOT NULL,
    balance TEXT NOT NULL,
    currency TEXT NOT NULL,
    transaction_count INTEGER,
    PRIMARY KEY (account_id, date, currency)
);

CREATE TABLE IF NOT EXISTS s_monthly_spending (
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    year_month TEXT NOT NULL,
    total TEXT NOT NULL,
    currency TEXT NOT NULL,
    transaction_count INTEGER,
    PRIMARY KEY (account_id, year_month, currency)
);

CREATE TABLE IF NOT EXISTS s_portfolio_holdings (
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    commodity TEXT NOT NULL,
    total_quantity TEXT NOT NULL,
    total_cost_basis TEXT NOT NULL,
    cost_currency TEXT NOT NULL,
    latest_price TEXT,
    latest_price_date TEXT,
    market_value TEXT,
    unrealized_gain TEXT,
    asset_class TEXT,
    PRIMARY KEY (account_id, commodity)
);

CREATE TABLE IF NOT EXISTS s_account_monthly_balances (
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    year_month TEXT NOT NULL,
    closing_balance TEXT NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (account_id, year_month, currency)
);

CREATE TABLE IF NOT EXISTS s_net_worth (
    year_month TEXT NOT NULL,
    currency TEXT NOT NULL,
    total_assets TEXT NOT NULL,
    total_liabilities TEXT NOT NULL,
    net_worth TEXT NOT NULL,
    assets_cash TEXT,
    assets_equity TEXT,
    assets_debt TEXT,
    assets_crypto TEXT,
    assets_other TEXT,
    exchange_rate_to_base TEXT,
    PRIMARY KEY (year_month, currency)
);

CREATE TABLE IF NOT EXISTS s_yearly_capital_gains (
    year INTEGER NOT NULL,
    term TEXT NOT NULL,
    currency TEXT NOT NULL,
    total_proceeds TEXT NOT NULL,
    total_cost_basis TEXT NOT NULL,
    total_gain_loss TEXT NOT NULL,
    disposition_count INTEGER,
    PRIMARY KEY (year, term, currency)
);
"""


def _adapt_decimal(d: Decimal) -> str:
    return str(d)


def _convert_decimal(s: bytes) -> Decimal:
    return Decimal(s.decode())


sqlite3.register_adapter(Decimal, _adapt_decimal)


class Database:
    def __init__(self, path: Path | str, *, read_only: bool = False):
        self.path = Path(path)
        self._read_only = read_only
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        uri = f"file:{self.path}"
        if self._read_only:
            uri += "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            return self.connect()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def create_schema(self) -> None:
        conn = self.conn
        conn.executescript(_CORE_SCHEMA)
        conn.executescript(_SUMMARY_SCHEMA)
        now = _now_iso()
        conn.execute("BEGIN")
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
            (SCHEMA_VERSION, now, "Initial schema"),
        )
        conn.execute("COMMIT")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params: list) -> sqlite3.Cursor:
        return self.conn.executemany(sql, params)

    def fetchone(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def query_readonly(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        self.conn.execute("PRAGMA query_only = ON")
        try:
            return self.fetchall(sql, params)
        finally:
            self.conn.execute("PRAGMA query_only = OFF")

    def backup(self, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(str(dest_path))
        try:
            self.conn.backup(dest)
        finally:
            dest.close()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_db(settings: Settings) -> Iterator[Database]:
    db = Database(settings.db_path)
    try:
        db.connect()
        yield db
    finally:
        db.close()
