# Strategy Analytics, Arcade v0.7

A detailed local-first research dashboard is available in both the
single-instrument **Trading Arcade** and multi-instrument **Portfolio Arcade**.

## Price chart and execution overlays

The historical price chart now supports:

- Candlestick and line views with volume.
- Two independently selectable SMA lookbacks (5, 10, 20, 30, 50, 100, 150,
  or 200 historical candles, depending on the control).
- Visible SMA line values computed at each revealed candle close.
- Optional circles when the selected fast/slow SMA lines cross. These indicate
  *indicator crosses*, not necessarily a queued/executed strategy order.
- Green arrows at actual modeled **buy fills**, red arrows at **sell fills**.
  These represent execution timestamps, not when rules were written or queued.
- Individual switches to show/hide overlays, crossings, and fill markers.

The indicators use only observed closes up to and including the displayed
candle. No future prices are read from frozen game snapshots.

## Analytics dashboard

A separate analysis report reconstructs every **modeled** fill and fee from the
saved SQLite season, using the original frozen data. Both modes show:

| Chart or panel | Details |
| --- | --- |
| Equity vs benchmark | Your simulated portfolio value against price-only equal-weight buy-and-hold. Single-asset mode uses that same instrument as benchmark. |
| Drawdown | Percentage decline from the highest earlier marked portfolio value. |
| Cash vs invested | Daily marked portfolio exposure and remaining uninvested cash. |
| Summary | Total return, excess return, maximum drawdown, modeled fees, notional turnover, invested amount, and profitable-exit rate. |
| Rolling periods | Returns over 5, 20, 60, 126, and 252 **replay steps**, where history permits. |
| Attribution | Position quantities, approximate portfolio weights, average cost, unrealized P&L, realized P&L, and last observed prices. |
| Execution audit | Every past fill's date, symbol, direction, size, price, notional, fee, net cash change, and whether a bot, risk rule or manual ticket placed it. |

Chart filters show all progress or the most recent 5, 20, 60, 126, or
252 replay steps. Download the equity time-series and execution history
separately using the **Export CSV** and **Export trades** controls.

The analysis updates as time advances and is available on saved sessions.

## Integrity and limitations

- The report is calculated using only the game's saved, **revealed** bars
  through the active replay index. When a stock is closed and another
  instrument trades, its last known close is used to mark existing positions,
  not as a fabricated tradable candle.
- Crossover circles are visual indicator events. Trades always follow actual
  queued order and next-open execution rules. An indicator signal does not
  guarantee a trade.
- The benchmark uses equal starting notionals, a fixed initial capital of
  $100,000, and last observed closes. It is a **price-only benchmark** without
  dividends, splits, tracking error, transaction costs, FX or option contracts.
- Portfolio strategy equity is reconstructed using the **full persisted fill
  history**, including modeled commissions. It includes no interest, tax,
  market impact, stock split adjustments, or actual broker execution quality.
- The profitable-exit ratio counts positive versus non-positive individual
  sell-fill P&L relative to current average cost. It is not win rate per
  complete round trip, and buy fees are included in average cost.
- Rolling windows count shared timeline steps. A stock/crypto basket includes
  weekends, so 20 steps are **not** always 20 stock trading sessions.
- Open unrealized P&L and realized P&L are not forecasts of future returns.

## APIs and tests

`GET /api/arcade/{run_id}/analytics`

`GET /api/portfolio-seasons/{run_id}/analytics`

`backend/strategy_analytics.py` is a dependency-free server-side calculator.
`backend/tests/test_strategy_analytics.py` exercises fees, benchmark returns,
missing candles, trade attribution and prevention of hidden-future leakage.

No new Python or npm packages are required, and no existing saved games or
local market caches are deleted.
