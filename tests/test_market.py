"""Tests for market data — price fetch mock, cache TTL, manual entry, Price directive writing."""

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from personalfinance.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def invest_env(tmp_path):
    ledger = tmp_path / "main.beancount"
    shutil.copy(FIXTURES / "investments.beancount", ledger)
    prices = tmp_path / "prices.beancount"
    prices.write_text('; Price directives\noption "operating_currency" "USD"\n')
    load_config(tmp_path)
    return tmp_path


class TestManualPrices:
    def test_manual_price_entry(self, invest_env):
        from personalfinance.market.fetcher import fetch_prices
        result = fetch_prices(
            commodities=[],
            manual_prices={"HOUSE": "550000"},
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "ok"
        assert len(result["prices"]) == 1
        assert result["prices"][0]["commodity"] == "HOUSE"
        assert result["prices"][0]["source"] == "manual"


class TestPriceCache:
    def test_cache_set_and_get(self, invest_env):
        from personalfinance.market.fetcher import _PriceCache
        cache = _PriceCache(invest_env / ".test_cache.db", ttl_hours=1)
        cache.set("TEST", {"commodity": "TEST", "price": "100.00"})
        result = cache.get("TEST")
        assert result is not None
        assert result["price"] == "100.00"

    def test_cache_miss(self, invest_env):
        from personalfinance.market.fetcher import _PriceCache
        cache = _PriceCache(invest_env / ".test_cache2.db", ttl_hours=1)
        result = cache.get("NONEXISTENT")
        assert result is None


class TestPriceDirectiveWriting:
    def test_writes_price_directive(self, invest_env):
        from personalfinance.market.fetcher import fetch_prices
        result = fetch_prices(
            commodities=[],
            manual_prices={"GOLD": "2000.50"},
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["directives_written"] == 1
        prices_content = (invest_env / "prices.beancount").read_text()
        assert "GOLD" in prices_content
        assert "2000.50" in prices_content


class TestFetchWithMock:
    @patch("personalfinance.market.fetcher._fetch_stock_price")
    def test_stock_fetch_mock(self, mock_fetch, invest_env):
        mock_fetch.return_value = Decimal("210.50")
        from personalfinance.market.fetcher import fetch_prices
        result = fetch_prices(
            commodities=["AAPL"],
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "ok"
        assert len(result["prices"]) == 1
        assert result["prices"][0]["price"] == "210.50"
        mock_fetch.assert_called_once_with("AAPL")

    @patch("personalfinance.market.fetcher._fetch_stock_price")
    def test_stock_fetch_error(self, mock_fetch, invest_env):
        mock_fetch.side_effect = Exception("Network error")
        from personalfinance.market.fetcher import fetch_prices
        result = fetch_prices(
            commodities=["FAIL"],
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "ok"
        assert len(result["errors"]) == 1
        assert "Network error" in result["errors"][0]["error"]


class TestEmptyCommodities:
    def test_no_commodities(self, invest_env):
        from personalfinance.market.fetcher import fetch_prices
        result = fetch_prices(
            commodities=[],
            ledger_path=str(invest_env / "main.beancount"),
        )
        assert result["status"] == "ok"
        assert result["message"] == "No commodities to fetch prices for."
