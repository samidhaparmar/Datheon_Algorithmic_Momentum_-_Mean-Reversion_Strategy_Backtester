"""Causal momentum and Bollinger Band signals.

Every row is a decision for the bar at its timestamp. Indicators are calculated
from prices shifted by one *observed bar*, so row t uses data through bar t-1.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SignalConfig:
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    ma_fast: int = 20
    ma_slow: int = 50
    bb_window: int = 20
    bb_width: float = 2.0
    volatility_fast: int = 10
    volatility_slow: int = 60
    min_volatility_scale: float = 0.75
    max_volatility_scale: float = 1.50

    def validate(self) -> None:
        integers = (self.macd_fast, self.macd_slow, self.macd_signal,
                    self.ma_fast, self.ma_slow, self.bb_window,
                    self.volatility_fast, self.volatility_slow)
        if any(value < 2 for value in integers):
            raise ValueError("All lookback windows must be at least 2 bars")
        if self.macd_fast >= self.macd_slow or self.ma_fast >= self.ma_slow:
            raise ValueError("Fast MACD and moving-average windows must be shorter than slow windows")
        if self.volatility_fast >= self.volatility_slow:
            raise ValueError("Fast volatility window must be shorter than slow volatility window")
        if not (0 < self.min_volatility_scale <= self.max_volatility_scale):
            raise ValueError("Volatility scale bounds must be positive and ordered")
        if self.bb_width <= 0:
            raise ValueError("Bollinger width must be positive")

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def _validate_prices(bars: pd.DataFrame) -> pd.Series:
    if "adjusted_close" not in bars:
        raise ValueError("Input bars must contain adjusted_close")
    if bars.empty:
        raise ValueError("Input bars are empty")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("Input bars require timezone-aware timestamps")
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("Input timestamps must be unique and sorted")
    price = pd.to_numeric(bars["adjusted_close"], errors="raise").astype(float)
    if not np.isfinite(price.to_numpy()).all() or (price <= 0).any():
        raise ValueError("Adjusted close must be finite and positive")
    return price


def build_signals(bars: pd.DataFrame, config: SignalConfig | None = None) -> pd.DataFrame:
    """Build decision-time indicators and target positions for one symbol.

    Positions: +1 long, -1 short, 0 flat. They are desired exposures for the
    current bar, not filled orders or realized returns. Execution belongs to
    the later simulator, where spread, slippage, and timing are modeled.
    """
    config = config or SignalConfig()
    config.validate()
    price = _validate_prices(bars)
    known_price = price.shift(1)
    result = pd.DataFrame(index=bars.index)
    result.index.name = "timestamp"
    result["information_cutoff"] = bars.index.to_series().shift(1)
    result["known_adjusted_close"] = known_price

    # MACD and dual simple moving averages are aligned with the decision bar.
    fast_ema = known_price.ewm(span=config.macd_fast, adjust=False,
                               min_periods=config.macd_fast).mean()
    slow_ema = known_price.ewm(span=config.macd_slow, adjust=False,
                               min_periods=config.macd_slow).mean()
    result["macd_line"] = fast_ema - slow_ema
    result["macd_signal_line"] = result["macd_line"].ewm(
        span=config.macd_signal, adjust=False, min_periods=config.macd_signal).mean()
    result["macd_histogram"] = result["macd_line"] - result["macd_signal_line"]
    result["ma_fast"] = known_price.rolling(config.ma_fast, min_periods=config.ma_fast).mean()
    result["ma_slow"] = known_price.rolling(config.ma_slow, min_periods=config.ma_slow).mean()
    macd_ready = result[["macd_line", "macd_signal_line"]].notna().all(axis=1)
    ma_ready = result[["ma_fast", "ma_slow"]].notna().all(axis=1)
    result["momentum_ready"] = macd_ready & ma_ready
    macd_spread = result["macd_histogram"]
    ma_spread = result["ma_fast"] - result["ma_slow"]
    result["macd_cross"] = np.select(
        [macd_ready & macd_ready.shift(1, fill_value=False) & (macd_spread > 0) & (macd_spread.shift(1) <= 0),
         macd_ready & macd_ready.shift(1, fill_value=False) & (macd_spread < 0) & (macd_spread.shift(1) >= 0)],
        [1, -1], default=0).astype("int8")
    result["ma_cross"] = np.select(
        [ma_ready & ma_ready.shift(1, fill_value=False) & (ma_spread > 0) & (ma_spread.shift(1) <= 0),
         ma_ready & ma_ready.shift(1, fill_value=False) & (ma_spread < 0) & (ma_spread.shift(1) >= 0)],
        [1, -1], default=0).astype("int8")
    result["momentum_position"] = np.select(
        [result["momentum_ready"] & (macd_spread > 0) & (ma_spread > 0),
         result["momentum_ready"] & (macd_spread < 0) & (ma_spread < 0)],
        [1, -1], default=0).astype("int8")

    # Price volatility sets the Bollinger envelope. A short/long return-volatility
    # ratio widens it in volatile regimes and narrows it in calm regimes.
    known_log_return = np.log(known_price).diff()
    fast_vol = known_log_return.rolling(config.volatility_fast, min_periods=config.volatility_fast).std(ddof=0)
    slow_vol = known_log_return.rolling(config.volatility_slow, min_periods=config.volatility_slow).std(ddof=0)
    volatility_scale = (fast_vol / slow_vol.replace(0, np.nan)).clip(
        config.min_volatility_scale, config.max_volatility_scale)
    result["bb_mid"] = known_price.rolling(config.bb_window, min_periods=config.bb_window).mean()
    result["bb_std"] = known_price.rolling(config.bb_window, min_periods=config.bb_window).std(ddof=0)
    result["bb_width"] = config.bb_width * volatility_scale
    result["bb_upper"] = result["bb_mid"] + result["bb_width"] * result["bb_std"]
    result["bb_lower"] = result["bb_mid"] - result["bb_width"] * result["bb_std"]
    result["mean_reversion_ready"] = result[["bb_mid", "bb_std", "bb_width"]].notna().all(axis=1) & (result["bb_std"] > 0)

    positions: list[int] = []
    actions: list[str] = []
    position = 0
    for known, mid, lower, upper, ready in zip(
        known_price.to_numpy(), result["bb_mid"].to_numpy(),
        result["bb_lower"].to_numpy(), result["bb_upper"].to_numpy(),
        result["mean_reversion_ready"].to_numpy()
    ):
        action = "hold"
        if not ready:
            if position:
                action = "exit_unavailable"
            position = 0
        elif position == 0:
            if known < lower:
                position, action = 1, "enter_long"
            elif known > upper:
                position, action = -1, "enter_short"
        elif position == 1 and known >= mid:
            position, action = 0, "exit_long"
        elif position == -1 and known <= mid:
            position, action = 0, "exit_short"
        positions.append(position)
        actions.append(action)
    result["mean_reversion_position"] = np.array(positions, dtype="int8")
    result["mean_reversion_action"] = actions
    if "symbol" in bars:
        symbols = bars["symbol"].dropna().unique()
        if len(symbols) != 1:
            raise ValueError("Signal input must contain exactly one symbol")
        result["symbol"] = symbols[0]
    if "frequency" in bars:
        frequencies = bars["frequency"].dropna().unique()
        if len(frequencies) != 1:
            raise ValueError("Signal input must contain exactly one frequency")
        result["frequency"] = frequencies[0]
    return result
