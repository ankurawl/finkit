from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, TypeVar

from finkit.db import Database

T = TypeVar("T", bound="SummaryBuilder")


@dataclass
class RefreshContext:
    affected_account_ids: set[int] = field(default_factory=set)
    affected_date_range: tuple[str, str] = ("9999-12-31", "0001-01-01")
    affected_commodities: set[str] = field(default_factory=set)
    prices_updated: bool = False


class SummaryBuilder(ABC):
    table_name: str

    @abstractmethod
    def get_create_sql(self) -> str: ...

    @abstractmethod
    def rebuild(self, db: Database) -> None: ...

    @abstractmethod
    def refresh(self, db: Database, context: RefreshContext) -> None: ...


class SummaryRegistry:
    _summaries: dict[str, SummaryBuilder] = {}

    @classmethod
    def register(cls, table_name: str) -> Callable[[type[T]], type[T]]:
        def decorator(builder_cls: type[T]) -> type[T]:
            instance = builder_cls()
            instance.table_name = table_name
            cls._summaries[table_name] = instance
            return builder_cls
        return decorator

    @classmethod
    def rebuild_all(cls, db: Database) -> None:
        for table_name in cls._summaries:
            db.execute(f"DROP TABLE IF EXISTS {table_name}")

        for builder in cls._summaries.values():
            db.execute(builder.get_create_sql())

        cls._reset_lots(db)

        for builder in cls._summaries.values():
            builder.rebuild(db)

        cls._replay_lot_dispositions(db)

    @classmethod
    def rebuild_one(cls, db: Database, table_name: str) -> None:
        if table_name not in cls._summaries:
            raise KeyError(f"No summary builder registered for {table_name}")
        builder = cls._summaries[table_name]
        db.execute(f"DROP TABLE IF EXISTS {table_name}")
        db.execute(builder.get_create_sql())
        builder.rebuild(db)

    @classmethod
    def refresh_all(cls, db: Database, context: RefreshContext) -> None:
        for builder in cls._summaries.values():
            builder.refresh(db, context)

    @classmethod
    def get_registered(cls) -> list[str]:
        return list(cls._summaries.keys())

    @classmethod
    def create_tables(cls, db: Database) -> None:
        for builder in cls._summaries.values():
            db.execute(builder.get_create_sql())

    @classmethod
    def _reset_lots(cls, db: Database) -> None:
        db.execute("UPDATE lots SET quantity = original_quantity, disposed = 0")

    @classmethod
    def _replay_lot_dispositions(cls, db: Database) -> None:
        dispositions = db.fetchall(
            """
            SELECT ld.lot_id, ld.quantity
            FROM lot_dispositions ld
            JOIN transactions t ON t.id = ld.sell_transaction_id
            ORDER BY t.date ASC, ld.id ASC
            """
        )
        for disp in dispositions:
            disp_qty = Decimal(disp["quantity"])
            lot = db.fetchone("SELECT quantity FROM lots WHERE id = ?", (disp["lot_id"],))
            if lot is None:
                continue
            current_qty = Decimal(lot["quantity"])
            new_qty = current_qty - disp_qty
            disposed = 1 if new_qty <= 0 else 0
            db.execute(
                "UPDATE lots SET quantity = ?, disposed = ? WHERE id = ?",
                (str(new_qty), disposed, disp["lot_id"]),
            )


registry = SummaryRegistry()
