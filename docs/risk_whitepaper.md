# Strategy Risk Methodology Whitepaper

Datheon Algorithmic Momentum and Mean-Reversion Strategy Backtester

Version 1.0 | 14 November 2026 | Research methodology, not an investment recommendation

## Executive summary

This note explains the data, signal, execution, and risk calculations implemented in the open-source Datheon backtester. The system is designed to make assumptions visible and repeatable. It is a research prototype. Its simulated fills do not constitute broker quotes, and its historical results cannot establish future profitability. No production trading claim is made.

The workflow is sequential: ingest and validate OHLCV bars; calculate decision-time signals using only earlier bars; trade target-state changes at the next adjusted open; deduct explicit spread, impact, commission, and short borrow costs; then report net performance and bootstrap scenarios. The dashboard selects strategy parameters on an earlier training period and displays a later holdout evaluation.

## 1. Data lineage and quality controls

Daily prices can be retrieved from Yahoo Finance or Alpha Vantage. A ten-year hourly history requires historical intraday access from Alpha Vantage; Yahoo's intraday window is substantially shorter. Vendor-adjusted prices incorporate split and dividend adjustments. The pipeline retains provider OHLCV, adjusted OHLC, corporate action fields when available, simple returns, and log returns. It rejects duplicate timestamps, nonfinite values, negative volume, nonpositive prices, and inconsistent high-low ranges. A manifest records the requested interval, observed coverage, source, stationarity diagnostics, and failures. Missing bars remain missing.

Using today's S&P 500 constituents for a historical period introduces survivorship bias. A credible historical universe must identify membership at each decision date and include delisted securities. Provider revisions, symbol changes, stale prices, and missing corporate actions remain data risks. ADF statistics are diagnostics for a unit-root null, not proof of stationarity.

## 2. Signal timing and strategy rules

For decision row t, the information cutoff is the preceding observed bar. The signal engine explicitly shifts adjusted close by one bar before computing all indicators. A change to bar t cannot alter the decision shown on row t. Warmup periods are flat and marked as unready.

The momentum rule calculates MACD from a 12-bar and 26-bar exponential moving average, with a 9-bar signal line. It also calculates 20-bar and 50-bar simple moving averages. The desired state is long when both spreads are positive, short when both are negative, and flat when they disagree. Cross events are recorded separately from ongoing target state.

The mean-reversion rule uses a 20-bar Bollinger mean and rolling price standard deviation. Its band width responds to the ratio of short and long realized log-return volatility, clipped to an explicit range. It enters long below the lower band or short above the upper band, and exits at the rolling mean. Lookback values, band width, and volatility scaling are configurable.

## 3. Execution assumptions

The simulator trades at the current bar's adjusted open after receiving the prior-bar signal. It uses the previous bar's volume, never the current bar's closing volume, for capacity and impact. A per-bar participation limit can leave orders partially filled; outstanding shares remain pending. An unchanged target state does not trigger a full rebalance each bar.

For filled shares Q and previous-bar volume V, participation p equals abs(Q) / V. The adverse price adjustment in basis points is half_spread_bps + linear_impact_bps * p + sqrt_impact_bps * sqrt(p). Buy fills pay above the reference open and sell fills receive below it. Commissions are max(minimum_commission, abs(Q) * commission_per_share). A short position pays a per-bar borrow fee based on previous close notional and the annual borrow rate. Costs are deducted from cash before close-to-close equity is recorded.

The adjusted OHLC stream is a synthetic total-return basis. Explicit dividends and splits are not credited again. This produces a coherent research accounting convention but is not an executable quote history. The model omits order-book dynamics, temporary versus permanent impact, auction timing, market halts, exchange-specific fees, borrow locate failures, margin calls, cash interest, and tax. A short gap that exhausts capital terminates the simulation at zero equity. Impact coefficients and participation limits are scenario assumptions that require instrument-level calibration before practical use.

## 4. Risk measures

All performance measures use net returns after simulated costs. Annualized Sharpe equals mean per-bar excess return divided by its sample standard deviation, multiplied by sqrt(bars_per_year). Sortino replaces total volatility with the root mean square of negative excess returns. Calmar equals annualized compounded return divided by maximum drawdown magnitude. A zero denominator yields a null ratio rather than an invented value.

Drawdown at a bar is equity divided by the running peak, minus one. Maximum drawdown is the largest loss from a prior equity peak. Maximum drawdown duration counts consecutive underwater bars, including an unrecovered drawdown at the sample end. The dashboard separately shows rolling-window drawdown and a normalized buy-and-hold benchmark on adjusted close. SPY may be used as an ETF proxy; it is not identical to the S&P 500 price index.

Daily results use 252 bars per year by default. Hourly results use 252 * 6.5 bars per year. These are conventions, not observed trading-session counts. The user can override the annualization factor and risk-free rate. Short samples, irregular bars, stale prices, and serial correlation can distort annualized ratios.

## 5. Scenario simulation and probability of ruin

Monte Carlo paths resample observed net strategy returns in circular moving blocks. The seed, path count, horizon, block size, and ruin threshold are recorded. The estimated probability of ruin is the fraction of paths whose equity ever reaches or falls below a configured fraction of initial capital. The default threshold is 50 percent. Pointwise 5th, 50th, and 95th percentile curves and sample paths are saved for review.

This is a conditional resampling statistic. It does not incorporate an unseen regime, structural break, parameter drift, or a new liquidity crisis unless such behavior is represented in the observed returns. It is not a calibrated probability forecast. Stress tests should vary impact, spread, borrow fees, return blocks, and starting dates.

## 6. Validation and model governance

The automated suite checks corporate-action adjustment arithmetic, price validation, signal lag invariance, crossover timing, partial fills, cost decomposition, borrow fees, ruin handling, drawdown duration, deterministic bootstrap output, and the end-to-end Parquet workflow. GitHub Actions runs the suite on every push. The backtest rejects signals whose information cutoff or lagged price does not match the bar file; when a signal manifest is present, source-file hashes are checked as well.

Parameter search is chronological. Candidate settings are ranked on the earlier training segment; only the selected setting is assessed on the later holdout segment. That holdout is still one historical realization. Repeated manual tuning to its results would consume the holdout's evidential value. A stronger deployment review would add rolling walk-forward splits, instrument and period diversification, scenario calibration against broker fills, and independent data reconciliation.

## 7. Decision use and remaining work

The repository supports reproducible research and demonstration. Before capital allocation, a reviewer should verify point-in-time universe membership, vendor licensing, corporate actions, data gaps, benchmark alignment, transaction cost calibration, borrow availability, parameter stability, and out-of-sample performance. All example performance distributed with this repository is explicitly labeled synthetic. The repository does not claim an audited live track record.

## References

- William F. Sharpe, "The Sharpe Ratio" (1994), https://web.stanford.edu/~wfsharpe/art/sr/sr.htm
- Toth et al., "Anomalous Price Impact and the Critical Nature of Liquidity in Financial Markets" (2011), https://journals.aps.org/prx/abstract/10.1103/PhysRevX.1.021006
- Alpha Vantage API documentation, https://www.alphavantage.co/documentation/
- yfinance price-history reference, https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html
- statsmodels Augmented Dickey-Fuller reference, https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html
