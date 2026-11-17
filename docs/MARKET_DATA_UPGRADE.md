# Local market-data expansion, monitoring and private AI

Development branch only. **Do not deploy** to Vercel before a major,
owner-approved release. All new market and strategy records stay under the
Git-ignored `data/` directory on the Windows laptop.

## 1. Shared instrument catalog

The Market Desk, single-asset simulator and portfolio simulator use the
same backend list, `GET /api/instruments`, now including all 138 built-in
symbols plus up to 200 previously verified user imports. Search the
provider when the symbol is not already in the local catalog, then import
an exact Yahoo-confirmed ticker. The 2 option entries are placeholders,
not tradable contracts. Some CAD, forex and continuous futures instruments
are chart/research-only. A successful catalog lookup does not guarantee
OHLCV provider coverage.

## 2. USD/CAD multi-asset portfolio research

The research comparison supports 2–10 USD- or CAD-denominated stocks/ETFs,
and USD cryptocurrency. For CAD instruments, it downloads historical
`USDCAD=X` (CAD per 1 USD) daily closes. CAD security open/close prices
are converted to USD using the **last completed FX session strictly
before the security's date**. It never uses today's FX close for today's
open execution. Dates without a recent FX observation are excluded; a
short/missing FX series fails closed. Every research result records source
conversion metadata. These are indicative historical valuations, not
executable FX rates. The legacy historical portfolio simulator still uses
a USD-only cash ledger, while mixed-currency **research comparisons**
support CAD. No real broker trades or currency conversions are executed.

## 3. Bounded incremental local history collector

In the Market Desk, choose a symbol and candle interval and press
**Collect new bars locally**. The local ingestion worker
`backend.market_ingest_worker` automatically runs with `start-local.ps1`.

- The subscription list persists in private `data/market_ingestion.sqlite3`.
- At most 25 active symbol/interval pairs can be tracked at once.
- Supported observed intervals: 1m, 5m, 15m, 1h, 1d.
- The first collection seeds a limited recent provider window using the
  existing historical adapter. Subsequent collection requests only the
  period since the latest archived candle, with a three-candle overlap
  to capture corrections. Existing Parquet files are atomically merged
  and de-duplicated.
- Minimum collection spacing: 60s for 1m, 120s for 5m, 300s for 15m,
  600s for hourly and 3600s for daily; the worker checks due items
  every 30 seconds. Failed requests have 3x cooldown.
- Exchange-listed instruments pause polling outside their modeled
  session; crypto trades 24/7.
- Public API quotas, upstream availability, rate limits and returned
  timestamps determine actual freshness. This is **not** tick streaming,
  licensed consolidated real-time NBBO, or broker execution.
- Market symbols are verified, no browser-supplied arbitrary endpoints,
  and shared public demo sessions cannot start or inspect ingestion.

Private API:
`GET /api/market-data/subscriptions`
`POST /api/market-data/subscriptions`, JSON `{"asset_id":"spy","resolution":"5m"}`
`DELETE /api/market-data/subscriptions/spy/5m`

Use a bounded watchlist. Tracking all 138 symbols at one-minute resolution
would exceed reliable anonymous-provider service capacity and is intentionally
not supported.

## 4. Completed-bar intraday strategy monitoring

In **Live Strategy Machine**, each new deployment can opt into
`1d`, `1h` or `15m` evaluation. Existing deployments keep their
daily cadence. The machine runs its worker every 90 seconds by default,
but checks a price condition only when the data provider has delivered
a **completed bar**. It:

- Rejects demo/offline data, insufficient warmup bars, invalid candles,
  and stale provider timestamps.
- Enforces exactly-once evaluation per deployment/symbol/source-bar
  via the existing unique SQLite key across worker restarts.
- Retains per-day signal caps, maximum allocations, journal-based
  risk stop and manual human trade confirmation.
- Does not convert an indicative Yahoo candle to an executable quote.
  It cannot submit broker orders.
- Requires fresh completed 15-minute or hourly bars. Delayed Yahoo
  publication makes actual signal latency **greater than** the worker
  polling interval. Some symbols may fail intraday coverage even when
  daily prices are available.

Daily monitoring still evaluates previous-session bars as before.
These intraday modes are experimental research monitoring until a
reliable licensed data feed, exchange holiday calendar, intraday risk
model and real broker reconciliation are validated.

## 5. Data coverage and stale source health

The Market Desk shows the local archive count, estimated session
coverage, up to 16 possible gaps, last archived candle and subscription
health/errors. The data-quality endpoint is read-only, does not
fetch market data or interpolate missing prices, and does not
confuse a stored historical candle with a live executable quote.

`GET /api/market-data/coverage/spy?window=1Y&resolution=1d`
`GET /api/market-data/health`

The weekday coverage estimate can flag holidays and exchange halts
as possible gaps: it is **not an exchange-calendar-certified quality
score**. The full local archive uses compressed Zstd Parquet and DuckDB.

## TwIL-8B from webAI: optional local model

Official model card:
https://huggingface.co/webAI-Official/TwIL-8B

Model details as of November 17, 2026:
- 8.79B parameter dense transformer, IBM Granite 4.2 base.
- Variants: balanced and verbose; both are English-focused text models.
- Balanced Q4_K_M GGUF download approximately 4.98 GiB;
  full BF16 checkpoint approximately 16.38 GiB.
- Reported strengths in mathematics, coding and instruction following,
  but this is **not a benchmark of financial reasoning or profitable
  trading**. Competition benchmarks are publisher-reported.
- It may generate long reasoning preambles even for short prompts,
  increasing latency on CPU hardware.
- License: **webAI Non-Commercial License 1.0**. The license limits
  intended use to non-commercial research and educational purposes.
  Do not bundle model weights in this repo or enable it as a public
  commercial default. Check licensing independently before any
  monetization or redistribution.
- Current model card describes English, not reliable bilingual outputs.
  Retain a Chinese-capable alternative for Simplified Chinese users.

**Optional setup after installing llama.cpp on your own PC:**

```powershell
llama-server -hf webAI-Official/TwIL-8B --hf-file TwIL-8B-Q4_K_M-balanced.gguf --alias TwIL-8B-Q4_K_M-balanced.gguf --host 127.0.0.1 --port 8081 --reasoning off --ctx-size 8192
```

This downloads weights on the local machine and runs a loopback-only
OpenAI-compatible chat API. Do not bind the server to the LAN or tunnel.
The user must review and accept the upstream model license before
downloading weights.

In your Git-ignored `.env` or local process environment, set:

```ini
TRADING_SIM_AI_PROVIDER=llama_cpp
TRADING_SIM_AI_MODEL=TwIL-8B-Q4_K_M-balanced.gguf
TRADING_SIM_AI_TIMEOUT_SECONDS=600
```

Restart the Python API. The existing built-in AI assistant now supports
the provider through `http://127.0.0.1:8081/v1/chat/completions`.
Ollama remains the default if no explicit provider is selected.
TwIL is never downloaded, started or paid for automatically by
Trading Simulator. Its output is advisory only: generated strategy
DSL must pass the same server-side validator and never auto-executes.

The existing AI context uses **revealed** historical bars and saved
research summaries, never hidden future candles. A small generated token
budget can truncate TwIL's long reasoning, so treat it as an experimental
assistant, not the primary optimization engine. The dedicated numerical
backtest/research code remains authoritative for performance metrics.

## Validation and runtime

```powershell
cd E:\Trading-Simulator
git pull
.\start-local.ps1
npm run verify:local
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Main frontend: http://127.0.0.1:5173

No deployment to Vercel or external hosted research database is
required. Existing live Vercel builds remain unchanged.
