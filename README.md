# Datheon Algorithmic Momentum & Mean-Reversion Backtester

An incremental research project for equity market data, strategy signals, execution simulation, and risk analytics. **Task 1 is implemented here:** a reproducible daily/hourly OHLCV ingestion and sanitation pipeline. Later milestones will build on its adjusted price and return schema.

## Task 1: historical market data

The CLI downloads one or many equities, checks timestamp uniqueness and OHLCV integrity, stores raw and adjusted OHLC, computes simple and logarithmic returns, and records an Augmented Dickey–Fuller (ADF) test on each return series. Data is written as per-symbol Parquet files with a JSON manifest containing coverage, test results, provenance, and failures. A failed ticker makes the command exit nonzero while retaining successful files and a failure record.

**Provider capabilities:** Yahoo Finance supplies up to ten years of daily data, but its hourly history is limited to roughly the most recent 60 days. For ten years of hourly data, use the Alpha Vantage historical intraday endpoint with a premium API entitlement. Its `month` parameter is requested for every month in the range; a ten-year run is roughly 120 requests per symbol. Alpha Vantage's adjusted daily endpoint is also premium. This repository does not contain downloaded market data or an API key.

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

## Research cautions

- `--sp500-current` fetches today's constituents, which introduces survivorship bias into a historical backtest. Supply a historical, point-in-time universe for credible strategy results.
- The adjusted-close ratio is the provider's historical adjustment convention. Adjusted OHLC is suitable for total-return research, but the adjusted price is not an executable quote. Later execution simulations should distinguish signal prices from actual fills.
- Dividend and split events are retained for inspection. Alpha Vantage's intraday response does not include event columns; null does not mean no event occurred.
- Provider availability, revisions, ticker changes, delistings, rate limits, and corporate actions can change the result. The manifest records what was actually retrieved; it never labels a short series as ten years of coverage.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use synthetic bars and mocked provider responses. They do not require live vendor access.

## Sources

- [yfinance price-history reference](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)
- [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/)
- [statsmodels ADF documentation](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html)
