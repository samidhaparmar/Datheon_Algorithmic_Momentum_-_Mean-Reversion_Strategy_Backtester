"""Command-line entry point for reproducible equity data ingestion."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from .pipeline import prepare_bars, stationarity_report
from .providers import AlphaVantage, ProviderError, yahoo_history

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def current_sp500_symbols() -> list[str]:
    """Fetch current constituents; callers must not use this as historical membership."""
    response = requests.get(SP500_URL, headers={"User-Agent": "Datheon research data pipeline/0.1"}, timeout=30)
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text), match="Symbol")
    if not tables or "Symbol" not in tables[0]:
        raise ValueError("Could not parse the S&P 500 constituent table")
    return [str(value).replace(".", "-") for value in tables[0]["Symbol"].dropna()]


def parse_symbols(args: argparse.Namespace) -> list[str]:
    if args.sp500_current:
        raw = current_sp500_symbols()
    elif args.universe_csv:
        table = pd.read_csv(args.universe_csv)
        if "symbol" not in table.columns:
            raise ValueError("Universe CSV must have a 'symbol' column")
        raw = table["symbol"].dropna().astype(str).tolist()
    else:
        raw = args.symbols or []
    symbols = list(dict.fromkeys(symbol.strip().upper().replace(".", "-") for symbol in raw))
    if not symbols or any(not re.fullmatch(r"[A-Z0-9^-]+", symbol) for symbol in symbols):
        raise ValueError("Provide valid symbols, --universe-csv, or --sp500-current")
    return symbols


def run(args: argparse.Namespace) -> int:
    if args.years <= 0 or args.alpha_pause < 0:
        raise ValueError("--years must be positive and --alpha-pause cannot be negative")
    end = pd.Timestamp(args.end).tz_localize("UTC") if args.end else pd.Timestamp.now(tz="UTC")
    start = pd.Timestamp(args.start).tz_localize("UTC") if args.start else end - pd.DateOffset(years=args.years)
    if start >= end:
        raise ValueError("start must precede end")
    symbols = parse_symbols(args)
    frequencies = ["daily", "hourly"] if args.frequency == "both" else [args.frequency]
    if "hourly" in frequencies and args.hourly_provider == "yahoo" and start < end - pd.Timedelta(days=60):
        raise ValueError("Yahoo hourly history is limited to approximately 60 days; use Alpha Vantage for a longer range")
    needs_alpha = ("hourly" in frequencies and args.hourly_provider == "alpha") or (
        "daily" in frequencies and args.daily_provider == "alpha")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    alpha = AlphaVantage(os.getenv("ALPHAVANTAGE_API_KEY", ""), args.alpha_pause,
                         cache_dir=out.parent / "raw-cache" / "alpha") if needs_alpha else None
    manifest: dict[str, object] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_inclusive_utc": start.isoformat(), "end_exclusive_utc": end.isoformat(),
        "universe_source": "current_sp500" if args.sp500_current else "csv" if args.universe_csv else "explicit_symbols",
        "survivorship_warning": "Current S&P 500 membership is not point-in-time historical membership" if args.sp500_current else None,
        "symbols_requested": symbols, "results": [],
        "alpha_historical_month_cache": str(out.parent / "raw-cache" / "alpha") if needs_alpha else None,
    }
    failures = 0
    for frequency in frequencies:
        source = args.daily_provider if frequency == "daily" else args.hourly_provider
        directory = out / frequency
        directory.mkdir(exist_ok=True)
        for symbol in symbols:
            item: dict[str, object] = {"symbol": symbol, "frequency": frequency, "source": source}
            try:
                if source == "yahoo":
                    raw = yahoo_history(symbol, start.to_pydatetime(), end.to_pydatetime(), frequency)
                elif frequency == "daily":
                    assert alpha is not None
                    raw = alpha.daily(symbol, start.to_pydatetime(), end.to_pydatetime())
                else:
                    assert alpha is not None
                    raw = alpha.hourly(symbol, start.to_pydatetime(), end.to_pydatetime())
                bars = prepare_bars(raw, symbol, frequency, source)
                target = directory / f"{symbol}.parquet"
                temporary = target.with_suffix(".parquet.tmp")
                bars.to_parquet(temporary, index=True)
                temporary.replace(target)
                item.update(status="ok", rows=len(bars), first_bar_utc=bars.index.min().isoformat(),
                            last_bar_utc=bars.index.max().isoformat(),
                            stationarity=stationarity_report(bars), path=str(target))
                print(f"OK {frequency} {symbol}: {len(bars)} bars", flush=True)
            except (ValueError, ProviderError, requests.RequestException, KeyError) as exc:
                failures += 1
                item.update(status="error", error=str(exc))
                print(f"ERROR {frequency} {symbol}: {exc}", file=sys.stderr, flush=True)
            manifest["results"].append(item)
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Manifest: {manifest_path}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Download, validate, adjust, and test equity OHLCV data")
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument("--symbols", nargs="+", help="Yahoo-style tickers, e.g. AAPL MSFT BRK-B")
    universe.add_argument("--universe-csv", help="CSV with a symbol column")
    universe.add_argument("--sp500-current", action="store_true", help="Use today's S&P 500 members (survivorship bias)")
    parser.add_argument("--frequency", choices=["daily", "hourly", "both"], default="daily")
    parser.add_argument("--daily-provider", choices=["yahoo", "alpha"], default="yahoo")
    parser.add_argument("--hourly-provider", choices=["yahoo", "alpha"], default="alpha")
    parser.add_argument("--start", help="Inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--end", help="Exclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--years", type=int, default=10, help="Lookback if --start is absent")
    parser.add_argument("--alpha-pause", type=float, default=0, help="Seconds between Alpha Vantage calls")
    parser.add_argument("--output", default="data/processed")
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except (ValueError, requests.RequestException) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
