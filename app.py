"""Datheon Strategy Research Lab. Run with: streamlit run app.py"""

from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datheon_data.dashboard import (aligned_benchmark, candidate_configs,
                                    optimize_train_test, rolling_drawdown)
from datheon_data.demo import synthetic_bars
from datheon_data.execution import ExecutionConfig, simulate_execution
from datheon_data.pipeline import prepare_bars
from datheon_data.providers import AlphaVantage, ProviderError, yahoo_history
from datheon_data.reports import render_tearsheet_pdf
from datheon_data.risk import monte_carlo_equity, performance_metrics
from datheon_data.signals import SignalConfig, build_signals


st.set_page_config(page_title="Datheon | Strategy Research Lab", page_icon="📈", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1500px;}
.datheon-label {font-size: .72rem; font-weight: 700; letter-spacing: .18em; color: #1d78b4;}
.datheon-title {font-size: 2.25rem; font-weight: 720; color: #102039; margin: .3rem 0;}
.datheon-subtitle {color: #5c6d83; font-size: 1rem; margin-bottom: 1.2rem;}
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="datheon-label">DATHEON / QUANTITATIVE RESEARCH</div>', unsafe_allow_html=True)
st.markdown('<div class="datheon-title">Strategy Research Lab</div>', unsafe_allow_html=True)
st.markdown('<div class="datheon-subtitle">Momentum and mean reversion, with causal signals, execution costs, and risk analytics.</div>', unsafe_allow_html=True)


def parse_tickers(value: str) -> list[str]:
    tickers = list(dict.fromkeys(part.strip().upper().replace(".", "-") for part in value.split(",")))
    if not tickers or len(tickers) > 5 or any(not re.fullmatch(r"[A-Z0-9^-]+", t) for t in tickers):
        raise ValueError("Enter 1-5 comma-separated ticker symbols")
    return tickers


def parse_candidates(value: str, kind: type) -> list:
    try:
        numbers = [kind(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError("Parameter candidates must be comma-separated numbers") from exc
    if not numbers:
        raise ValueError("Enter at least one parameter candidate")
    return numbers


@st.cache_data(ttl=3600, show_spinner=False)
def load_bars(symbol: str, start: str, end: str, frequency: str, source: str) -> pd.DataFrame:
    if source == "Synthetic demo":
        return synthetic_bars(symbol, start, end, frequency)
    start_ts = pd.Timestamp(start).tz_localize("UTC")
    end_ts = pd.Timestamp(end).tz_localize("UTC") + pd.Timedelta(days=1)
    if source == "Yahoo Finance":
        if frequency == "hourly" and start_ts < end_ts - pd.Timedelta(days=60):
            raise ValueError("Yahoo hourly history is limited to about 60 days; choose a shorter range or Alpha Vantage")
        raw = yahoo_history(symbol, start_ts.to_pydatetime(), end_ts.to_pydatetime(), frequency)
        return prepare_bars(raw, symbol, frequency, "yahoo")
    key = os.getenv("ALPHAVANTAGE_API_KEY", "")
    alpha = AlphaVantage(key, cache_dir=Path("data/raw-cache/alpha"))
    raw = (alpha.daily(symbol, start_ts.to_pydatetime(), end_ts.to_pydatetime())
           if frequency == "daily" else alpha.hourly(symbol, start_ts.to_pydatetime(), end_ts.to_pydatetime()))
    return prepare_bars(raw, symbol, frequency, "alpha_vantage")


with st.sidebar.form("research_controls"):
    st.subheader("Research setup")
    source = st.selectbox("Data source", ["Synthetic demo", "Yahoo Finance", "Alpha Vantage"])
    ticker_text = st.text_input("Tickers", value="AAPL, MSFT", help="Up to five symbols, separated by commas")
    benchmark_symbol = st.text_input("Buy-and-hold benchmark", value="SPY")
    frequency = st.selectbox("Bar frequency", ["daily", "hourly"])
    start_date = st.date_input("Start date", value=date.today() - timedelta(days=365 * 3))
    end_date = st.date_input("End date", value=date.today())
    strategy = st.selectbox("Strategy", ["momentum", "mean_reversion"],
                            format_func=lambda value: "Momentum" if value == "momentum" else "Bollinger mean reversion")
    st.divider()
    st.subheader("Execution assumptions")
    initial_capital = st.number_input("Initial capital ($)", min_value=1_000.0, value=100_000.0, step=10_000.0)
    half_spread = st.number_input("Half spread (bps)", min_value=0.0, value=2.5, step=0.5)
    max_participation = st.slider("Maximum volume participation", 0.01, 0.25, 0.05, 0.01)
    st.divider()
    optimize = st.checkbox("Optimize on training period", value=True)
    first_candidates = st.text_input("MA fast / BB window candidates", value="10, 20" if strategy == "momentum" else "15, 20")
    second_candidates = st.text_input("MA slow / BB width candidates", value="40, 60" if strategy == "momentum" else "1.5, 2.0, 2.5")
    run_button = st.form_submit_button("Run research", type="primary", use_container_width=True)

if run_button:
    st.session_state.pop("research_results", None)
    st.session_state.pop("research_meta", None)
    try:
        if start_date >= end_date:
            raise ValueError("Start date must precede end date")
        tickers = parse_tickers(ticker_text)
        benchmark_list = parse_tickers(benchmark_symbol)
        if len(benchmark_list) != 1:
            raise ValueError("Enter exactly one benchmark ticker")
        benchmark_ticker = benchmark_list[0]
        base_config = SignalConfig()
        execution = ExecutionConfig(initial_capital=initial_capital, half_spread_bps=half_spread,
                                    max_participation=max_participation,
                                    periods_per_year=252 if frequency == "daily" else 252 * 6.5)
        candidates = (candidate_configs(strategy, base_config,
                                       parse_candidates(first_candidates, int),
                                       parse_candidates(second_candidates, int if strategy == "momentum" else float))
                      if optimize else [base_config])
        results = {}
        with st.spinner("Loading bars and running cost-aware backtests..."):
            benchmark_bars = load_bars(benchmark_ticker, str(start_date), str(end_date), frequency, source)
            for ticker in tickers:
                bars = load_bars(ticker, str(start_date), str(end_date), frequency, source)
                if optimize:
                    chosen = optimize_train_test(bars, strategy, candidates, execution)
                    signals, curve = chosen["signals"], chosen["curve"]
                    config = chosen["selected_config"]
                else:
                    signals = build_signals(bars, base_config)
                    curve = simulate_execution(bars, signals, strategy, execution)
                    config = base_config
                    chosen = None
                metrics = performance_metrics(curve, execution.initial_capital, execution.periods_per_year)
                mc, mc_curves = monte_carlo_equity(curve["net_return"], execution.initial_capital,
                                                   paths=300, block_size=5, ruin_fraction=0.5)
                comparison = aligned_benchmark(curve["equity"], benchmark_bars["adjusted_close"],
                                               execution.initial_capital)
                results[ticker] = {"bars": bars, "signals": signals, "curve": curve,
                                   "config": config, "optimization": chosen, "metrics": metrics,
                                   "mc": mc, "mc_curves": mc_curves, "comparison": comparison}
        st.session_state["research_results"] = results
        st.session_state["research_meta"] = {"source": source, "benchmark": benchmark_ticker,
                                              "strategy": strategy, "frequency": frequency,
                                              "execution": execution.to_dict(),
                                              "start": str(start_date), "end": str(end_date)}
    except (ValueError, ProviderError, OSError) as exc:
        st.error(str(exc))

if "research_results" not in st.session_state:
    st.info("Choose settings in the sidebar and run the research. The default synthetic demo works without a market-data account.")
    st.stop()

results = st.session_state["research_results"]
meta = st.session_state["research_meta"]
if meta["source"] == "Synthetic demo":
    st.warning("SYNTHETIC DEMONSTRATION — all prices and performance shown here are simulated, not historical market results.")
else:
    st.caption(f"Market data: {meta['source']} · {meta['frequency']} · {meta['start']} to {meta['end']}")
ticker = st.selectbox("Review ticker", list(results))
item = results[ticker]
metrics = item["metrics"]
comparison = item["comparison"]

def percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"

def ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"

top = st.columns(4)
top[0].metric("Net return", percent(metrics["total_return"]))
top[1].metric("Sharpe", ratio(metrics["sharpe_ratio"]))
top[2].metric("Maximum drawdown", percent(metrics["maximum_drawdown"]))
top[3].metric("Bootstrap ruin frequency", percent(item["mc"]["probability_of_ruin"]))

overview, optimization_tab, audit = st.tabs(["Performance", "Parameter search", "Audit & export"])
with overview:
    fig = go.Figure()
    for name, color in [("strategy", "#0078b8"), ("benchmark", "#56677f")]:
        fig.add_trace(go.Scatter(x=comparison.index,
                                 y=(comparison[name] / meta["execution"]["initial_capital"] - 1) * 100,
                                 name=meta["strategy"].replace("_", " ").title() if name == "strategy" else f"{meta['benchmark']} buy-and-hold",
                                 line=dict(color=color, width=2.5)))
    fig.update_layout(title="Cumulative total return", yaxis_title="Return (%)", height=420,
                      margin=dict(l=20, r=20, t=55, b=20), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    window = 63 if meta["frequency"] == "daily" else 100
    drawdown_fig = go.Figure()
    for name, color in [("strategy", "#0078b8"), ("benchmark", "#56677f")]:
        drawdown_fig.add_trace(go.Scatter(x=comparison.index,
                                          y=rolling_drawdown(comparison[name], window) * 100,
                                          name=name.title(), line=dict(color=color, width=2)))
    drawdown_fig.update_layout(title=f"Rolling {window}-bar drawdown", yaxis_title="Drawdown (%)",
                               height=350, margin=dict(l=20, r=20, t=55, b=20), hovermode="x unified")
    st.plotly_chart(drawdown_fig, use_container_width=True)
    st.caption("Benchmark uses adjusted close and is normalized at the first common bar. The ruin estimate resamples observed net returns and is not a forecast.")

with optimization_tab:
    if item["optimization"] is None:
        st.info("Enable parameter optimization in the sidebar to compare training-period candidates.")
    else:
        chosen = item["optimization"]
        st.caption(f"Chronological split: training ends before {chosen['split_timestamp']}; the selected model is then assessed on later bars.")
        train_col, test_col = st.columns(2)
        train_col.metric("Training Sharpe", ratio(chosen["train_metrics"]["sharpe_ratio"]))
        test_col.metric("Holdout Sharpe", ratio(chosen["test_metrics"]["sharpe_ratio"]))
        st.dataframe(chosen["leaderboard"], use_container_width=True, hide_index=True)
        st.caption(f"Selected parameters: {chosen['selected_config'].to_dict()}")

with audit:
    report = {"ticker": ticker, "benchmark": meta["benchmark"], "source": meta["source"],
              "synthetic_demo": meta["source"] == "Synthetic demo", "strategy": meta["strategy"],
              "frequency": meta["frequency"], "start": meta["start"], "end": meta["end"],
              "signal_parameters": item["config"].to_dict(),
              "execution_parameters": meta["execution"],
              "performance": metrics, "monte_carlo": item["mc"]}
    st.json(report)
    st.download_button("Download risk report (JSON)", json.dumps(report, indent=2),
                       file_name=f"{ticker}_{meta['strategy']}_risk_report.json", mime="application/json")
    st.download_button("Download equity curve (CSV)", item["curve"].to_csv(),
                       file_name=f"{ticker}_{meta['strategy']}_equity_curve.csv", mime="text/csv")
    st.download_button("Download performance tearsheet (PDF)",
                       render_tearsheet_pdf(report, comparison),
                       file_name=f"{ticker}_{meta['strategy']}_tearsheet.pdf", mime="application/pdf")
    whitepaper = Path(__file__).resolve().parent / "docs" / "risk_whitepaper.pdf"
    if whitepaper.exists():
        st.download_button("Download risk whitepaper (PDF)", whitepaper.read_bytes(),
                           file_name="datheon_risk_whitepaper.pdf", mime="application/pdf")
    st.dataframe(item["curve"].tail(50), use_container_width=True)
