# Trading Simulator

A **local-first paper trading and historical replay terminal** using public financial market data. It runs in your browser at `127.0.0.1:5173` with a Python service on `127.0.0.1:8000`. No hosted database, deployment, brokerage account, or paid API key is required.

## Status (v0.2)

- Actual historical OHLCV charts: stocks, US/Canadian ETFs, continuous futures indicators, forex, and crypto.
- **Coinbase Exchange public API** for crypto candles and real-time bid/ask snapshots.
- **Yahoo Finance (unofficial yfinance)** for other assets' historical candles and indicative last prices. May be delayed, throttled, incomplete, or unavailable; do not assume exchange accuracy or current quotes.
- Market-mode long-only USD cash paper orders on US stocks, USD ETFs, USD forex pairs, and crypto, with modeled fills, fees, conservative freshness and session guards.
- SQLite-backed paper portfolio and order ledger. Persists after restarting the application.
- Manual historical replay with **no future price candles displayed**, separate $100,000 account, next-bar-open execution and forward stepping.
- SMA crossover historical backtest. Signals use the prior candle close and fill at the next candle open. Includes simple fee, spread and slippage models, returns, trades and drawdown.
- Chart-only futures, foreign-currency ETFs and placeholder options. **No pretend trade fills for products whose contract mechanics aren't modeled.**
- No trading provider credentials, actual broker orders, short sales, margin, corporate action adjustments, option expiration, interest, borrow costs, dividend cash flows, or accurate level II/queue simulation.

Market data are real but **fills are simulations**. Yahoo does not provide verified executable order-book quotes. Stock and forex fills use assumed spread + 2bps slippage. Coinbase crypto uses its displayed bid/ask plus 2bps. No claims of institutional accuracy.

## Requirements

- Windows, macOS or Linux.
- Node.js 22+ and npm.
- Python 3.11+ (Python 3.12 recommended).
- Internet access for the external financial data providers. If a provider errors, the UI reports a failure and does **not** silently replace it with fake data.

## Run locally (Windows PowerShell)

Clone once:

```powershell
git clone https://github.com/ABCPeter123/Trading-Simulator.git
cd Trading-Simulator
```

**Terminal 1, start Python API:**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2, start browser UI:**

```powershell
npm install
npm run dev
```

Open **http://127.0.0.1:5173**. Both terminals must remain running.

The API health endpoint is http://127.0.0.1:8000/api/health and its interactive documentation is http://127.0.0.1:8000/docs.

On macOS/Linux, replace `py -3 -m venv .venv` with `python3 -m venv .venv`, use `.venv/bin/python` instead of `.venv\Scripts\python.exe`.

For future updates, run `git pull` before starting. Then reinstall dependencies if the requirements or package files changed.

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
