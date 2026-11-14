"""Rebuild the methodology whitepaper and clearly synthetic example tearsheet."""

from __future__ import annotations

import json
from pathlib import Path

from datheon_data.dashboard import aligned_benchmark
from datheon_data.demo import synthetic_bars
from datheon_data.execution import ExecutionConfig, simulate_execution
from datheon_data.reports import render_tearsheet_pdf, render_whitepaper_pdf
from datheon_data.risk import monte_carlo_equity, performance_metrics
from datheon_data.signals import SignalConfig, build_signals


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = root / "docs"
    whitepaper = (docs / "risk_whitepaper.md").read_text(encoding="utf-8")
    (docs / "risk_whitepaper.pdf").write_bytes(render_whitepaper_pdf(whitepaper))

    start, end = "2023-01-01", "2025-12-31"
    bars = synthetic_bars("DEMO", start, end, "daily")
    benchmark = synthetic_bars("BENCH", start, end, "daily")
    signals = build_signals(bars, SignalConfig())
    execution = ExecutionConfig()
    curve = simulate_execution(bars, signals, "momentum", execution)
    metrics = performance_metrics(curve, execution.initial_capital, execution.periods_per_year)
    mc, _ = monte_carlo_equity(curve["net_return"], execution.initial_capital,
                               paths=300, block_size=5, ruin_fraction=0.5, seed=42)
    comparison = aligned_benchmark(curve["equity"], benchmark["adjusted_close"],
                                   execution.initial_capital)
    report = {
        "ticker": "DEMO", "benchmark": "BENCH", "source": "synthetic_demo",
        "synthetic_demo": True, "strategy": "momentum", "frequency": "daily",
        "start": start, "end": end, "signal_parameters": SignalConfig().to_dict(),
        "execution_parameters": execution.to_dict(),
        "performance": metrics, "monte_carlo": mc,
    }
    (docs / "sample_tearsheet.pdf").write_bytes(render_tearsheet_pdf(report, comparison))
    (docs / "sample_tearsheet.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Built risk_whitepaper.pdf and sample_tearsheet.pdf (synthetic demonstration)")


if __name__ == "__main__":
    main()
