# Expanded instruments and historical data

The local Trading Simulator now supports 330+ built-in reference instruments.
This includes US and Canadian stocks and ETFs, global benchmarks, bond funds,
commodity/sector funds, FX, cryptocurrencies and continuous futures.

Provider identification does not guarantee current listing, price history,
valid execution eligibility, or a continuous 20-year record. A symbol can
have shorter or missing coverage. Canadian dollar securities and noncash
contracts require explicit handling; more instruments do not authorize
automated brokerage trading.

## Historical research windows

| Candle interval | Available requested windows |
| --- | --- |
| 1 minute | 7D |
| 5 or 15 minutes | 7D, 30D, 60D |
| 1 hour | 7D, 30D, 60D, 6M, 1Y, 2Y |
| 1 day | 1Y, 2Y, 5Y, 10Y, 15Y, 20Y, MAX |

15Y and 20Y for Yahoo use explicit start/end dates because the provider
does not accept these labels directly as period arguments. MAX means the
maximum actual provider history, not a guarantee of 20 years. Coinbase
history is fetched in 300-bar pages. Real provider constraints normally
limit minute candles to recent days or weeks, while hourly data may
reach about two years. Up to 20,000 intraday candles are retained per
supported requested window. Unavailable candles are never synthesized.

Historical Yahoo candles use raw OHLCV with auto_adjust=False. These are
not dividend-adjusted total-return prices. Continuous futures may require
roll adjustment before robust multi-year studies. Real-time executable
quotes are not implied.

## Batch download real daily data on E:

The command below downloads actual observed historical OHLCV from external
market providers into Git-ignored compressed Parquet archives on your PC.
It does not run by itself on startup or in GitHub Actions.

~~~powershell
cd E:\Trading-Simulator
git pull
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --preset diversified --window 20Y --dry-run
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --preset diversified --window 20Y
~~~

Additional choices:

~~~powershell
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --preset canada --window MAX
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --preset global --window 15Y
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --ids spy,qqq,xbal,usdcad --window 20Y
~~~

The program checks instrument IDs, rate-limits requests and prints
observed first/last dates, counts, missing data and offline-only records.
It does not download model weights, execute trades, modify saved
strategies, or send owner holdings to an external provider. Symbols are
ordinary public reference tickers. Downloaded data remains in data/market/
and is not published to Vercel or GitHub.

Offline historical recovery no longer discards everything except the
last 5,000 bars. Old Parquet records remain intact. The local ingestion
watchlist can track up to 100 active instrument/interval pairs. Each
worker cycle processes at most 10 due subscriptions using oldest-first
ordering to avoid starving a large watchlist or overloading providers.

Data coverage must be measured from actual bars rather than inferred
from the selected time window. Imported Yahoo symbols remain subject to
provider confirmation and instrument/currency safety checks. Custom
imports are kept privately in data/custom_instruments.json, up to 1,000
symbols. No routine Vercel deployment is authorized.
