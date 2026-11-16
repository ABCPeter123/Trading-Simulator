# Intraday Historical Replay (v0.8)

The same time-resolution controls now appear in the Trading Terminal, Trading
Arcade, and Portfolio Arcade. You can choose **1m, 5m, 15m, 1h or 1d**.

## Start a season

1. Open the existing local project and use `start-local.ps1`.
2. Select a mode and pick a supported USD instrument or portfolio basket.
3. Choose **Replay candle interval**, then select a permitted historical range.
4. Create a season, submit orders or arm a bot and move forward using **Next
   candle**, **+5**, **+20**, or autoplay. The unit is the game candle, not a
   fixed number of calendar days.
5. During the game, use **Chart interval** to display your already revealed
   candles aggregated into a coarser timeframe. This affects **display only**.

The original Trading Terminal's **Candle interval** control re-downloads
provider candles at the selected resolution when switched.

## Supported interval and lookback combinations

| Candle size | Allowed history requests |
| --- | --- |
| 1 minute (`1m`) | `7D` |
| 5 minutes (`5m`) | `7D`, `30D`, `60D` |
| 15 minutes (`15m`) | `7D`, `30D`, `60D` |
| 1 hour (`1h`) | `7D`, `30D`, `60D`, `6M`, `1Y` |
| 1 day (`1d`) | `1Y`, `2Y`, `5Y`, `10Y`, `MAX` |

This matrix is a conservative provider *request* limit, **not a guarantee**
that the provider holds candles for that full interval.

- Yahoo Finance is unofficial and can throttle, change, or deny requests.
  In practice the 1-minute lookback is about 7 days (the adapter requests
  6 days), 5-15 minute bars about 60 days, and 1-hour history considerably
  longer, with varying availability.
- Coinbase Exchange supports 60, 300, 900, 3600, 21600 and 86400 second
  candle sizes, at most 300 candles per API request. The local adapter pages
  backward and caps one intraday snapshot at the **latest 5,000 actual bars**
  to prevent unbounded network traffic, RAM and browser rendering.
  For example, 5,000 continuous 1-minute crypto bars span only about 3.5
  calendar days, even if `7D` was requested.
- The dataset is frozen per game and archived in Parquet under separate
  `data/market/{asset_id}/{window}_{resolution}.parquet` files. Previously
  downloaded daily data and saved sessions are not overwritten.
- If the source is unavailable and a local archive exists for the exact
  symbol/window/resolution, the simulator can load those recorded bars and
  clearly labels them as archived, not live.

## Execution and indicator accuracy

- In a 1-minute season, `SMA(20)` uses **20 observed 1-minute candles**.
  In a 1-hour season it uses 20 hourly candles. Gaps and closed sessions
  remain gaps; a 20-candle indicator is not necessarily a 20-minute clock
  period when data are missing.
- Strategy conditions are evaluated only on revealed candles and orders
  are queued for no earlier than the next observed candle **for the target
  instrument**. A bar-less symbol cannot trade at an invented fill.
- In Portfolio Arcade, each instrument's original UTC candle timestamps
  are aligned on one **union event clock**. A mixed basket can have a valid
  stock mark from the previous session while cryptocurrency continues.
  Baskets require at least two actual overlapping calendar dates and
  recent common activity.
- The chart-only aggregation uses earliest open, observed maximum high,
  observed minimum low, latest close, and summed volume for the chosen
  time bucket. **No unseen candles are included**. Trade arrows map to
  the corresponding displayed bucket.
- The two SMA overlays are calculated from **displayed chart candles**.
  Your bot evaluates its rules using the original replay granularity.
  Thus, switching the chart from 1m to 1h does **not** change or retroactively
  trigger the strategy.
- Existing daily Arcade saves retain their original `1d` resolution and
  SQLite snapshots. No schema migration or reinstall is necessary.
- The analytics report uses unique timestamps in intraday games, so it
  preserves multiple fills and equity observations during the same day.
  Rolling windows count observed timeline steps, not clock minutes.

## Remaining modeling limitations

These are historical bar-based **simulations**. They do not reconstruct
exchange order books, tick-by-tick sequences, bid/ask at individual historical
times, queue priority, liquidity and partial fills. Stop and limit triggers
use observed OHLC ranges with model spread and fees. A future upgrade can
add a licensed long-term minute data provider, proper intraday sessions and
more detailed order execution modeling, but no unavailable prices should
ever be fabricated to fill gaps.

## APIs

- `GET /api/market/{asset_id}?range=7D&resolution=1m`
- `POST /api/arcade/new` with `{"asset_id":"spy","period":"7D","resolution":"1m"}`
- `POST /api/portfolio-seasons` with
  `{"asset_ids":["spy","qqq"],"period":"7D","resolution":"1m"}`

Older clients that omit `resolution` keep their previous default behavior.
