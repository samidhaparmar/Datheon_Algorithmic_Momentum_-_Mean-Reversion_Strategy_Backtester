"""Vendor adapters. All timestamps returned here are UTC."""

from __future__ import annotations

import time
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf


class ProviderError(RuntimeError):
    """Market data request failed or returned an unusable response."""


def yahoo_history(symbol: str, start: datetime, end: datetime, frequency: str) -> pd.DataFrame:
    interval = "1d" if frequency == "daily" else "1h"
    try:
        frame = yf.Ticker(symbol).history(
            start=start, end=end, interval=interval, auto_adjust=False,
            actions=True, repair=True, raise_errors=True, timeout=30,
        )
    except Exception as exc:
        raise ProviderError(f"Yahoo request failed for {symbol}: {exc}") from exc
    if frame.empty:
        raise ProviderError(f"Yahoo returned no {frequency} bars for {symbol}")
    frame = frame.rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Adj Close": "adjusted_close", "Volume": "volume",
        "Dividends": "dividend", "Stock Splits": "split_ratio",
    })
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame.index.name = "timestamp"
    return frame


class AlphaVantage:
    """Monthly historical intraday requests; a premium entitlement is required."""

    url = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str, pause_seconds: float = 0.0,
                 session: requests.Session | None = None, cache_dir: Path | None = None):
        if not api_key:
            raise ValueError("ALPHAVANTAGE_API_KEY is required")
        self.api_key = api_key
        self.pause_seconds = pause_seconds
        self.session = session or requests.Session()
        self.cache_dir = cache_dir

    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        # Historical months are immutable enough to cache for long-running jobs.
        # The current month and daily endpoint remain fresh on each run.
        month = params.get("month")
        cacheable = bool(month and month < datetime.utcnow().strftime("%Y-%m"))
        cache_path = None
        if cacheable and self.cache_dir is not None:
            digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
            cache_path = self.cache_dir / f"{digest}.json"
            if cache_path.exists():
                return json.loads(cache_path.read_text(encoding="utf-8"))
        response = self.session.get(self.url, params={**params, "apikey": self.api_key}, timeout=45)
        response.raise_for_status()
        payload = response.json()
        for key in ("Error Message", "Note", "Information"):
            if key in payload:
                raise ProviderError(f"Alpha Vantage: {payload[key]}")
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(cache_path)
        if self.pause_seconds:
            time.sleep(self.pause_seconds)
        return payload

    def daily(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        payload = self._request({
            "function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": symbol.replace("-", "."), "outputsize": "full"
        })
        series = payload.get("Time Series (Daily)")
        if not series:
            raise ProviderError(f"Alpha Vantage returned no daily bars for {symbol}")
        frame = pd.DataFrame.from_dict(series, orient="index").rename(columns={
            "1. open": "open", "2. high": "high", "3. low": "low",
            "4. close": "close", "5. adjusted close": "adjusted_close",
            "6. volume": "volume", "7. dividend amount": "dividend",
            "8. split coefficient": "split_ratio",
        }).apply(pd.to_numeric)
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame.index.name = "timestamp"
        return frame.loc[(frame.index >= start) & (frame.index < end)].sort_index()

    def hourly(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        # The vendor publishes US intraday timestamps in America/New_York.
        months = pd.period_range(start=start.date(), end=(end - pd.Timedelta(microseconds=1)).date(), freq="M")
        parts: list[pd.DataFrame] = []
        for month in months:
            payload = self._request({
                "function": "TIME_SERIES_INTRADAY", "symbol": symbol.replace("-", "."),
                "interval": "60min", "month": str(month), "outputsize": "full",
                "adjusted": "true", "extended_hours": "false",
            })
            series = payload.get("Time Series (60min)")
            if not series:
                raise ProviderError(f"Alpha Vantage returned no hourly bars for {symbol} in {month}")
            part = pd.DataFrame.from_dict(series, orient="index").rename(columns={
                "1. open": "open", "2. high": "high", "3. low": "low",
                "4. close": "close", "5. volume": "volume",
            }).apply(pd.to_numeric)
            local_index = pd.to_datetime(part.index).tz_localize("America/New_York", ambiguous="raise", nonexistent="raise")
            part.index = local_index.tz_convert("UTC")
            parts.append(part)
        frame = pd.concat(parts).sort_index()
        frame.index.name = "timestamp"
        # Intraday endpoint already adjusts OHLC for splits and dividends.
        frame["adjusted_close"] = frame["close"]
        frame["dividend"] = float("nan")  # Not supplied at intraday resolution.
        frame["split_ratio"] = float("nan")
        return frame.loc[(frame.index >= start) & (frame.index < end)]
