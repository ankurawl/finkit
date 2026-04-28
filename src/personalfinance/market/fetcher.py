"""Market data fetcher — public APIs to Beancount Price directives."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import httpx

from personalfinance.config import get_config, get_prices_path, resolve_path
from personalfinance.ledger import append_text, format_price_directive, get_commodities, load_file


CRYPTO_TOP = {
    "BTC", "ETH", "SOL", "ADA", "DOT", "AVAX", "MATIC", "LINK", "UNI", "ATOM",
    "XRP", "DOGE", "SHIB", "LTC", "BCH", "XLM", "ALGO", "FTM", "NEAR", "APT",
}

FIAT_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "KRW",
    "MXN", "BRL", "SGD", "HKD", "NZD", "SEK", "NOK", "DKK", "PLN", "ZAR",
}


def fetch_prices(
    commodities: list[str] | None = None,
    manual_prices: dict[str, str] | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """
    Fetch current prices for commodities and write Price directives.

    Auto-detects commodity type (stock, crypto, forex) and uses appropriate API.
    """
    config = get_config()
    prices_path = str(get_prices_path())
    today = date.today()

    if commodities is None:
        try:
            entries, _, _ = load_file(ledger_path)
            commodities = [c for c in get_commodities(entries) if c not in FIAT_CURRENCIES]
        except FileNotFoundError:
            commodities = []

    if not commodities and not manual_prices:
        return {"status": "ok", "message": "No commodities to fetch prices for.", "prices": []}

    cache = _PriceCache(resolve_path(".price_cache.db"), ttl_hours=config.market.cache_ttl_hours)
    results = []
    errors = []

    stocks = [c for c in (commodities or []) if c not in CRYPTO_TOP and c not in FIAT_CURRENCIES]
    cryptos = [c for c in (commodities or []) if c in CRYPTO_TOP]
    forex = [c for c in (commodities or []) if c in FIAT_CURRENCIES and c != config.general.default_currency]

    if stocks:
        for symbol in stocks:
            cached = cache.get(symbol)
            if cached:
                results.append(cached)
                continue
            try:
                price = _fetch_stock_price(symbol)
                if price:
                    entry = {"commodity": symbol, "price": str(price), "currency": "USD", "source": "yfinance"}
                    cache.set(symbol, entry)
                    results.append(entry)
                else:
                    errors.append({"commodity": symbol, "error": "No price data available"})
            except Exception as e:
                errors.append({"commodity": symbol, "error": str(e)})

    if cryptos:
        try:
            crypto_prices = _fetch_crypto_prices(cryptos, config.general.default_currency)
            for symbol, price in crypto_prices.items():
                entry = {"commodity": symbol, "price": str(price), "currency": config.general.default_currency, "source": "coingecko"}
                cache.set(symbol, entry)
                results.append(entry)
        except Exception as e:
            errors.append({"commodity": ",".join(cryptos), "error": str(e)})

    if forex:
        for curr in forex:
            cached = cache.get(f"forex_{curr}")
            if cached:
                results.append(cached)
                continue
            try:
                rate = _fetch_forex_rate(curr, config.general.default_currency)
                if rate:
                    entry = {"commodity": curr, "price": str(rate), "currency": config.general.default_currency, "source": "exchangerate-api"}
                    cache.set(f"forex_{curr}", entry)
                    results.append(entry)
            except Exception as e:
                errors.append({"commodity": curr, "error": str(e)})

    if manual_prices:
        for commodity, price_str in manual_prices.items():
            entry = {"commodity": commodity, "price": price_str, "currency": config.general.default_currency, "source": "manual"}
            results.append(entry)

    directives = []
    for r in results:
        directive = format_price_directive(today, r["commodity"], Decimal(r["price"]), r["currency"])
        directives.append(directive)

    if directives:
        prices_file = Path(prices_path)
        prices_file.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(directives)
        append_text(prices_path, text)

    return {
        "status": "ok",
        "prices": results,
        "errors": errors if errors else None,
        "directives_written": len(directives),
        "prices_file": prices_path,
    }


def _fetch_stock_price(symbol: str) -> Decimal | None:
    """Fetch stock price via yfinance."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        if price:
            return Decimal(str(round(price, 4)))
    except ImportError:
        return _fetch_stock_price_httpx(symbol)
    return None


def _fetch_stock_price_httpx(symbol: str) -> Decimal | None:
    """Fallback stock price fetch via public API."""
    try:
        resp = httpx.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "1d"},
            timeout=10,
            headers={"User-Agent": "finkit/0.1"},
        )
        if resp.status_code == 200:
            data = resp.json()
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return Decimal(str(round(price, 4)))
    except Exception:
        pass
    return None


def _fetch_crypto_prices(symbols: list[str], currency: str) -> dict[str, Decimal]:
    """Fetch crypto prices from CoinGecko."""
    import os
    symbol_to_id = {s: s.lower() for s in symbols}
    id_to_symbol = {v: k for k, v in symbol_to_id.items()}
    ids = ",".join(symbol_to_id.values())

    headers = {}
    api_key = os.environ.get("COINGECKO_API_KEY")
    if api_key:
        headers["x-cg-demo-api-key"] = api_key
        base_url = "https://pro-api.coingecko.com/api/v3"
    else:
        base_url = "https://api.coingecko.com/api/v3"

    resp = httpx.get(
        f"{base_url}/simple/price",
        params={"ids": ids, "vs_currencies": currency.lower()},
        headers=headers,
        timeout=10,
    )

    prices = {}
    if resp.status_code == 200:
        data = resp.json()
        for cg_id, price_data in data.items():
            symbol = id_to_symbol.get(cg_id, cg_id.upper())
            price = price_data.get(currency.lower())
            if price:
                prices[symbol] = Decimal(str(price))
    return prices


def _fetch_forex_rate(from_currency: str, to_currency: str) -> Decimal | None:
    """Fetch forex rate."""
    import os
    api_key = os.environ.get("EXCHANGERATE_API_KEY")
    if not api_key:
        return _fetch_forex_fallback(from_currency, to_currency)

    resp = httpx.get(
        f"https://v6.exchangerate-api.com/v6/{api_key}/pair/{from_currency}/{to_currency}",
        timeout=10,
    )
    if resp.status_code == 200:
        data = resp.json()
        rate = data.get("conversion_rate")
        if rate:
            return Decimal(str(round(rate, 6)))
    return None


def _fetch_forex_fallback(from_currency: str, to_currency: str) -> Decimal | None:
    """Fallback forex rate fetch."""
    try:
        resp = httpx.get(
            f"https://open.er-api.com/v6/latest/{from_currency}",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            rate = data.get("rates", {}).get(to_currency)
            if rate:
                return Decimal(str(round(rate, 6)))
    except Exception:
        pass
    return None


class _PriceCache:
    """Simple SQLite price cache with TTL."""

    def __init__(self, db_path: Path, ttl_hours: int = 12):
        self.db_path = db_path
        self.ttl_seconds = ttl_hours * 3600
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS prices (key TEXT PRIMARY KEY, data TEXT, ts REAL)"
        )

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT data, ts FROM prices WHERE key = ?", (key,)).fetchone()
        if row and (time.time() - row[1]) < self.ttl_seconds:
            return json.loads(row[0])
        return None

    def set(self, key: str, data: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO prices (key, data, ts) VALUES (?, ?, ?)",
            (key, json.dumps(data), time.time()),
        )
        self.conn.commit()
