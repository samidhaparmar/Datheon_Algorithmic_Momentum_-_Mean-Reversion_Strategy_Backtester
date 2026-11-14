"""Single-asset, next-open execution simulation with explicit trading costs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, sqrt

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExecutionConfig:
    initial_capital: float = 100_000.0
    allocation: float = 0.95
    half_spread_bps: float = 2.5
    linear_impact_bps: float = 20.0
    sqrt_impact_bps: float = 30.0
    max_participation: float = 0.05
    commission_per_share: float = 0.005
    minimum_commission: float = 1.0
    annual_borrow_rate: float = 0.03
    periods_per_year: float = 252.0

    def validate(self) -> None:
        values = asdict(self)
        if not all(isfinite(value) for value in values.values()):
            raise ValueError("Execution parameters must be finite")
        if self.initial_capital <= 0 or self.periods_per_year <= 0:
            raise ValueError("Capital and periods per year must be positive")
        if not 0 < self.allocation <= 1 or not 0 < self.max_participation <= 1:
            raise ValueError("Allocation and participation must be in (0, 1]")
        costs = (self.half_spread_bps, self.linear_impact_bps, self.sqrt_impact_bps,
                 self.commission_per_share, self.minimum_commission, self.annual_borrow_rate)
        if any(value < 0 for value in costs):
            raise ValueError("Costs and borrow rate cannot be negative")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def _validate_inputs(bars: pd.DataFrame, signals: pd.DataFrame, strategy: str) -> str:
    column = {"momentum": "momentum_position", "mean_reversion": "mean_reversion_position"}.get(strategy)
    if column is None:
        raise ValueError("Strategy must be momentum or mean_reversion")
    if bars.empty or not bars.index.equals(signals.index):
        raise ValueError("Bars and signals must have identical, nonempty timestamps")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("Bar timestamps must be timezone-aware")
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("Bar timestamps must be unique and sorted")
    required_bars = {"adjusted_open", "adjusted_close", "volume"}
    if (not required_bars.issubset(bars) or column not in signals or
            "information_cutoff" not in signals or "known_adjusted_close" not in signals):
        raise ValueError("Bars or signals are missing required columns")
    for field in required_bars:
        values = pd.to_numeric(bars[field], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any() or (field != "volume" and (values == 0).any()):
            raise ValueError(f"Invalid {field} values")
    target = signals[column]
    if target.isna().any() or not target.isin([-1, 0, 1]).all():
        raise ValueError("Target positions must be -1, 0, or 1")
    if int(target.iloc[0]) != 0:
        raise ValueError("First decision must be flat because no prior bar is available")
    cutoffs = signals["information_cutoff"]
    if pd.notna(cutoffs.iloc[0]):
        raise ValueError("First information cutoff must be null")
    for i in range(1, len(bars)):
        if cutoffs.iloc[i] != bars.index[i - 1]:
            raise ValueError("Signal information cutoff must equal the preceding observed bar")
    known = pd.to_numeric(signals["known_adjusted_close"], errors="raise").to_numpy(dtype=float)
    expected = bars["adjusted_close"].shift(1).to_numpy(dtype=float)
    if not np.allclose(known, expected, rtol=1e-10, atol=1e-10, equal_nan=True):
        raise ValueError("Signals were not generated from these adjusted closes")
    return column


def simulate_execution(bars: pd.DataFrame, signals: pd.DataFrame, strategy: str,
                       config: ExecutionConfig | None = None) -> pd.DataFrame:
    """Trade target-state changes at the current adjusted open, mark at close.

    Previous-bar volume limits fills and determines impact. Unfilled target shares
    remain pending; unchanged target states do not rebalance continuously.
    Adjusted OHLC is a synthetic total-return price basis, so dividends/splits
    are already incorporated and must not be credited separately.
    """
    config = config or ExecutionConfig()
    config.validate()
    target_column = _validate_inputs(bars, signals, strategy)
    cash = config.initial_capital
    shares = 0.0
    desired_shares = 0.0
    last_target = 0
    prior_equity = config.initial_capital
    ruined = False
    records: list[dict[str, object]] = []
    for i, timestamp in enumerate(bars.index):
        opening = float(bars["adjusted_open"].iloc[i])
        closing = float(bars["adjusted_close"].iloc[i])
        previous_volume = float(bars["volume"].iloc[i - 1]) if i else 0.0
        target = int(signals[target_column].iloc[i])
        borrow_fee = 0.0
        fill_shares = 0.0
        fill_price = np.nan
        participation = 0.0
        spread_cost = 0.0
        linear_cost = 0.0
        sqrt_cost = 0.0
        commission = 0.0
        status = "ok"
        equity_open = 0.0
        if not ruined:
            if i and shares < 0:
                borrow_fee = abs(shares) * float(bars["adjusted_close"].iloc[i - 1]) * (
                    config.annual_borrow_rate / config.periods_per_year)
                cash -= borrow_fee
            equity_open = cash + shares * opening
            if equity_open <= 0:
                ruined = True
            else:
                if target != last_target:
                    desired_shares = target * config.allocation * equity_open / opening
                    last_target = target
                request = desired_shares - shares
                if previous_volume > 0 and abs(request) > 1e-10:
                    fill_shares = float(np.sign(request) * min(abs(request),
                                                               config.max_participation * previous_volume))
                    participation = abs(fill_shares) / previous_volume
                    linear_bps = config.linear_impact_bps * participation
                    sqrt_bps = config.sqrt_impact_bps * sqrt(participation)
                    side = np.sign(fill_shares)
                    fill_price = opening * (1 + side * (
                        config.half_spread_bps + linear_bps + sqrt_bps) / 10_000)
                    notional = abs(fill_shares) * opening
                    spread_cost = notional * config.half_spread_bps / 10_000
                    linear_cost = notional * linear_bps / 10_000
                    sqrt_cost = notional * sqrt_bps / 10_000
                    commission = max(config.minimum_commission,
                                     config.commission_per_share * abs(fill_shares))
                    cash -= fill_shares * fill_price + commission
                    shares += fill_shares
            if ruined:
                cash = 0.0
                shares = 0.0
                status = "ruin"
        else:
            status = "ruined"
        equity = max(0.0, cash + shares * closing) if not ruined else 0.0
        if equity <= 0 and not ruined:
            ruined = True
            cash = 0.0
            shares = 0.0
            equity = 0.0
            status = "ruin"
        net_return = equity / prior_equity - 1 if prior_equity > 0 else 0.0
        prior_equity = equity
        records.append({
            "strategy": strategy, "target_position": target,
            "actual_shares": shares, "actual_side": int(np.sign(shares)),
            "pending_shares": 0.0 if ruined else desired_shares - shares,
            "reference_open": opening, "mark_close": closing,
            "prior_volume": previous_volume, "fill_shares": fill_shares,
            "fill_price": fill_price, "participation": participation,
            "spread_cost": spread_cost, "linear_impact_cost": linear_cost,
            "sqrt_impact_cost": sqrt_cost, "commission": commission,
            "borrow_fee": borrow_fee, "cash": cash, "equity_open": equity_open,
            "equity": equity, "net_return": net_return, "status": status,
            "information_cutoff": signals["information_cutoff"].iloc[i],
        })
    curve = pd.DataFrame(records, index=bars.index)
    curve.index.name = "timestamp"
    peak = np.maximum.accumulate(np.r_[config.initial_capital, curve["equity"].to_numpy()])[1:]
    curve["drawdown"] = curve["equity"].to_numpy() / peak - 1
    if "symbol" in bars:
        curve["symbol"] = bars["symbol"].iloc[0]
    return curve
