"""Pure research helpers used by the Streamlit dashboard and report generator."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .execution import ExecutionConfig, simulate_execution
from .risk import performance_metrics
from .signals import SignalConfig, build_signals


def curve_from_returns(returns: pd.Series, initial_capital: float) -> pd.DataFrame:
    """Rebase a contiguous return segment for honest train/test metrics."""
    if returns.empty or initial_capital <= 0:
        raise ValueError("Returns and initial capital are required")
    values = returns.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < -1).any():
        raise ValueError("Returns must be finite and at least -100%")
    equity = initial_capital * np.cumprod(1 + values)
    peaks = np.maximum.accumulate(np.r_[initial_capital, equity])[1:]
    return pd.DataFrame({"equity": equity, "net_return": values,
                         "drawdown": equity / peaks - 1}, index=returns.index)


def aligned_benchmark(strategy_equity: pd.Series, benchmark_close: pd.Series,
                      initial_capital: float) -> pd.DataFrame:
    """Normalize a buy-and-hold benchmark at the first common close."""
    if strategy_equity.empty or benchmark_close.empty:
        raise ValueError("Strategy and benchmark series are required")
    benchmark = benchmark_close.sort_index().reindex(strategy_equity.index, method="ffill")
    if benchmark.isna().any() or (benchmark <= 0).any():
        raise ValueError("Benchmark does not cover the strategy timestamps")
    return pd.DataFrame({"strategy": strategy_equity.astype(float),
                         "benchmark": initial_capital * benchmark / float(benchmark.iloc[0])},
                        index=strategy_equity.index)


def rolling_drawdown(equity: pd.Series, window: int = 63) -> pd.Series:
    if window < 2 or equity.empty or (equity < 0).any() or equity.iloc[0] <= 0:
        raise ValueError("Rolling drawdown requires nonnegative equity and window >= 2")
    return equity / equity.rolling(window, min_periods=1).max() - 1


def candidate_configs(strategy: str, base: SignalConfig,
                      first: list[int], second: list[int | float]) -> list[SignalConfig]:
    """Small, deterministic two-dimensional grid for one strategy at a time."""
    candidates: list[SignalConfig] = []
    for a in sorted(set(first)):
        for b in sorted(set(second)):
            if strategy == "momentum" and a < b:
                candidates.append(replace(base, ma_fast=a, ma_slow=int(b)))
            elif strategy == "mean_reversion":
                candidates.append(replace(base, bb_window=a, bb_width=float(b)))
    if not candidates or len(candidates) > 25:
        raise ValueError("Choose 1-25 valid parameter combinations")
    for config in candidates:
        config.validate()
    return candidates


def optimize_train_test(bars: pd.DataFrame, strategy: str,
                        candidates: list[SignalConfig], execution: ExecutionConfig,
                        train_fraction: float = 0.70,
                        risk_free_annual: float = 0.0) -> dict[str, object]:
    """Select on the earlier training segment; assess only the winner on holdout."""
    if not 0.5 <= train_fraction < 0.9 or len(bars) < 50:
        raise ValueError("Use at least 50 bars and a train fraction in [0.5, 0.9)")
    if not candidates:
        raise ValueError("At least one candidate is required")
    split = int(len(bars) * train_fraction)
    leaderboard: list[dict[str, object]] = []
    best_config = None
    best_score = (-float("inf"), -float("inf"))
    for config in candidates:
        signals = build_signals(bars, config)
        curve = simulate_execution(bars, signals, strategy, execution)
        train_curve = curve_from_returns(curve["net_return"].iloc[:split], execution.initial_capital)
        train = performance_metrics(train_curve, execution.initial_capital,
                                    execution.periods_per_year, risk_free_annual)
        sharpe = train["sharpe_ratio"]
        score = (float(sharpe) if sharpe is not None else -float("inf"),
                 float(train["total_return"]))
        row = {"config": config, "train_sharpe": sharpe,
               "train_total_return": train["total_return"],
               "train_max_drawdown": train["maximum_drawdown"]}
        leaderboard.append(row)
        if score > best_score:
            best_score, best_config = score, config
    assert best_config is not None
    best_signals = build_signals(bars, best_config)
    best_curve = simulate_execution(bars, best_signals, strategy, execution)
    test_curve = curve_from_returns(best_curve["net_return"].iloc[split:], execution.initial_capital)
    test = performance_metrics(test_curve, execution.initial_capital,
                               execution.periods_per_year, risk_free_annual)
    return {
        "selected_config": best_config,
        "leaderboard": pd.DataFrame([{**row, "config": str(row["config"].to_dict())}
                                     for row in leaderboard]).sort_values(
                                         ["train_sharpe", "train_total_return"],
                                         ascending=False, na_position="last").reset_index(drop=True),
        "train_metrics": performance_metrics(
            curve_from_returns(best_curve["net_return"].iloc[:split], execution.initial_capital),
            execution.initial_capital, execution.periods_per_year, risk_free_annual),
        "test_metrics": test,
        "split_timestamp": bars.index[split],
        "signals": best_signals, "curve": best_curve,
    }
