"""Run execution and risk analytics from prepared bars and causal signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .execution import ExecutionConfig, simulate_execution
from .risk import monte_carlo_equity, performance_metrics


def _bar_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted([*path.glob("daily/*.parquet"), *path.glob("hourly/*.parquet")])
    return []


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=True)
    temporary.replace(path)


def run(bars_path: Path, signals_path: Path, output_path: Path, strategies: list[str],
        settings: dict[str, float], risk_free_annual: float, mc_paths: int,
        mc_horizon: int | None, mc_block_size: int, ruin_fraction: float, seed: int) -> int:
    files = _bar_files(bars_path)
    if not files:
        raise ValueError(f"No prepared Parquet bars found at {bars_path}")
    if not strategies or any(name not in {"momentum", "mean_reversion"} for name in strategies):
        raise ValueError("Choose momentum, mean_reversion, or both strategies")
    output_path.mkdir(parents=True, exist_ok=True)
    expected_bar_hashes: dict[tuple[str, str], str] = {}
    signal_manifest = signals_path / "manifest.json"
    if signal_manifest.exists():
        for item in json.loads(signal_manifest.read_text(encoding="utf-8")).get("results", []):
            if item.get("status") == "ok" and item.get("source_sha256"):
                expected_bar_hashes[(item["frequency"], item["symbol"])] = item["source_sha256"]
    manifest: dict[str, object] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "bars_path": str(bars_path), "signals_path": str(signals_path),
        "strategies": strategies, "results": [],
    }
    failures = 0
    for bar_file in files:
        frequency = bar_file.parent.name
        if frequency not in {"daily", "hourly"}:
            failures += 1
            manifest["results"].append({"input": str(bar_file), "status": "error",
                                         "error": "Frequency directory must be daily or hourly"})
            continue
        signal_file = signals_path / frequency / bar_file.name
        for strategy in strategies:
            item: dict[str, object] = {"symbol": bar_file.stem, "frequency": frequency,
                                       "strategy": strategy, "bars_input": str(bar_file),
                                       "signals_input": str(signal_file)}
            try:
                bar_digest = hashlib.sha256(bar_file.read_bytes()).hexdigest()
                expected_digest = expected_bar_hashes.get((frequency, bar_file.stem))
                if expected_digest is not None and bar_digest != expected_digest:
                    raise ValueError("Prepared bars changed after signals were generated; regenerate signals")
                bars = pd.read_parquet(bar_file)
                signals = pd.read_parquet(signal_file)
                if "symbol" in bars and (bars["symbol"].nunique() != 1 or bars["symbol"].iloc[0] != bar_file.stem):
                    raise ValueError("Bar symbol does not match filename")
                params = dict(settings)
                if params["periods_per_year"] is None:
                    params["periods_per_year"] = 252.0 if frequency == "daily" else 252.0 * 6.5
                config = ExecutionConfig(**params)
                curve = simulate_execution(bars, signals, strategy, config)
                metrics = performance_metrics(curve, config.initial_capital,
                                              config.periods_per_year, risk_free_annual)
                mc_summary, mc_curves = monte_carlo_equity(
                    curve["net_return"], config.initial_capital, paths=mc_paths,
                    horizon=mc_horizon, block_size=mc_block_size,
                    ruin_fraction=ruin_fraction, seed=seed)
                destination = output_path / frequency / bar_file.stem / strategy
                destination.mkdir(parents=True, exist_ok=True)
                curve_path = destination / "equity_curve.parquet"
                mc_path = destination / "monte_carlo.parquet"
                report_path = destination / "risk_report.json"
                _write_parquet(curve, curve_path)
                _write_parquet(mc_curves, mc_path)
                report = {
                    "symbol": bar_file.stem, "frequency": frequency, "strategy": strategy,
                    "execution_parameters": config.to_dict(), "risk_free_annual": risk_free_annual,
                    "metrics": metrics, "monte_carlo": mc_summary,
                    "bars_sha256": bar_digest,
                    "signals_sha256": hashlib.sha256(signal_file.read_bytes()).hexdigest(),
                }
                report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
                item.update(status="ok", bars=len(curve), ending_equity=metrics["ending_equity"],
                            risk_report=str(report_path), equity_curve=str(curve_path),
                            monte_carlo_curves=str(mc_path))
                print(f"OK {frequency} {bar_file.stem} {strategy}: {len(curve)} bars", flush=True)
            except (ValueError, KeyError, OSError, ImportError) as exc:
                failures += 1
                item.update(status="error", error=str(exc))
                print(f"ERROR {frequency} {bar_file.stem} {strategy}: {exc}", file=sys.stderr, flush=True)
            manifest["results"].append(item)
    (output_path / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate execution and calculate risk")
    parser.add_argument("--bars", type=Path, default=Path("data/processed"))
    parser.add_argument("--signals", type=Path, default=Path("data/signals"))
    parser.add_argument("--output", type=Path, default=Path("data/backtests"))
    parser.add_argument("--strategy", choices=["momentum", "mean_reversion", "both"], default="both")
    defaults = ExecutionConfig().to_dict()
    for name, value in defaults.items():
        parser.add_argument("--" + name.replace("_", "-"), type=float,
                            default=None if name == "periods_per_year" else value)
    parser.add_argument("--risk-free-annual", type=float, default=0.0)
    parser.add_argument("--mc-paths", type=int, default=1000)
    parser.add_argument("--mc-horizon", type=int)
    parser.add_argument("--mc-block-size", type=int, default=5)
    parser.add_argument("--ruin-fraction", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    strategies = ["momentum", "mean_reversion"] if args.strategy == "both" else [args.strategy]
    settings = {name: getattr(args, name) for name in defaults}
    try:
        raise SystemExit(run(args.bars, args.signals, args.output, strategies, settings,
                             args.risk_free_annual, args.mc_paths, args.mc_horizon,
                             args.mc_block_size, args.ruin_fraction, args.seed))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
