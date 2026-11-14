"""Performance ratios, drawdown diagnostics, and bootstrap equity paths."""

from __future__ import annotations

from math import ceil, isfinite, sqrt

import numpy as np
import pandas as pd


def _ratio(numerator: float, denominator: float) -> float | None:
    value = numerator / denominator if denominator > 0 else float("nan")
    return float(value) if isfinite(value) else None


def performance_metrics(curve: pd.DataFrame, initial_capital: float,
                        periods_per_year: float, risk_free_annual: float = 0.0) -> dict[str, object]:
    """Compute annualized ratios from net returns, including all simulated costs."""
    if (not all(isfinite(value) for value in (initial_capital, periods_per_year, risk_free_annual)) or
            initial_capital <= 0 or periods_per_year <= 0 or risk_free_annual <= -1):
        raise ValueError("Invalid initial capital, annualization, or risk-free rate")
    if curve.empty or not {"equity", "net_return", "drawdown"}.issubset(curve):
        raise ValueError("Curve requires equity, net_return, and drawdown")
    returns = curve["net_return"].to_numpy(dtype=float)
    equity = curve["equity"].to_numpy(dtype=float)
    drawdown = curve["drawdown"].to_numpy(dtype=float)
    if not (np.isfinite(returns).all() and np.isfinite(equity).all() and np.isfinite(drawdown).all()):
        raise ValueError("Curve contains non-finite performance values")
    if (equity < 0).any() or (returns < -1).any():
        raise ValueError("Equity or returns are outside supported bounds")
    per_period_rf = (1 + risk_free_annual) ** (1 / periods_per_year) - 1
    excess = returns - per_period_rf
    excess_std = float(np.std(excess, ddof=1)) if len(excess) > 1 else 0.0
    downside = float(np.sqrt(np.mean(np.minimum(excess, 0) ** 2)))
    mean_excess = float(np.mean(excess))
    annual_return = float((equity[-1] / initial_capital) ** (periods_per_year / len(equity)) - 1)
    maximum_drawdown = float(-np.min(drawdown))
    duration = 0
    maximum_duration = 0
    for value in drawdown:
        duration = duration + 1 if value < 0 else 0
        maximum_duration = max(maximum_duration, duration)
    result: dict[str, object] = {
        "bars": len(equity), "initial_capital": initial_capital,
        "ending_equity": float(equity[-1]),
        "total_return": float(equity[-1] / initial_capital - 1),
        "annualized_return": annual_return,
        "annualized_volatility": float(np.std(returns, ddof=1) * sqrt(periods_per_year)) if len(returns) > 1 else None,
        "sharpe_ratio": _ratio(mean_excess * sqrt(periods_per_year), excess_std),
        "sortino_ratio": _ratio(mean_excess * sqrt(periods_per_year), downside),
        "calmar_ratio": _ratio(annual_return, maximum_drawdown),
        "maximum_drawdown": maximum_drawdown,
        "maximum_drawdown_duration_bars": maximum_duration,
        "risk_free_annual": risk_free_annual,
        "periods_per_year": periods_per_year,
    }
    for column in ("spread_cost", "linear_impact_cost", "sqrt_impact_cost", "commission", "borrow_fee"):
        if column in curve:
            result[f"total_{column}"] = float(curve[column].sum())
    if "fill_shares" in curve and "reference_open" in curve:
        result["total_traded_notional"] = float((curve["fill_shares"].abs() * curve["reference_open"]).sum())
    if "status" in curve:
        result["ruined_in_backtest"] = bool(curve["status"].eq("ruin").any())
    return result


def monte_carlo_equity(returns: pd.Series | np.ndarray, initial_capital: float,
                       paths: int = 1000, horizon: int | None = None,
                       block_size: int = 5, ruin_fraction: float = 0.5,
                       seed: int = 42) -> tuple[dict[str, object], pd.DataFrame]:
    """Circular block-bootstrap net returns; ruin means ever crossing a loss threshold.

    This is conditional resampling of the observed strategy returns, not a
    forward probability forecast. The source returns should already include
    execution costs. Sample paths and pointwise quantiles are returned.
    """
    observed = np.asarray(returns, dtype=float)
    if observed.ndim != 1 or len(observed) < 2 or not np.isfinite(observed).all():
        raise ValueError("Monte Carlo requires at least two finite returns")
    if (observed < -1).any() or initial_capital <= 0:
        raise ValueError("Returns cannot be below -100% and capital must be positive")
    horizon = len(observed) if horizon is None else horizon
    if paths < 1 or horizon < 1 or block_size < 1 or not 0 < ruin_fraction < 1:
        raise ValueError("Invalid Monte Carlo paths, horizon, block size, or ruin fraction")
    rng = np.random.default_rng(seed)
    blocks = ceil(horizon / block_size)
    starts = rng.integers(0, len(observed), size=(paths, blocks))
    offsets = np.arange(block_size)
    indexes = ((starts[:, :, None] + offsets) % len(observed)).reshape(paths, -1)[:, :horizon]
    sampled = observed[indexes]
    with np.errstate(over="ignore", invalid="ignore"):
        path_equity = initial_capital * np.cumprod(1 + sampled, axis=1)
    path_equity = np.column_stack((np.full(paths, initial_capital), path_equity))
    if not np.isfinite(path_equity).all():
        raise ValueError("Monte Carlo equity overflowed; inspect extreme input returns")
    threshold = initial_capital * ruin_fraction
    ruined = (path_equity <= threshold).any(axis=1)
    terminal = path_equity[:, -1]
    quantiles = np.quantile(path_equity, [0.05, 0.5, 0.95], axis=0)
    curves = pd.DataFrame({"step": np.arange(horizon + 1),
                           "p05": quantiles[0], "p50": quantiles[1], "p95": quantiles[2]})
    for i in range(min(paths, 10)):
        curves[f"sample_{i:02d}"] = path_equity[i]
    summary: dict[str, object] = {
        "method": "circular_moving_block_bootstrap",
        "paths": paths, "horizon_bars": horizon, "block_size": block_size,
        "seed": seed, "ruin_fraction_of_initial_capital": ruin_fraction,
        "probability_of_ruin": float(np.mean(ruined)),
        "terminal_equity_p05": float(np.quantile(terminal, 0.05)),
        "terminal_equity_p50": float(np.quantile(terminal, 0.50)),
        "terminal_equity_p95": float(np.quantile(terminal, 0.95)),
    }
    return summary, curves
