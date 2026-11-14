"""Generate research signals from Task 1 Parquet bars."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .signals import SignalConfig, build_signals


def _inputs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted([*path.glob("daily/*.parquet"), *path.glob("hourly/*.parquet")])
    return []


def run(input_path: Path, output_path: Path, config: SignalConfig) -> int:
    config.validate()
    files = _inputs(input_path)
    if not files:
        raise ValueError(f"No daily/hourly Parquet bars found at {input_path}")
    output_path.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "information_rule": "row t uses adjusted closes through the preceding observed bar only",
        "parameters": config.to_dict(), "results": [],
    }
    failures = 0
    for file in files:
        item: dict[str, object] = {"input": str(file)}
        try:
            bars = pd.read_parquet(file)
            signals = build_signals(bars, config)
            frequency = str(bars["frequency"].iloc[0]) if "frequency" in bars else file.parent.name
            if frequency not in {"daily", "hourly"}:
                raise ValueError("Input frequency must be daily or hourly")
            symbol = str(bars["symbol"].iloc[0]) if "symbol" in bars else file.stem
            if symbol != file.stem:
                raise ValueError("Symbol column does not match input filename")
            destination_dir = output_path / frequency
            destination_dir.mkdir(exist_ok=True)
            destination = destination_dir / file.name
            temporary = destination.with_suffix(".parquet.tmp")
            signals.to_parquet(temporary, index=True)
            temporary.replace(destination)
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            item.update(status="ok", symbol=symbol, frequency=frequency,
                        rows=len(signals), momentum_ready_bars=int(signals["momentum_ready"].sum()),
                        mean_reversion_ready_bars=int(signals["mean_reversion_ready"].sum()),
                        source_sha256=digest, output=str(destination))
            print(f"OK {frequency} {symbol}: {len(signals)} decision rows", flush=True)
        except (ValueError, KeyError, OSError, ImportError) as exc:
            failures += 1
            item.update(status="error", error=str(exc))
            print(f"ERROR {file}: {exc}", file=sys.stderr, flush=True)
        manifest["results"].append(item)
    (output_path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate causal momentum and mean-reversion signals")
    parser.add_argument("--input", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("data/signals"))
    defaults = SignalConfig()
    for name, value in defaults.to_dict().items():
        parser.add_argument("--" + name.replace("_", "-"), type=type(value), default=value)
    args = parser.parse_args()
    config = SignalConfig(**{name: getattr(args, name) for name in defaults.to_dict()})
    try:
        raise SystemExit(run(args.input, args.output, config))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
