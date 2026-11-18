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

## Subscription-first: durable bootstrap and hourly verification

Recommended option is to **select a symbol and interval in Market Desk**, then
click the local collection toggle. The backend now records two durable jobs in
the private SQLite ingestion database:

1. Historical bootstrap, due immediately. This requests the widest supported
   provider window for the selected bar size: daily MAX, hourly 2Y, 5m and
   15m for 60D, and 1m for 7D. Availability is provider-dependent and
   an unsupported/empty response remains unresolved. Existing subscription
   records are automatically added to this queue when the worker starts.
2. A rolling reconciliation job, eligible after bootstrap succeeds. It checks
   short overlapping provider windows at least once per hour when processing
   capacity and the provider permit: daily 21D, hourly 7D, 5/15m 7D, and
   1m 2D. It compares every returned OHLCV timestamp/value against the
   final archived Parquet after deduplication, correcting changed bars and
   filling provider-returned gaps. It does not assume that provider omissions
   mean no trades occurred.

The bootstrap only runs once successfully. Both stages remain in SQLite and
survive restarts. A failed fetch, malformed/conflicting candle or unverified
archive write records an error and an unresolved state. Failures retry at
1, 2, 4, 8 and progressively up to 60 minutes, with no finite attempt
limit and no busy looping. A recent successful check is labelled
provider_checked, never guaranteed_complete. After every successful
reconciliation, its next check is due one hour later. The actual check can
be delayed by queue congestion or throttling.

Fresh incremental polling and slower reconciliation now run in separate
threads of the same local worker process. A slow historical download does
not block the next normal feed-poll iteration. Each reconciliation cycle
handles only one due job to limit provider pressure.

The authenticated /api/market-data/health endpoint and Market Desk show
the initial backfill state, latest verification outcome, recorded bar count,
retry errors, and next due time. You can leave a failing job in the queue
without treating it as clean market data.

This is *provider-observation verification*, not end-to-end delivery
certification. It cannot prove that Yahoo or Coinbase themselves supplied
every possible traded bar or transaction, that missing bars are still
available for retry, or that adjusted prices/corporate actions are complete.
For research that requires 100% exchange-level completeness, those
questions must remain unresolved until a licensed, auditable feed is used.

## Ongoing collection and delivery limits

The Trading Simulator does not guarantee complete live delivery for all
instruments. The local collector is opt-in by symbol and candle interval.
start-local.ps1 starts the local worker, which runs every 30 seconds
while the PC and worker remain on. It fetches only configured active
subscriptions, up to 10 due feeds each polling cycle.

Minimum revisit intervals are 1m bars every 60 seconds, 5m bars every
120 seconds, 15m bars every 300 seconds, 1h every 600 seconds and
daily every 3600 seconds. Provider latency, trading sessions and rate
limits can make the actual interval longer. These are polled provider
candles, not licensed exchange ticks. The download-all historical
command does not automatically activate ongoing subscriptions.

To check the actual collector from PowerShell:

~~~powershell
cd E:\Trading-Simulator
git pull
.\stop-local.ps1
.\start-local.ps1 -NoBrowser
Invoke-RestMethod http://127.0.0.1:8000/api/market-data/health |
    ConvertTo-Json -Depth 5
~~~

The new collector heartbeat in the health endpoint shows recently
confirmed polling or idle state, the last heartbeat time and its age.
The collector state can instead be stale or unverified. A configured
active subscription and a prior successful sync alone are never proof
that the worker is currently running. Market Desk displays this
separately from subscriptions, last successful sync, and source failures.
The delivery_guaranteed property is always false.

When the provider or PC is unavailable, a later incremental fetch
starts at the last saved bar with a three-bar overlap. Archives dedupe
same timestamps, so successful retries do not insert duplicate candles.
Provider errors cause a longer retry cooldown (3x the interval).
Recent trailing gaps can be recovered if a source still retains
the corresponding bars. Historical missing internal periods, outages
past retention, incomplete historical sessions, and permanent provider
omissions are NOT guaranteed recoverable. The coverage API reports
potential gaps and missing timestamps without fabricating bars.
Market holidays or halts require calendar-aware review.

For a contractual delivery guarantee, use a licensed exchange feed with
durable message replay, heartbeats, gap detection, independent audit,
monitoring, alerts, and a redundant always-on collector. Coinbase has
public WebSocket trade channels, but the simulator does not currently
consume them. Yahoo Finance via yfinance is unofficial and has limited
intraday coverage. The simulator runs this locally, not on Vercel.

## Download everything, without duplicate bars

To download the maximum available real DAILY history for every built-in
and locally imported catalog ticker, run:

~~~powershell
cd E:\Trading-Simulator
git pull
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --all --dry-run
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --all
~~~

To also collect the widest supported historical intraday windows, including
1-minute, 5-minute, 15-minute and 1-hour observations:

~~~powershell
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --all --include-intraday --dry-run
.\.venv\Scripts\python.exe scripts\backfill-market-history.py --all --include-intraday
~~~

This performs many real provider requests; historical availability and
throttling depend on the source. Use the dry run to see the planned number of
tasks. It does not contact market providers or write market archives.
The default for --all is MAX daily data. For instruments with no valid actual
ticker, such as option placeholders, the downloader skips the instrument.

**Idempotent storage:** Each task has a unique instrument, exact interval and
one widest requested time window. It does not download overlapping 10Y/15Y/20Y
windows as separate copies during the same run. Before requesting a provider,
it checks the existing local Parquet archive and skips any nonempty, readable
window already present. It does this even when the progress file was lost.
Completed task state is checkpointed atomically in the private
data/market/_download_progress.json file. If interrupted, run the same
command again: completed files are reused, failed or missing tasks are retried.

The Parquet archive merges candle observations by their exact UNIX timestamp
within each instrument/interval/window, retaining corrected source bars
instead of appending a duplicate timestamp. Use --refresh only when you
intentionally want to re-fetch the completed windows; a refresh never
appends duplicate time rows. Existing different time windows created before
this feature may hold overlapping content in separate files. This workflow
does not delete or rewrite those prior archives or private replay snapshots.
Unreadable archives are flagged for manual repair and never overwritten
silently.

Only actual recorded OHLCV is saved. No blank periods are extrapolated.
For example, a newly listed ETF cannot have a 20-year history even if
MAX was requested. The most extensive feasible historical resolution is
not necessarily a live or licensed market-data feed.

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
