# Datheon Algorithmic Momentum & Mean-Reversion Backtester

An incremental research project for equity market data, strategy signals, execution simulation, and risk analytics. **Tasks 1–3 are implemented:** OHLCV preparation, causal momentum/mean-reversion signals, and cost-aware execution and risk simulation. The interactive dashboard and risk whitepaper are the remaining milestone.

## Task 1: historical market data

The CLI downloads one or many equities, checks timestamp uniqueness and OHLCV integrity, stores raw and adjusted OHLC, computes simple and logarithmic returns, and records an Augmented Dickey–Fuller (ADF) test on each return series. Data is written as per-symbol Parquet files with a JSON manifest containing coverage, test results, provenance, and failures. A failed ticker makes the command exit nonzero while retaining successful files and a failure record.

**Provider capabilities:** Yahoo Finance supplies up to ten years of daily data, but its hourly history is limited to roughly the most recent 60 days. For ten years of hourly data, use the Alpha Vantage historical intraday endpoint with a premium API entitlement. Its `month` parameter is requested for every month in the range; a ten-year run is roughly 120 requests per symbol. Alpha Vantage's adjusted daily endpoint is also premium. This repository does not contain downloaded market data or an API key.

Completed historical Alpha Vantage months are cached under `data/raw-cache/alpha` so a long run can resume without downloading the same months again. Current-month and daily requests remain uncached.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

## Examples

```bash
# Ten years of daily prices using Yahoo Finance.
datheon-ingest --symbols AAPL MSFT --frequency daily --years 10

# Ten years of daily and hourly prices; requires Alpha Vantage premium access.
export ALPHAVANTAGE_API_KEY='your-key'
datheon-ingest --symbols AAPL MSFT --frequency both --years 10 --alpha-pause 1

# Current S&P 500 members (research with a survivorship-bias warning).
datheon-ingest --sp500-current --frequency daily --years 10

# Point-in-time or custom universe supplied as a CSV with a `symbol` column.
datheon-ingest --universe-csv universe.csv --start 2016-11-14 --end 2026-11-14
```

Use `--frequency hourly --hourly-provider yahoo --start YYYY-MM-DD` for recent hourly data. The Yahoo adapter rejects requests longer than its documented intraday window. `--end` is exclusive; all output timestamps are UTC. Alpha Vantage's regular-session hourly timestamps are interpreted in `America/New_York` before conversion to UTC. For any provider, data gaps remain gaps: the pipeline does not invent missing bars.

### Output contract

Each `data/processed/<frequency>/<symbol>.parquet` file has a UTC `timestamp` index and these columns:

| Column | Meaning |
| --- | --- |
| `open`, `high`, `low`, `close`, `volume` | Provider OHLCV. For Alpha hourly, OHLC is already adjusted by the provider. |
| `adjusted_open`, `adjusted_high`, `adjusted_low`, `adjusted_close` | Split/dividend-adjusted OHLC. Daily values use the adjusted-close-to-close factor. |
| `adjustment_factor` | `adjusted_close / close`; equals 1 for already adjusted Alpha hourly prices. |
| `dividend`, `split_ratio` | Daily corporate actions when the provider supplies them; unavailable intraday actions are null. |
| `simple_return`, `log_return` | Consecutive-bar adjusted-close returns; first value is null. |
| `symbol`, `frequency`, `source` | Provenance. |

`data/processed/manifest.json` lists the request window, requested universe, each file's coverage and row count, ADF statistic and p-value, and any errors. `stationary_at_5pct` means the ADF unit-root null was rejected at 5%; it does not prove stationarity. Short or nearly constant series are reported as untestable.

## Task 2: causal strategy signals

Generate decision-time signals from Task 1 output:

```bash
datheon-signals --input data/processed --output data/signals

# Experiment with a different set of lookbacks and band width.
datheon-signals --ma-fast 10 --ma-slow 40 --bb-window 20 --bb-width 2.5
```

The command reads `daily/*.parquet` and `hourly/*.parquet`, writes matching files under `data/signals`, and records parameters, readiness counts, and a SHA-256 hash of each input in `data/signals/manifest.json`.

Each output row is a **decision for bar `t`**. Its `information_cutoff` is the preceding observed bar, and `known_adjusted_close` is that bar's adjusted close. All indicator and position columns derive from this lagged series. A crossover caused by the close of bar `t-1` first appears on decision row `t`. Warmup rows are flat and marked as unready.

| Signal | Rule |
| --- | --- |
| MACD | EMA(12) minus EMA(26), with a 9-bar EMA signal line. `macd_cross` is +1 or -1 at an upward or downward signal-line crossing. |
| Dual moving averages | SMA(20) and SMA(50). `ma_cross` is +1 or -1 at an upward or downward crossing. |
| Momentum target | `momentum_position` is +1 when both MACD and MA spreads are positive, -1 when both are negative, and 0 when they disagree. |
| Dynamic Bollinger Bands | A 20-bar mean ± rolling price standard deviation times `bb_width`. The width is scaled by the ratio of 10-bar to 60-bar log-return volatility, clipped to 0.75–1.50. |
| Mean reversion target | Enter long below the lower band or short above the upper band. Exit at the midline. `mean_reversion_action` records entries and exits; `mean_reversion_position` is +1, -1, or 0. |

These are **target exposures**, not executed trades or realized P&L. The execution simulator in Task 3 will determine fill timing and costs. The indicators use row-count windows, so a gap in market data is not filled with synthetic observations. Lookbacks and band parameters are configurable via `datheon-signals --help`.

## Task 3: execution and risk analytics

```bash
datheon-backtest --bars data/processed --signals data/signals --output data/backtests

# Illustrative sensitivity run with narrower participation and a larger spread.
datheon-backtest --strategy momentum --max-participation 0.02 \
  --half-spread-bps 5 --mc-paths 2000 --ruin-fraction 0.5
```

The simulator trades changes in the Task 2 target state at the **next bar's open** and marks equity at that bar's close. It uses only the **previous bar's volume** to cap each fill (`max_participation` defaults to 5%) and calculate impact. Unfilled shares remain pending; unchanged targets do not cause repeated rebalancing. It verifies both the signal's `information_cutoff` and its lagged price against the bar file. When a Task 2 manifest exists, it also checks the source file hash to reject stale signals.

For an order of `Q` shares and preceding-bar volume `V`, participation is `|Q| / V`. The fill price is the adjusted open plus or minus a configurable half spread and two impact terms: `linear_impact_bps × participation` and `sqrt_impact_bps × sqrt(participation)`. The side determines the sign. Per-share commissions with a minimum charge are deducted for each fill. Short inventory pays a configurable annual borrow rate per bar. Defaults are research assumptions, **not calibrated broker quotes or promises of executable liquidity**. The adjusted OHLC series is a synthetic total-return price basis; dividends and splits are already embedded and are not credited again. Actual raw quotes, intraday order books, margin requirements, and borrow availability are outside this model. A short gap that exhausts capital ends the simulation at zero equity.

Outputs for each symbol, frequency, and strategy are:

| File | Contents |
| --- | --- |
| `equity_curve.parquet` | Targets, actual shares, partial fills, participation, spread/impact/commission/borrow costs, equity, net returns, and drawdown. |
| `risk_report.json` | Annualized Sharpe, Sortino, and Calmar ratios; total return; maximum drawdown; maximum drawdown duration in bars; cost totals; Monte Carlo summary; input hashes and parameters. |
| `monte_carlo.parquet` | Pointwise 5th/50th/95th percentile equity curves and up to ten sample paths. |

Sharpe divides mean excess bar return by its sample standard deviation and multiplies by the square root of bars per year. Sortino uses the root mean square of negative excess returns. Calmar divides annualized compounded return by maximum drawdown magnitude. The default annualization is 252 bars for daily data and 252 × 6.5 for hourly data; override with `--periods-per-year` if the data's session structure differs. Ratios with a zero denominator are null.

Monte Carlo uses a seeded **circular moving-block bootstrap** of observed *net* strategy returns (default 1,000 paths, five-bar blocks, and a horizon matching the backtest). `probability_of_ruin` is the fraction of sampled paths that ever reach or fall below `ruin_fraction × initial_capital` (default 50%). It is conditional on the backtest return history and model assumptions, **not a forward probability forecast**. The manifest and report record the seed and all inputs for reproducibility.

## Research cautions

- `--sp500-current` fetches today's constituents, which introduces survivorship bias into a historical backtest. Supply a historical, point-in-time universe for credible strategy results.
- The adjusted-close ratio is the provider's historical adjustment convention. Adjusted OHLC is suitable for total-return research, but the adjusted price is not an executable quote. Later execution simulations should distinguish signal prices from actual fills.
- Dividend and split events are retained for inspection. Alpha Vantage's intraday response does not include event columns; null does not mean no event occurred.
- Provider availability, revisions, ticker changes, delistings, rate limits, and corporate actions can change the result. The manifest records what was actually retrieved; it never labels a short series as ten years of coverage.
- Execution cost coefficients should be stress-tested or calibrated to venue, ticker, and order size. A single-symbol backtest is not a diversified portfolio backtest.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use synthetic bars and mocked provider responses. They do not require live vendor access.

## Sources

- [yfinance price-history reference](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)
- [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/)
- [statsmodels ADF documentation](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html)
- [pandas exponentially weighted windows](https://pandas.pydata.org/pandas-docs/stable/generated/pandas.Series.ewm.html)
- [pandas rolling standard deviation](https://pandas.pydata.org/docs/reference/api/pandas.api.typing.Rolling.std.html)
- [William Sharpe, *The Sharpe Ratio*](https://web.stanford.edu/~wfsharpe/art/sr/sr.htm)
- [Tóth et al., *Anomalous Price Impact and the Critical Nature of Liquidity in Financial Markets*](https://journals.aps.org/prx/abstract/10.1103/PhysRevX.1.021006)
