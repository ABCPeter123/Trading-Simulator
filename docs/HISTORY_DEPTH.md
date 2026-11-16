# Historical data depth and candle resolutions

Both single-asset and portfolio simulations now default to the **maximum
available daily historical range** instead of a five-year window. New
sessions begin at the earliest supported starting point (15% into the
retrieved bars). This allows replaying roughly 85% of the available record,
subject to indicator warmup and provider coverage.

This change only affects **new sessions**. A previously saved five-year
session keeps its immutable downloaded candles and past orders. To use a
longer historical window, create a new session with **1d** candles and
**Maximum available history**. You can select an explicit replay start
date when the provider has data covering that date.

## Which resolutions can go back further?

| Candle interval | Supported requested lookback |
| --- | --- |
| 1m | 7 days |
| 5m and 15m | 7, 30, or 60 days |
| 1h | 7, 30, 60 days; 6 months; 1 year |
| 1d | 1, 2, 5, or 10 years; maximum available |

Provider-specific availability may be **shorter** than these requested
windows, especially for intraday Yahoo Finance data. Minute data are
also capped at 5,000 observed candles per simulation. No system can
legitimately turn three years of daily bars into exact historical minute
data. The app never fabricates missing candles or claims a broader source
record than it retrieved.

For stocks and ETFs, maximum daily coverage depends on when Yahoo Finance
has prices for that symbol. For crypto, public Coinbase candles are limited
by the pair's history and an approximate thirteen-year request horizon.
The underlying market provider can throttle requests, change supported
history, or be unavailable. Locally recorded real-data archives are
retained for offline fallback, not extended with invented prices.

## Portfolio interval selector

In an active portfolio simulation, the **Replay candle interval** selector
shows 1m, 5m, 15m, 1h, and 1d. Changing it opens the new-session setup
with the same basket, so strategy signals, next-open fills and all price
data use the requested granularity. The current session stays saved and
can be restored via **Return to current session** or the saved-session
list. The separate **Chart interval** control can aggregate currently
loaded candles to a wider timeframe without changing the actual execution
clock. It cannot create finer candles from daily bars.

## Privacy and reproducibility

The selected candles are frozen in the local SQLite simulation snapshot.
Changing a session's resolution does not silently rewrite saved orders,
existing historical decisions or downloaded source prices. The archive
and replay execution controls operate using observed data only.

## Full-data chart rendering

Chart timeframes are now **viewports** over the complete observed dataset,
not requests to discard candles from the graph. All loaded, revealed OHLCV
bars, SMA values, execution markers, and analytics observations remain in
their respective chart series. The chart library draws the visible portion,
which lets you inspect a few candles on a phone or many years on a desktop
without permanently trimming the underlying series.

The historical replay and market price charts provide **Fit all data**
and **Latest candles** controls. They initially fit the full known history,
then support scrolling and zooming without deleting candles. When the
chart is still showing the full range, new replay candles expand that range.
If you have panned into a specific historical period, the chart preserves
your manual position.

Analytics range buttons (last 5/20/60/126/252 steps or custom dates) focus
the horizontal chart window. They never remove earlier equity, benchmark,
drawdown, or capital points. Click **All** to return to the complete
revealed history. Trade markers also no longer stop after 250 executions.

The stochastic fan chart now draws every available simulated path, with
transparent strokes and percentile curves on top. These paths are model
scenarios and never count as historical market observations.

The simulator still withholds genuinely unrevealed future replay candles,
and it cannot show historical prices the upstream provider did not supply.
These restrictions are separate from chart viewport rendering.
