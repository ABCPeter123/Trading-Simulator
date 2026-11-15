# Trading Arcade v0.4

A gamified, local historical trading simulator. It uses actual provider OHLCV
candles, a frozen market snapshot per run, and a backend-run game engine.

## How to play

1. Run `git pull` to get updates, then launch with `powershell -ExecutionPolicy Bypass -File .\start-local.ps1`. The launcher reuses installed dependencies and the local environment. No new Python or Node dependencies were added for Arcade.
2. Arcade opens by default at http://127.0.0.1:5173.
3. Pick a supported USD stock, ETF, crypto pair, or forex pair. Options, futures and CAD-denominated ETFs remain disabled until realistic contract models exist.
4. Start a season with $100,000 in virtual cash. A real historical market is frozen into `data/arcade.sqlite3` for that run.
5. Place a **buy** or **sell** order. Choose a percentage of cash/holdings or a number of units.
6. Advance the historical market by 1, 5 or 20 bars, use autoplay, or skip to the next bot action.
7. Create or paste a strategy in the Workshop, click **Save & arm bot**, and advance time. The bot automatically checks the revealed market history.
8. Try to beat the same instrument's buy-and-hold return while controlling drawdown. Earn XP and badges. Your completed and incomplete seasons remain available after restart.

## Order execution

The backend is the authority for cash, positions, queued orders and fills.
You cannot place an order at an arbitrarily selected historical fill price.

- **Market buy/sell**: submitted at a known bar close, fills at the next bar open with assumed half-spread, 2 basis points additional slippage and simulated commission.
- **Limit buy/sell**: fills if the next or subsequent bars' low/high reaches the limit. A favorable gap at the opening may improve the fill. A limit cannot execute at a worse-than-limit price.
- **Stop buy/sell**: activates when the bar touches the stop; a gap through the stop uses the opening and can slip past the trigger.
- All order types support percent or unit sizing; stock/ETF quantities are whole shares, crypto and spot FX allow fractions.
- Buy orders are cash-only, sell orders are long-only. There is no leverage, shorting, borrowing, interest, dividends, and no actual routing to a brokerage.
- OHLC bars cannot reveal intrabar path or order-book depth. A touched limit is assumed filled without queue/volume verification; this is an approximation, not guaranteed fill realism.
- Market snapshots may be **delayed or unofficial**. The game preserves the snapshot when a run begins, so later source revisions do not change that run.

## The simple strategy language

Rules are one per line, optionally preceded by lines starting with `#`:

```text
# Trend-following example
WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 50%
WHEN SMA(10) CROSSES BELOW SMA(30) SELL 100%
```

Another example:

```text
WHEN RSI(14) BELOW 30 BUY 25%
WHEN RSI(14) ABOVE 70 SELL 100%
```

And:

```text
WHEN PRICE ABOVE SMA(20) BUY 20%
WHEN PRICE BELOW SMA(20) SELL 100%
```

Supported indicators: `PRICE`, `SMA(n)`, `RSI(n)`, and numerical thresholds. Periods are 2 through 100.
Conditions: `ABOVE`, `BELOW`, `CROSSES ABOVE`, `CROSSES BELOW`. All of these are *edge-triggered*, meaning a rule only fires on a cross, not on every bar that stays above or below the threshold.

Actions: `BUY N%` of available USD cash, or `SELL N%` of the held asset. Maximum 12 active rules and 1800 characters. An automated strategy triggers no more than one rule each bar. The strategy code is parsed with a strict grammar, never executed using `eval` or Python.

**Lookahead protection:** The bot evaluates signals using only closes up to the current revealed bar. Orders queue after that bar closes and cannot execute before the next bar opens. Game HTTP responses include only revealed candles; hidden future bars remain on the backend. This isn't a competitive anti-cheat platform since historical market data can be accessed externally.

## Local files and persistence

- `data/arcade.sqlite3` contains saved sessions, compressed historical price snapshots, queued orders, fills, bot code and progress.
- `data/trading.sqlite3` remains the separate market-mode paper trading ledger.
- `data/market/` retains recorded provider market bars as Parquet.
- None of these files are committed to Git.
- The browser remembers your selected arcade run. If browser state is cleared, you can still resume from the server's saved-run list.

The launcher does not wipe any of the above storage.

## API endpoints

| Method | Route | Description |
| --- | --- | --- |
| GET | `/api/arcade/runs` | List saved sessions |
| POST | `/api/arcade/new` | Create a frozen historical game snapshot |
| GET | `/api/arcade/{run_id}` | Revealed candles and current game state |
| POST | `/api/arcade/{run_id}/advance` | Advance 1–100 bars; optional until_action |
| POST | `/api/arcade/{run_id}/orders` | Queue a paper market, limit or stop order |
| DELETE | `/api/arcade/{run_id}/orders/{order_id}` | Cancel an unfilled order |
| PUT | `/api/arcade/{run_id}/strategy` | Save validated bot rules |
| POST | `/api/arcade/validate` | Check strategy syntax without executing |
| GET | `/api/arcade/examples` | Examples of the supported language |

Run `python -m pytest -q backend/tests/test_arcade.py` from the repository root with your existing local Python environment.

## Next fidelity upgrades

Session calendars and corporate actions, asset-specific commission models, multi-asset portfolios, order-book reconstruction from licensed Level II data, tick-by-tick replay, more realistic fills/partial fills, and robust parameter tuning. Keep each precision step tied to data you actually have.
