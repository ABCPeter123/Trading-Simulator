# Portfolio Arcade v0.6

Multi-asset historical trading with one shared USD cash ledger. This feature
uses a **new SQLite table** (`portfolio_seasons` in `data/arcade.sqlite3`) and
does **not** migrate or change existing single-asset Arcade sessions.

## Start a portfolio season

1. Open the existing local application in VS Code with the normal launcher.
2. From Trading Arcade choose **Portfolio Arcade**.
3. Select **2-5** USD-denominated stocks, ETFs, or spot crypto assets.
4. Choose the historical range (1Y, 2Y, 5Y, 10Y, or MAX), and optionally a
   historical starting date.
5. Play with a shared $100,000 USD cash account.
6. Select an asset tab to place market, limit, or stop orders. Time skip or
   autoplay the shared daily calendar. Every asset tracks a separate position,
   weighted-average cost, and realized/unrealized P&L.
7. Enter a cross-asset strategy in the strategy lab, save it, and advance time.

## Cross-asset DSL

```text
# SPY signal controls a trade in QQQ
WHEN spy SMA(10) CROSSES ABOVE SMA(30) BUY 25% qqq
WHEN spy SMA(10) CROSSES BELOW SMA(30) SELL 100% qqq
```

The first identifier after `WHEN` is the **signal symbol ID**. The last
identifier is the **trade target ID**. Both must belong to the chosen basket.

The rest of each rule uses the existing safe, edge-triggered language:
PRICE, SMA(n), RSI(n), numeric thresholds, ABOVE, BELOW, CROSSES ABOVE,
CROSSES BELOW, and BUY/SELL a percentage of available cash or held units.

An SPY crossover on Friday cannot buy QQQ until QQQ's next actual recorded bar.
Bots cannot trade a symbol on days when its market has no candle.

## Synchronized data and execution

The backend requests daily candles for all selected symbols, normalizes them
to **UTC calendar days**, and creates a single union timeline. OHLCV data are
never forward filled. If one asset lacks a candle for a given day:

- Its orders remain pending until that asset's next real observed candle.
- Its open position is valued using the last **revealed** close, with the
  mark date shown in the UI. Stale marks are explicitly distinguishable.
- Its bot does not evaluate a signal on the missing day.
- A cryptocurrency may trade on Saturday while a stock remains idle.

A basket must contain sufficient overlapping history, including at least
36 warm-up observations for each symbol and about 45 playable calendar days.
If the provider cannot supply these, season creation fails visibly.

All markets are simulations: market orders use next-bar opens, synthetic
spread/slippage/commission models, and optional stop-loss/take-profit orders.
Limit fills cannot represent exchange queues, intrabar path, depth or partial
fills. Equity baselines are simplified equal-weight buy-and-hold approximations
without corporate action or dividend adjustments. FX cross-currency settlement,
futures margin and options multipliers are intentionally out of scope.

## Persistence and tests

Shared-cash seasons, instrument snapshots, bot scripts, positions, fills, and
current replay dates persist in local SQLite:

```text
data/arcade.sqlite3
  game_sessions      # original single-asset saves, unchanged
  portfolio_seasons  # new multi-asset seasons
```

Your normal `start-local.ps1` launcher does not reset either table. The change
adds **no dependencies**, so pull the GitHub update and restart the launcher
without reinstalling packages.

The offline tests for this feature are under
`backend/tests/test_portfolio_arcade.py`. They test shared cash,
cross-asset signals, anti-lookahead, non-trading days, risk controls, and
session restoration.
