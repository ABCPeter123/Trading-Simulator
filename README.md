# Trading Simulator

> **Milestone-only production releases:** Automatic Vercel deployments
> have been disabled. GitHub commits no longer imply website updates.
> Develop through `npm run dev` or `.\start-local.ps1`
> (including the laptop research worker), then release one tested milestone
> only after explicit owner approval. See
> [local-first development and release freeze](docs/LOCAL_FIRST_RELEASE_POLICY.md).


> **Long-term product direction:** A professional, always-on quantitative trading
> research, live signal, risk-monitoring, and human-confirmed trade management
> platform. The historical simulator is one stage of the product, not the final
> purpose. Read the [canonical product vision](docs/PRODUCT_VISION.md) and
> [contributor instructions](AGENTS.md) before planning or implementing new work.
> Real 24/7 signal operation, external trade confirmations and live portfolio
> monitoring are **planned capabilities**, not yet production-ready.

A **local-first historical trading simulator with integrated paper market research** using public financial market data. It runs in your browser at `127.0.0.1:5173` with a Python service on `127.0.0.1:8000`. No hosted database, deployment, brokerage account, or paid API key is required.

## Compare local development with the Vercel website

The *actual* latest published Vercel source commit is pinned in
[config/production-baseline.json](config/production-baseline.json). GitHub
main includes newer unreleased work; **do not reset main to match the old
production deployment**.

Run the development application with its private backend and research worker:

```powershell
cd E:\Trading-Simulator
git pull
.\start-local.ps1
```

Use **http://127.0.0.1:5173** for ongoing npm/Vite development.

To see the exact source of the deployed Vercel version beside it, open
another PowerShell window and run:

```powershell
.\scripts\start-vercel-baseline.ps1
```

Use **http://127.0.0.1:5174** for the frozen Vercel-source preview.
The preview creates a separate detached Git worktree and does not
modify, reset, or deploy the current development application.
Both screens use the laptop API; remote password login is intentionally
replaced with localhost access in the local preview.

Inspect the unreleased frontend changes with `npm run baseline:status`.
See [exact baseline parity and release procedure](docs/VERCEL_LOCAL_PARITY.md).
A new Vercel deployment requires a major milestone and explicit approval.

## Multi-asset portfolio strategy research (beta)

**Portfolio-first is the default Strategy Discovery workflow.** Compare
five allocation families (equal weight, inverse volatility, trend filter,
relative momentum and volatility target) across **2-10 instruments**,
with shared cash, category exposure caps, estimated trading costs,
chronological validation and a held-out historical test. Review model
rankings, equity curves, correlations, holdings and simulated fills.

**Queue from the website, execute on Windows:** the primary research button
now creates a durable background job in the laptop's local SQLite queue.
`start-private-bridge.ps1` also starts the independent research worker;
jobs continue after browser close, and the web UI polls progress, supports
cancellation, and opens the complete saved study on completion. The website
requires the private PC to be powered on to enqueue new work, but a previously
queued job survives a restart. Read [browser queue setup and data locations](docs/PORTFOLIO_RESEARCH.md#queue-portfolio-research-from-the-website).
Older single-ticker SMA research remains available in its own secondary tab.

Run directly on Windows without visiting the dashboard:

```powershell
cd E:\\Trading-Simulator
git pull
powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -ComparePortfolio
```

Add `-PortfolioAssets "spy,qqq,ief,gld,eem,vnq,btcusd"` to choose
your own supported basket. Add `-EmailPortfolioStudy` for an
owner-confirmed email of the full briefing including research outcomes.

Studies are saved only to Git-ignored `data/portfolio_research.sqlite3`,
not to GitHub or Vercel. Research uses actual private-host provider candles
and does not automatically execute or deploy portfolio decisions.
See [methodology and limitations](docs/PORTFOLIO_RESEARCH.md).

## Live strategy machine, optimization, and real trade journal (beta)

The project now supports a private end-to-end workflow:

- **Strategy Discovery:** test 16 example SMA parameter combinations on separate
  training, validation, and held-out test periods. Save research outputs
  and approved candidate versions only in local, Git-ignored databases.
- **Live Strategy Machine:** deploy a saved strategy in paper or human
  execution monitoring mode. A separate Python background worker
  evaluates completed prior-day candles on trading days, records
  idempotent suggestions and suppresses stale/unreliable data.
- **Risk and notifications:** cap allocations and daily recommendations,
  block signals on feed errors, escalate missed urgent signals, and deliver
  deduplicated Discord or email alerts using private local credentials.
- **Human-confirmed execution:** record actual broker fills with editable
  price, quantity, fees, currency, timestamp, reference and notes.
  Corrections preserve an audit trail, with distinct reported results
  for different currencies.
- **Operational dashboard:** six top-level workspaces organize monitoring,
  research, strategy discovery, live signals, actual trades, and incidents.

**Email-first live monitoring:** The private Windows worker sends immediate
signal and risk notifications to your configured email recipients. It also
generates a detailed weekday 5:15 PM Toronto-time HTML and text briefing with
pending actions, portfolio positions, confirmed P/L, recent fills, risk,
strategy evaluations, research progress and operational status. You can send
a report at any time with `start-live-machine.ps1 -SendEmailReport`.
See [email setup and reporting](docs/LIVE_MACHINE.md#notification-setup).
No public server stores recipients or strategy reports.

An optional Mac-based iMessage adapter remains available but is not required.
Set `TRADING_SIM_NOTIFICATION_CHANNELS=email` to use only email.

Start the independent worker on Windows after updating:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-live-machine.ps1
```

The worker operates independently of the browser while the PC stays on.
Optionally use `-InstallAtLogon` to register a logon-triggered scheduled
task. The full local setup, privacy policy and production limitations are
in [Live machine setup and safety](docs/LIVE_MACHINE.md).

**No broker orders are automatically placed.** Actual live trading is
manual by design. Historical optimization, live signals, portfolio marks,
leverage and shorting are not guarantees of profitability. More advanced
portfolio risk controls and brokerage reconciliation remain on the roadmap.

## Vercel cloud frontend, private local data

The **Vercel deployment hosts the React website and a tiny, non-secret
connection directory endpoint**. Your strategy versions, trained models,
market archives, broker records, Python backend and Ollama remain on your PC.
Approved website visitors enter **one fixed shared password**. The
Cloudflare Quick Tunnel URL is discovered automatically, even when it changes
after restarting the PC.

To run the password-protected bridge on your own Windows computer:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-private-bridge.ps1
```

The owner sets the shared password on first launch and provides one
Vercel access token, stored only in the ignored local state directory,
to authorize updating a tiny URL-only Vercel Global Config record.
The visitor never needs a Cloudflare account, a tunnel URL, or an API token.

The browser keeps temporary authenticated sessions in memory only.
Vercel never receives passwords or financial data. See
[one-password hybrid Vercel setup](docs/VERCEL_HYBRID.md) for the
one-time owner instructions, security restrictions and troubleshooting.

## Keep your generated trading strategies private

The engine source is public. **Real strategies generated or optimized by
your research, deployed rules, selected parameters, signals, brokerage
executions and private portfolio records are NOT public source code.**
The program already saves strategy versions locally in Git-ignored
`data/` SQLite files.

New privacy checks cover generated files, databases, model weights,
secret files and common exported strategy formats. Normal local setup
installs a Git pre-commit privacy guard, and GitHub Actions rejects
detected leaks in commits and pull requests.

Read the mandatory [Strategy Privacy Policy](docs/STRATEGY_PRIVACY.md)
before committing, exporting a strategy or sharing the public demo.
Code review is still essential because automated scans cannot identify
every possible proprietary algorithm embedded in source or prose.

## Research UI, longer history, and local AI improvements

- Cleaner layouts on mobile and desktop, improved chart sizing, chart-canvas
  checks, and English/Simplified Chinese translations for dynamic simulation
  events.
- New daily simulations default to **MAX** historical data with an earlier
  replay start. Existing saved sessions are unchanged.
- Active portfolio simulations expose 1m, 5m, 15m, 1h and daily execution
  intervals. Selecting another interval starts a fresh session while retaining
  previous portfolio saves.
- Ollama preloads its configured model when the website opens. Quantitative
  instructions, revealed-only curve checkpoints and explicit UI language
  improve the context supplied for research.

See [history depth](docs/HISTORY_DEPTH.md) and
[local AI setup](docs/AI_ASSISTANT.md). No new app dependencies.

## Share a live public website

A temporary Cloudflare Quick Tunnel lets **anyone with the generated HTTPS
URL** visit the running Trading Simulator from anywhere, without being on
the same Wi-Fi or needing a Cloudflare account.

On the Windows host, install the Cloudflare tunnel agent once:

```powershell
winget install -e --id Cloudflare.cloudflared
```

Open a new PowerShell terminal in the project, then run:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-public.ps1
```

Share the `https://...trycloudflare.com` URL printed by cloudflared.
Keep the PC and tunnel window running; Ctrl+C stops the demo. The public
copy uses **separate demo databases** and a compiled preview, leaving
the private localhost paper account and saved strategies untouched.
Visitors share a disposable sandbox. Ollama and paid AI are disabled for
public visitors.

See [Public tunnel setup and privacy](docs/PUBLIC_TUNNEL.md) for details
and limitations. Quick Tunnel URLs change each time; this is not
an always-on hosted deployment.

## Mobile and tablet support

The same Trading Simulator interface adapts to phones and tablets. On small screens, use the workspace section selector to navigate replay, orders, strategy editing, analytics and trade history. Financial tables scroll inside their panels and charts resize to fit the viewport.

To use your phone on the same **trusted private Wi-Fi** as the Windows host:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Mobile
```

Open the local IPv4 address printed by the launcher (for example, `http://192.168.1.123:5173`) in your phone browser. Stop any already running frontend before enabling `-Mobile`. Keep the host PC running. This opt-in development server is unauthenticated and must not be exposed to public networks.

See [Mobile setup and touch layout](docs/MOBILE.md) for device and firewall instructions. The regular launcher remains localhost-only.

## Unified Trading Simulator v1.1

There is now **one application**, Trading Simulator. The old separate
Trading Terminal screen has been removed, and its full watchlist, market
explorer, delayed quotes, candlestick charts, independent paper-account
ledger, paper order ticket, position tables, execution history and SMA
backtester live inside the **Market Data & Paper** workspace tab.

- **Saved Strategy Library**: save unlimited named versions up to the local
  safety cap (500 entries), browse previous rules, restore them as editable
  drafts, or delete old versions. The engine also archives previous strategy
  versions when you change the active one. Versions persist locally in
  SQLite and stay separate from running strategies.
- **AI timeout repair**: local Ollama requests now allow a 240-second default
  response window, configurable from 60-600 seconds in the private
  `.env` file. The model stays warm where supported, answer sizes are
  bounded, and the UI shows processing time. No paid provider is required.
- **Unified navigation**: historical replay, integrated market and paper
  research, orders, strategy and AI, analytics, stochastic scenarios and
  trade history share the same professionally tabbed application.
- **Non-destructive backwards replay** and existing database saves remain
  available without migrations.

See [Unified Simulator, Strategy Library and AI troubleshooting](docs/UNIFIED_SIMULATOR.md).

## Stochastic research, professional workspaces and backward replay (v1.0)

- **Stochastic Scenario Research**: fit historical candle log returns and
  generate 256 reproducible GBM scenarios per instrument with percentile
  bands, a modeled probability-of-rise estimate and configurable horizons.
  Includes theoretical Black-Scholes European option valuations, explicitly
  separated from directional market forecasts.
- **Forecast-aware rules**: `PROB_UP(20)` is now a safe historical probability
  expression available in strategy code and the visual rule builder.
  All strategy decisions use revealed information only.
- **Professional tabs**: both historical simulators now organize market
  overview, orders/positions, strategy/AI, performance analytics, stochastic
  scenarios and execution history into six sections. The integrated Market Data & Paper workspace
  includes charts, orders and backtest research subviews.
  Gamification panels are hidden without changing any saved data.
- **Backwards navigation**: inspect exact prior checkpoints using previous,
  next-recorded and return-to-latest controls. Historic inspection is
  read-only and never erases or silently alters an executed trade. New
  sessions record checkpoints from the beginning, and earlier saves start
  recording when modified after this update.

See [stochastic methodology](docs/STOCHASTIC_RESEARCH.md) and
[workspace/time navigation guide](docs/WORKSPACE_NAVIGATION.md).
All calculations run locally; no API keys or new dependencies required.

## AI Strategy Assistant v0.9

Both Trading Arcade and Portfolio Arcade now have a **bilingual AI research
assistant**. Ask it to analyze your historical equity curve, drawdown, fees,
benchmark comparison, and recent fills, or request a compatible strategy for
your game basket.

- **Local-first:** default provider is a user-installed **Ollama** model.
  Alternatively, configure the OpenAI Responses API using a private backend
  key. No model subscription or key is bundled with this repository.
- **No future leakage:** only the game's revealed portfolio analytics and
  a handful of recent fills are given to the model. Stored future bars remain
  invisible, even when asking about the strategy's future performance.
- **Human approval:** proposed DSL code must pass the existing validator and
  appears in a separate preview. **Insert draft for review** only edits the
  local strategy textbox. It does not arm, backtest, trade or execute orders.
- **Privacy:** model requests are initiated only when you ask a question.
  The backend stores credentials in the ignored `.env` file, not the browser.
  Cloud mode sends the summarized game data externally.

**Setup:** for Ollama, install Ollama, run `ollama pull llama3.2`,
copy `.env.example` to `.env`, then restart the local backend.
For OpenAI, configure your provider, model, and private key in `.env`.

See [AI Strategy Assistant setup and safeguards](docs/AI_ASSISTANT.md).

## Intraday Trading Arcade v0.8

Both Arcade modes and the original Trading Terminal now offer real provider
**1-minute, 5-minute, 15-minute, hourly and daily candles**, with interval-
appropriate historical ranges. Portfolio replay uses the actual UTC timestamps
of each observed instrument candle, without fabricating stock prices during
closed sessions. Switch an Arcade chart to a wider timeframe without changing
the original execution or strategy clock.

Historical minute data has strict provider limits; Yahoo minute history is
recent-only, and Coinbase data are fetched in bounded 300-candle pages with up
to 5,000 actual intraday observations retained per symbol. Long-term daily
history and existing saved games remain unchanged.

See [Intraday data and replay guide](docs/INTRADAY.md). No new dependencies.

## Strategy analytics v0.7

**Detailed game performance research** is now built into both Arcade modes.
Each saved historical season includes a strategy analytics dashboard with:

- Adjustable **SMA overlays** and crossover markers on the historical price chart.
- Real simulated **buy/sell execution arrows**, not guessed strategy signals.
- Equity versus equal-weight buy-and-hold, drawdown, and invested-vs-cash charts.
- Returns for user-selected replay windows and **custom date ranges**.
- Per-instrument P&L attribution, full execution audit, fees, turnover, and
  profit ratios for individual sell fills.
- Separate downloadable CSVs for equity time series and full trade history.
- Read-only analytics based on stored, revealed historical prices and fills
  without peeking at upcoming market bars.

Read [Strategy Analytics methodology](docs/STRATEGY_ANALYTICS.md).
The dashboard includes **English / 简体中文** labels and uses the existing
charting package. No new dependencies or local installation steps.

## Language support: English / 简体中文

The entire frontend now has an **EN / 中文** switch, fixed at the lower-right
corner across the trading terminal, single-asset Arcade, and Portfolio Arcade.
The selection persists per browser using localStorage and can be changed at any
time without restarting or reinstalling dependencies. Trading commands,
ticker symbols, and historical data remain unchanged when switching languages.

See [中文说明 / language guide](docs/LANGUAGE.md).

## Portfolio Arcade v0.6

**New: multi-asset historical seasons.** From Trading Arcade choose
**Portfolio Arcade** to trade 2-5 USD stocks, ETFs or crypto assets with one
shared $100,000 cash account. The engine aligns real daily candles, honors
missing market sessions, and lets you skip 1, 5, 20, or 100 calendar steps.
Every instrument has its own position and mark date.

Safe cross-asset strategies can use one symbol's indicators to trade another:

```text
WHEN spy SMA(10) CROSSES ABOVE SMA(30) BUY 25% qqq
WHEN spy SMA(10) CROSSES BELOW SMA(30) SELL 100% qqq
```

New runs are stored in a separate SQLite table. **Existing Trading Arcade
saves remain intact.** There are no new dependencies, so just `git pull`
and use your existing `start-local.ps1` launcher.

See [Portfolio Arcade instructions](docs/PORTFOLIO_ARCADE.md).

## Trading Arcade v0.5 (historical depth, instruments, no-code builder)

The app now opens in the [Trading Arcade](docs/ARCADE.md) by default.
Start a historical season with a virtual $100,000 account, choose daily candles from 1 year, 2 years, 5 years, 10 years or maximum available history, manually trade
with market/limit/stop orders, fast-forward up to 20 candles at a time,
autoplay, and earn levels/badges/score for your performance against buy-and-hold.

The instrument catalog includes 138 stocks, ETFs, forex pairs, crypto pairs, CAD listings and continuous futures references. A Yahoo Finance search/import option lets you explore further equities, ETFs and indices. Actual data availability varies by symbol; options and futures are not trade-enabled.\n\nBuild rules visually using indicator selectors or write simple automated strategies, for example:

```text
WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 50%
WHEN SMA(10) CROSSES BELOW SMA(30) SELL 100%
```

The bot runs on the server, evaluates only revealed candles and queues the
strategy's orders for the next candle open. Automatic stop-loss and take-profit controls are also available; ambiguous stop/target candles conservatively select the stop. Run progress and bot rules persist
in local SQLite. Use the back arrow to return to the existing Trading Terminal.

**No new dependencies are required.** For an existing setup, run `git pull`,
then start your normal local launcher. Do not recreate or reinstall packages.

## Existing terminal and quant stack (v0.3)

- Actual historical OHLCV charts: stocks, US/Canadian ETFs, continuous futures indicators, forex, and crypto.
- **Coinbase Exchange public API** for crypto candles and real-time bid/ask snapshots.
- **Yahoo Finance (unofficial yfinance)** for other assets' historical candles and indicative last prices. May be delayed, throttled, incomplete, or unavailable; do not assume exchange accuracy or current quotes.
- Market-mode long-only USD cash paper orders on US stocks, USD ETFs, USD forex pairs, and crypto, with modeled fills, fees, conservative freshness and session guards.
- SQLite-backed paper portfolio and order ledger. Persists after restarting the application.
- NumPy-vectorized O(n) SMA signals, keeping deterministic Decimal accounting for cash/fees.
- Polars-based compressed Parquet archive for downloaded OHLCV history, with DuckDB analytical queries.
- Offline historical chart/replay fallback from previously recorded Parquet bars, clearly labeled as stale. Offline bars never become executable quotes.
- Manual historical replay with **no future price candles displayed**, separate $100,000 account, next-bar-open execution and forward stepping.
- SMA crossover historical backtest. Signals use the prior candle close and fill at the next candle open. Includes simple fee, spread and slippage models, returns, trades and drawdown.
- Chart-only futures, foreign-currency ETFs and placeholder options. **No pretend trade fills for products whose contract mechanics aren't modeled.**
- No trading provider credentials, actual broker orders, short sales, margin, corporate action adjustments, option expiration, interest, borrow costs, dividend cash flows, or accurate level II/queue simulation.

Market data are real but **fills are simulations**. Yahoo does not provide verified executable order-book quotes. Stock and forex fills use assumed spread + 2bps slippage. Coinbase crypto uses its displayed bid/ask plus 2bps. No claims of institutional accuracy.

## Requirements

- Windows, macOS or Linux.
- Node.js 22+ and npm.
- Python 3.11+ (Python 3.12 recommended).
- Internet access for the external financial data providers. If a provider errors, the UI uses an explicitly labeled **offline historical archive** if previously recorded candles exist. Otherwise it reports the failure. It never silently replaces real data with synthetic quotes.

## Run locally (Windows PowerShell)

Clone once (skip this if you already have the folder):

```powershell
git clone https://github.com/ABCPeter123/Trading-Simulator.git
cd Trading-Simulator
```

**Normal daily startup:** If you already cloned the repository, open it in VS Code and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

The launcher detects your existing `.venv` and `node_modules` and reuses them.
It installs dependencies only when missing or when dependency manifests change,
starts the local API and Vite in separate PowerShell windows, and opens
**http://127.0.0.1:5173**. It does not reset your portfolio or market archive.

To incorporate a new GitHub update, run `git pull` first, then the same launcher.
To check dependencies without starting servers, append `-SetupOnly`.

The API health endpoint is http://127.0.0.1:8000/api/health and its interactive documentation is http://127.0.0.1:8000/docs.

**Manual startup:** If dependencies are already installed, start the backend in
one terminal with `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload`
and the frontend in another with `npm run dev`. No reinstall is necessary.

For macOS/Linux use a Python virtual environment and the manual backend/frontend
commands. The one-command launcher is designed for Windows PowerShell.

See [local setup and persistent state conventions](docs/LOCAL_SETUP.md).

## Using the simulator

1. Choose a symbol and timeframe. Historical charts show their provider and timestamps.
2. In **Market** mode, paper buys/sells are available only when a valid, reasonably fresh quote exists during the supported market session. The server obtains its own quote before every order. Long-only orders require cash and may charge commissions. Off-hours market orders are blocked.
3. In **Replay** mode, choose a supported instrument, queue a buy or sell at a known bar close, then click **Next** or **+5**. Your order executes at the **next** bar's open, never using a future price when you place it. Replay uses an isolated in-memory account and resets upon symbol/timeframe changes or browser reload.
4. Expand **Strategy backtester**, enter fast/slow daily moving average periods, and run the SMA crossover. Backtest starts with $10,000 and uses a separate in-memory balance.
5. The market-mode account lives at `data/trading.sqlite3`. Its files are ignored by Git. Use the top-right **Reset** button to clear the paper account.

## Architecture

```text
Vite + React + TradingView Lightweight Charts (browser, port 5173)
   | /api proxy
FastAPI local Python service (port 8000)
   |         |                        |
   |         |                        + SQLite paper ledger: data/trading.sqlite3
   |         |                        + Polars + Zstd Parquet: data/market/<asset>/<range>.parquet
   |         |                        + DuckDB query engine (in-process; no server)
   |         + Yahoo Finance unofficial/yfinance: equities, ETFs, indicative futures, FX
   + Coinbase Exchange public REST: crypto candles and ticker bid/ask
```

The service caches quote requests briefly and guards against stale quotes. All prices are sourced on the server, including paper executions. The browser cannot submit its own fill price.

### Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/health` | GET | Local server health |
| `/api/market/{asset_id}?range=1M` | GET | OHLCV bars, source, currency and timestamp |
| `/api/quotes/{asset_id}` | GET | Latest reference price, bid/ask if available, freshness and session state |
| `/api/account` | GET | Cash, positions, fills and marks |
| `/api/orders` | POST | Execute a modeled market order server-side |
| `/api/account/reset` | POST | Reset local paper ledger |
| `/api/backtest/{asset_id}?fast=10&slow=30` | GET | Historical SMA crossover result |
| `/api/archive/{asset_id}?range=1Y` | GET | Local Parquet archive statistics via DuckDB |
| `/api/arcade/new` | POST | Create a historical game session |
| `/api/arcade/{run_id}` | GET | View only revealed candles, portfolio and progress |
| `/api/arcade/{run_id}/advance` | POST | Time skip or advance to bot action |
| `/api/arcade/{run_id}/orders` | POST | Queue market, limit or stop order |
| `/api/arcade/{run_id}/strategy` | PUT | Save a simple trading bot |

## Tests

```powershell
npm run build
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```

GitHub Actions validates both the TypeScript/Vite build and backend tests.

## Known limitations and planned work

- 45-second quote polling and periodic chart snapshots are **not** tick-by-tick live streaming.
- Forex is broker-indicative and the simplified cash ledger does not model rollover/funding.
- Options need actual contract selection, bid/ask chains, multipliers, expiration/exercise and Greeks.
- Futures need proper dated contract mapping, multipliers, margin, P&L settlement and market hours.
- US market holiday calendar and some halted-session details are not fully modeled; quote freshness reduces but does not eliminate these limitations.
- Prices lack exchange-level order book / market impact modeling; strategy fills are approximate.
- yfinance is unofficial and is intended for personal research, not commercial redistribution.

TradingView Lightweight Charts is licensed separately; the application retains its TradingView chart attribution.

## Quant computation strategy

- For market ingestion, Polars stores provider OHLCV in local Zstandard Parquet files, merging overlapping timestamps and keeping the latest bar for each timestamp. The runtime keeps short network caches to avoid redundant requests.
- For historical research, DuckDB reads those Parquet files without a server. The optional R and Python analysis examples are in [research/README.md](research/README.md).
- For strategy signals, NumPy calculates moving averages with cumulative sums in O(n) time. Decimal-based fee, fill, and cash accounting remains in the event-driven Python loop.
- The [signal benchmark](backend/benchmarks/benchmark_signals.py) reports real timings on your hardware with reproducible **benchmark-only synthetic arrays**. Its results are not claims of live-exchange latency.
- Numba is a potential next optimization for large per-event loops. Rust + PyO3 is reserved for profiling-proven execution hotspots; adding native compilation before profiling adds complexity without guaranteed benefit.
- Market-data quality, bid/ask depth, latency, fee schedules, corporate actions, and futures/options mechanics determine simulation fidelity far more than raw arithmetic speed.
