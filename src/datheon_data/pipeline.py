"""Cleaning, adjustment, returns, and statistical diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

REQUIRED = ("open", "high", "low", "close", "adjusted_close", "volume")


def prepare_bars(raw: pd.DataFrame, symbol: str, frequency: str, source: str) -> pd.DataFrame:
    """Return validated bars with vendor-adjusted OHLC and per-symbol log returns.

    Daily Yahoo/Alpha bars provide adjusted close. The close adjustment factor is
    applied to the other OHLC fields. Alpha hourly OHLC is already adjusted.
    """
    if frequency not in {"daily", "hourly"}:
        raise ValueError("frequency must be daily or hourly")
    missing = set(REQUIRED) - set(raw.columns)
    if missing:
        raise ValueError(f"{symbol}: missing columns: {sorted(missing)}")
    if raw.empty:
        raise ValueError(f"{symbol}: no bars in requested range")
    if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
        raise ValueError(f"{symbol}: timestamps must be timezone-aware")
    if raw.index.has_duplicates:
        raise ValueError(f"{symbol}: duplicate timestamps")

    bars = raw.sort_index().copy()
    bars.index = bars.index.tz_convert("UTC")
    bars.index.name = "timestamp"
    for field in REQUIRED:
        bars[field] = pd.to_numeric(bars[field], errors="raise").astype(float)
    values = bars[list(REQUIRED)].to_numpy()
    if not np.isfinite(values).all():
        raise ValueError(f"{symbol}: non-finite OHLCV or adjusted close")
    if (bars[["open", "high", "low", "close", "adjusted_close"]] <= 0).any().any():
        raise ValueError(f"{symbol}: non-positive prices")
    if (bars["volume"] < 0).any():
        raise ValueError(f"{symbol}: negative volume")
    if ((bars["high"] < bars[["open", "close", "low"]].max(axis=1)) |
            (bars["low"] > bars[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError(f"{symbol}: inconsistent OHLC range")

    factor = bars["adjusted_close"] / bars["close"]
    for field in ("open", "high", "low"):
        bars[f"adjusted_{field}"] = bars[field] * factor
    bars["adjustment_factor"] = factor
    bars["log_return"] = np.log(bars["adjusted_close"]).diff()
    bars["simple_return"] = bars["adjusted_close"].pct_change()
    bars["symbol"] = symbol
    bars["frequency"] = frequency
    bars["source"] = source
    for field in ("dividend", "split_ratio"):
        if field not in bars:
            bars[field] = np.nan
    return bars[[
        "symbol", "frequency", "source", "open", "high", "low", "close", "volume",
        "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close",
        "adjustment_factor", "dividend", "split_ratio", "simple_return", "log_return",
    ]]


def stationarity_report(bars: pd.DataFrame) -> dict[str, object]:
    """ADF tests the null of a unit root; report evidence, never assume stationarity."""
    series = bars["log_return"].replace([np.inf, -np.inf], np.nan).dropna()
    result: dict[str, object] = {"observations": int(len(series)), "adf_statistic": None,
                                 "p_value": None, "lags": None, "stationary_at_5pct": None}
    if len(series) < 30 or series.nunique() < 3:
        result["status"] = "insufficient_variation_or_observations"
        return result
    try:
        statistic, p_value, lags, _, _, _ = adfuller(series.to_numpy(), autolag="AIC")
    except (ValueError, np.linalg.LinAlgError) as exc:
        result["status"] = f"test_failed: {exc}"
        return result
    result.update(adf_statistic=float(statistic), p_value=float(p_value),
                  lags=int(lags), stationary_at_5pct=bool(p_value < 0.05), status="ok")
    return result
