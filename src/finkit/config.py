from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from dotenv import load_dotenv


_DEFAULT_HOLDING_PERIODS: dict[str, int] = {
    "US.equity": 365,
    "US.crypto": 365,
    "IN.equity": 365,
    "IN.debt": 1095,
    "IN.elss": 1095,
}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path.home() / "finance")
    default_currency: str = "USD"
    base_currency: str = "USD"
    holding_periods: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_HOLDING_PERIODS))
    dedup_window_days: int = 3
    stock_source: str = "yfinance"
    crypto_source: str = "coingecko"
    forex_source: str = "exchangerate-api"
    ollama_enabled: bool = False
    ollama_model: str = "qwen2.5:7b"
    ollama_base_url: str = "http://localhost:11434"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "finkit.db"

    @property
    def statements_dir(self) -> Path:
        return self.data_dir / "statements"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    def holding_period_days(self, jurisdiction: str | None, asset_class: str | None) -> int:
        if jurisdiction and asset_class:
            key = f"{jurisdiction}.{asset_class}"
            if key in self.holding_periods:
                return self.holding_periods[key]
        return 365


def load_settings(config_path: Path | None = None, data_dir: Path | None = None) -> Settings:
    load_dotenv()

    raw: dict = {}
    if config_path and config_path.exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    elif data_dir:
        candidate = data_dir / "finkit.toml"
        if candidate.exists():
            with open(candidate, "rb") as f:
                raw = tomllib.load(f)

    general = raw.get("general", {})
    resolved_data_dir = data_dir or Path(os.path.expanduser(general.get("data_dir", "~/finance")))

    holding = dict(_DEFAULT_HOLDING_PERIODS)
    for key, val in raw.get("holding_periods", {}).items():
        holding[key] = int(val)

    imp = raw.get("import", {})
    market = raw.get("market", {})
    ollama = raw.get("ollama", {})

    return Settings(
        data_dir=resolved_data_dir,
        default_currency=general.get("default_currency", "USD"),
        base_currency=general.get("base_currency", "USD"),
        holding_periods=holding,
        dedup_window_days=int(imp.get("dedup_window_days", 3)),
        stock_source=market.get("stock_source", "yfinance"),
        crypto_source=market.get("crypto_source", "coingecko"),
        forex_source=market.get("forex_source", "exchangerate-api"),
        ollama_enabled=bool(ollama.get("enabled", False)),
        ollama_model=ollama.get("model", "qwen2.5:7b"),
        ollama_base_url=ollama.get("base_url", "http://localhost:11434"),
    )
