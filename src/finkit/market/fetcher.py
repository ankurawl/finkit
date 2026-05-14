from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal

from finkit.config import Settings
from finkit.db import Database
from finkit.engine.prices import store_price
from finkit.summaries.registry import RefreshContext, SummaryRegistry

logger = logging.getLogger(__name__)

_COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
_EXCHANGERATE_BASE_URL = "https://v6.exchangerate-api.com/v6"


def _today_iso() -> str:
    return date.today().isoformat()


def fetch_stock_prices(
    db: Database,
    symbols: list[str],
    settings: Settings | None = None,
) -> dict:
    """Fetch latest prices for stocks/ETFs/mutual funds via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance is not installed; skipping stock price fetch")
        return {
            "fetched": 0,
            "errors": ["yfinance is not installed — run `pip install yfinance`"],
        }

    fetched = 0
    errors: list[str] = []
    today = _today_iso()

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price_val = info.get("regularMarketPrice") or info.get("previousClose")
            if price_val is None:
                hist = ticker.history(period="1d")
                if hist.empty:
                    errors.append(f"{symbol}: no price data available")
                    continue
                price_val = hist["Close"].iloc[-1]

            price_dec = Decimal(str(price_val))
            currency = (info.get("currency") or "USD").upper()

            store_price(
                db,
                commodity=symbol.upper(),
                currency=currency,
                price=price_dec,
                date=today,
                source="yfinance",
            )
            fetched += 1
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    return {"fetched": fetched, "errors": errors}


def fetch_crypto_prices(
    db: Database,
    coins: list[str],
    currency: str = "USD",
    settings: Settings | None = None,
) -> dict:
    """Fetch crypto prices from CoinGecko."""
    try:
        import httpx
    except ImportError:
        return {
            "fetched": 0,
            "errors": ["httpx is not installed — run `pip install httpx`"],
        }

    api_key = os.environ.get("COINGECKO_API_KEY")
    ids_str = ",".join(c.lower() for c in coins)
    vs = currency.lower()
    params: dict[str, str] = {"ids": ids_str, "vs_currencies": vs}
    headers: dict[str, str] = {}
    if api_key:
        headers["x-cg-demo-api-key"] = api_key

    fetched = 0
    errors: list[str] = []
    today = _today_iso()

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{_COINGECKO_BASE_URL}/simple/price",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"fetched": 0, "errors": [f"CoinGecko API error: {exc}"]}

    for coin in coins:
        coin_lower = coin.lower()
        if coin_lower not in data:
            errors.append(f"{coin}: not found in CoinGecko response")
            continue
        price_val = data[coin_lower].get(vs)
        if price_val is None:
            errors.append(f"{coin}: price in {currency} not available")
            continue

        price_dec = Decimal(str(price_val))
        # Use uppercase ticker-style commodity name
        commodity = coin.upper()

        store_price(
            db,
            commodity=commodity,
            currency=currency.upper(),
            price=price_dec,
            date=today,
            source="coingecko",
        )
        fetched += 1

    return {"fetched": fetched, "errors": errors}


def fetch_forex_rates(
    db: Database,
    pairs: list[tuple[str, str]],
    settings: Settings | None = None,
) -> dict:
    """Fetch forex exchange rates from ExchangeRate-API."""
    try:
        import httpx
    except ImportError:
        return {
            "fetched": 0,
            "errors": ["httpx is not installed — run `pip install httpx`"],
        }

    api_key = os.environ.get("EXCHANGERATE_API_KEY")
    if not api_key:
        return {
            "fetched": 0,
            "errors": ["EXCHANGERATE_API_KEY environment variable is not set"],
        }

    fetched = 0
    errors: list[str] = []
    today = _today_iso()

    # Group pairs by base currency to minimize API calls
    bases: dict[str, list[str]] = {}
    for base, quote in pairs:
        bases.setdefault(base.upper(), []).append(quote.upper())

    try:
        with httpx.Client(timeout=30) as client:
            for base_currency, quote_currencies in bases.items():
                try:
                    resp = client.get(
                        f"{_EXCHANGERATE_BASE_URL}/{api_key}/latest/{base_currency}"
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    for q in quote_currencies:
                        errors.append(f"{base_currency}/{q}: API error — {exc}")
                    continue

                rates = data.get("conversion_rates", {})
                for quote_currency in quote_currencies:
                    rate_val = rates.get(quote_currency)
                    if rate_val is None:
                        errors.append(
                            f"{base_currency}/{quote_currency}: rate not available"
                        )
                        continue

                    rate_dec = Decimal(str(rate_val))
                    store_price(
                        db,
                        commodity=base_currency,
                        currency=quote_currency,
                        price=rate_dec,
                        date=today,
                        source="forex",
                    )
                    fetched += 1
    except Exception as exc:
        errors.append(f"Forex fetch error: {exc}")

    return {"fetched": fetched, "errors": errors}


def manual_price(
    db: Database,
    commodity: str,
    currency: str,
    price: str,
    date: str,
) -> None:
    """Record a manual price entry for unlisted or private assets."""
    price_dec = Decimal(price)
    store_price(
        db,
        commodity=commodity,
        currency=currency,
        price=price_dec,
        date=date,
        source="manual",
    )


def fetch_prices(
    db: Database,
    symbols: list[str] | None = None,
    coins: list[str] | None = None,
    forex_pairs: list[tuple[str, str]] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Unified entry point that delegates to individual fetchers and refreshes summaries."""
    combined: dict[str, dict] = {}
    all_commodities: set[str] = set()

    if symbols:
        result = fetch_stock_prices(db, symbols, settings=settings)
        combined["stocks"] = result
        if result["fetched"] > 0:
            all_commodities.update(s.upper() for s in symbols)

    if coins:
        result = fetch_crypto_prices(db, coins, settings=settings)
        combined["crypto"] = result
        if result["fetched"] > 0:
            all_commodities.update(c.upper() for c in coins)

    if forex_pairs:
        result = fetch_forex_rates(db, forex_pairs, settings=settings)
        combined["forex"] = result
        if result["fetched"] > 0:
            for base, quote in forex_pairs:
                all_commodities.add(base.upper())

    total_fetched = sum(r.get("fetched", 0) for r in combined.values())
    all_errors = []
    for r in combined.values():
        all_errors.extend(r.get("errors", []))

    if total_fetched > 0:
        context = RefreshContext(
            affected_commodities=all_commodities,
            prices_updated=True,
        )
        SummaryRegistry.refresh_all(db, context)

    return {
        "fetched": total_fetched,
        "errors": all_errors,
        "details": combined,
    }
