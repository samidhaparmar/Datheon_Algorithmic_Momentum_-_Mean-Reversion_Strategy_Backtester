"""Deterministic synthetic bars for dashboard demonstration and documentation."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .pipeline import prepare_bars


def synthetic_bars(symbol: str, start: str, end: str, frequency: str) -> pd.DataFrame:
    """Generate reproducible prices; never present these as historical market data."""
    days = pd.bdate_range(start, end, tz="UTC")
    if frequency == "daily":
        index = days
    elif frequency == "hourly":
        index = pd.DatetimeIndex([day + pd.Timedelta(hours=14, minutes=30) + pd.Timedelta(hours=j)
                                  for day in days for j in range(7)])
    else:
        raise ValueError("Frequency must be daily or hourly")
    if len(index) < 2:
        raise ValueError("The selected date range contains too few bars")
    seed = int(hashlib.sha256(f"{symbol}:{frequency}".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    volatility = 0.011 if frequency == "daily" else 0.004
    drift = 0.00025 if frequency == "daily" else 0.00004
    shocks = rng.normal(drift, volatility, len(index))
    close = 100 * np.exp(np.cumsum(shocks))
    opening = np.r_[100.0, close[:-1]] * np.exp(rng.normal(0, volatility / 4, len(index)))
    high = np.maximum(opening, close) * (1 + rng.uniform(0, 0.005, len(index)))
    low = np.minimum(opening, close) * (1 - rng.uniform(0, 0.005, len(index)))
    raw = pd.DataFrame({"open": opening, "high": high, "low": low,
                        "close": close, "adjusted_close": close,
                        "volume": rng.integers(150_000, 1_500_000, len(index))}, index=index)
    raw.index.name = "timestamp"
    return prepare_bars(raw, symbol, frequency, "synthetic_demo")
