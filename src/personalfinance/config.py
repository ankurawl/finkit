"""Configuration loader for finkit — reads finkit.toml and .env files."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class GeneralConfig(BaseModel):
    ledger_path: str = "main.beancount"
    prices_path: str = "prices.beancount"
    default_currency: str = "USD"
    data_dir: str = "."


class ImportConfig(BaseModel):
    mappings_dir: str = "mappings"
    rules_file: str = "rules.json"
    dedup_window_days: int = 3


class MarketConfig(BaseModel):
    cache_ttl_hours: int = 12
    stock_source: str = "yfinance"
    crypto_source: str = "coingecko"
    forex_source: str = "exchangerate-api"
    manual_prices_file: str = "manual_prices.json"


class OllamaConfig(BaseModel):
    enabled: bool = False
    model: str = "qwen2.5:7b"
    base_url: str = "http://localhost:11434"


class FinKitConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    import_: ImportConfig = Field(default_factory=ImportConfig, alias="import")
    market: MarketConfig = Field(default_factory=MarketConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)

    model_config = {"populate_by_name": True}


_config: Optional[FinKitConfig] = None
_data_dir: Optional[Path] = None


def load_config(data_dir: str | Path | None = None) -> FinKitConfig:
    """Load configuration from finkit.toml in the given data directory."""
    global _config, _data_dir

    if data_dir is None:
        data_dir = Path(os.environ.get("FINKIT_DATA_DIR", "~/finance")).expanduser()
    else:
        data_dir = Path(data_dir).expanduser().resolve()

    _data_dir = data_dir

    env_file = data_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    config_file = data_dir / "finkit.toml"
    if config_file.exists():
        with open(config_file, "rb") as f:
            raw = tomllib.load(f)
        _config = FinKitConfig.model_validate(raw)
    else:
        _config = FinKitConfig()

    return _config


def get_config() -> FinKitConfig:
    """Return the loaded config, loading defaults if not yet initialized."""
    global _config
    if _config is None:
        return load_config()
    return _config


def get_data_dir() -> Path:
    """Return the resolved data directory path."""
    global _data_dir
    if _data_dir is None:
        load_config()
    return _data_dir  # type: ignore[return-value]


def resolve_path(relative_path: str) -> Path:
    """Resolve a path relative to the data directory."""
    return get_data_dir() / relative_path


def get_ledger_path() -> Path:
    """Return the full path to the main ledger file."""
    return resolve_path(get_config().general.ledger_path)


def get_prices_path() -> Path:
    """Return the full path to the prices file."""
    return resolve_path(get_config().general.prices_path)
