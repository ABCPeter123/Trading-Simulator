"""Intraday Arcade snapshots: real provider OHLCV, bounded and cached.

The authoritative replay uses source bars at the chosen granularity. Chart
resampling is client-only; no unavailable finer candles are manufactured.
Yahoo minute history is recent-only; Coinbase API pages are capped at 300.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from time import monotonic, sleep
from fastapi import HTTPException
import httpx
import logging

from . import market
from .archive import load_archived_history, record_history
from .assets import get_instrument

# Conservative provider windows; a request outside this matrix fails rather
# than returning daily bars silently mislabelled as minute bars.
REPLAY_WINDOWS = {
    "1m": ("7D",),
    "5m": ("7D", "30D", "60D"),
    "15m": ("7D", "30D", "60D"),
    "1h": ("7D", "30D", "60D", "6M", "1Y", "2Y"),
    "1d": ("1Y", "2Y", "5Y", "10Y", "15Y", "20Y", "MAX"),
}
SPAN_DAYS = {"7D": 6, "30D": 30, "60D": 59, "6M": 182, "1Y": 364, "2Y": 729}
SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
MAX_INTRADAY_BARS = 20000
LOGGER = logging.getLogger(__name__)


def validate_replay_window(period: str, resolution: str) -> None:
    if resolution not in REPLAY_WINDOWS or period not in REPLAY_WINDOWS[resolution]:
        raise HTTPException(
            422, detail=f"Unsupported replay resolution/window: {resolution}/{period}. "
                        "Minute data has a limited lookback. Use daily bars for long history."
        )


def _valid(bar):
    try:
        values = [float(bar[k]) for k in ("open", "high", "low", "close", "volume")]
        return (all(isfinite(n) for n in values) and
                min(values[:4]) > 0 and values[4] >= 0 and
                values[1] >= max(values[0], values[2], values[3]) and
                values[2] <= min(values[0], values[1], values[3]))
    except (KeyError, TypeError, ValueError):
        return False


def fetch_yahoo(asset, start, end, resolution):
    try:
        frame = market.yf.Ticker(asset.ticker).history(
            start=start, end=end, interval=resolution,
            auto_adjust=False, prepost=False, timeout=12
        )
    except Exception as exc:
        raise HTTPException(503, detail=f"Yahoo intraday price service unavailable: {type(exc).__name__}") from exc
    rows = {}
    for ts, candle in frame.iterrows():
        try:
            v = candle.get("Volume", 0)
            volume = float(v)
            bar = {"time": int(ts.timestamp()), "open": float(candle["Open"]),
                   "high": float(candle["High"]), "low": float(candle["Low"]),
                   "close": float(candle["Close"]),
                   "volume": volume if isfinite(volume) and volume >= 0 else 0.0}
            if _valid(bar):
                rows[bar["time"]] = bar
        except (TypeError, ValueError, OverflowError):
            continue
    return [rows[k] for k in sorted(rows)][-MAX_INTRADAY_BARS:]


def fetch_coinbase(asset, start, end, resolution):
    step = SECONDS[resolution]
    rows = {}
    cursor = end
    earliest_next_request = monotonic()
    # Limit outbound requests: 5000 candles + one partial page. No infinite
    # pagination across years of 1-minute data.
    while cursor > start and len(rows) < MAX_INTRADAY_BARS:
        previous = max(start, cursor - timedelta(seconds=step*290))
        try:
            params = {"granularity": step,
                      "start": previous.isoformat(), "end": cursor.isoformat()}
            for attempt in range(3):
                remaining = earliest_next_request - monotonic()
                if remaining > 0:
                    sleep(remaining)
                earliest_next_request = monotonic() + 0.12
                response = market._client.get(
                    f"https://api.exchange.coinbase.com/products/{asset.ticker}/candles",
                    params=params,
                )
                # Coinbase anonymous requests can be throttled. Retry a
                # bounded number of times, never silently forge missing bars.
                if getattr(response, "status_code", 200) == 429 and attempt < 2:
                    sleep(0.5 * (attempt+1))
                    continue
                response.raise_for_status()
                candles = response.json()
                break
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, detail=f"Coinbase intraday service unavailable: {type(exc).__name__}") from exc
        if not isinstance(candles, list):
            raise HTTPException(503, detail="Invalid Coinbase candle response.")
        for candle in candles:
            if not isinstance(candle, list) or len(candle) < 6:
                continue
            try:
                t, low, high, op, close, volume = candle[:6]
                bar = {"time": int(t), "open": float(op), "high": float(high),
                       "low": float(low), "close": float(close), "volume": float(volume)}
                if _valid(bar) and start.timestamp() <= bar["time"] <= end.timestamp():
                    rows[bar["time"]] = bar
            except (ValueError, TypeError, OverflowError):
                continue
        cursor = previous - timedelta(seconds=1)
    return [rows[k] for k in sorted(rows)][-MAX_INTRADAY_BARS:]


def replay_history(asset_id: str, period: str, resolution: str = "1d"):
    validate_replay_window(period, resolution)
    if resolution == "1d":
        # Preserve existing mocks and daily archive/save behavior.
        return market.history(asset_id, period)

    asset = get_instrument(asset_id)
    if not asset.ticker:
        raise HTTPException(422, detail="No historical market symbol for this instrument.")
    archive_key = f"{period}_{resolution}"

    def load():
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=SPAN_DAYS[period])
        try:
            bars = (fetch_coinbase(asset, start, end, resolution) if asset.kind == "Crypto"
                    else fetch_yahoo(asset, start, end, resolution))
            if not bars:
                raise HTTPException(503, detail="No real intraday candles available for this instrument.")
            source = "Coinbase Exchange" if asset.kind == "Crypto" else "Yahoo Finance (unofficial)"
            response = {
                "asset_id": asset_id, "range": archive_key,
                "period": period, "resolution": resolution,
                "source": source, "currency": asset.currency,
                "bars": bars, "as_of": datetime.fromtimestamp(
                    bars[-1]["time"], timezone.utc).isoformat(),
                "is_demo": False, "delayed_or_indicative": asset.kind != "Crypto",
            }
            try:
                record_history(response)
            except Exception as exc:
                LOGGER.warning("Intraday archive write failed: %s", exc)
            return response
        except HTTPException:
            try:
                recorded = load_archived_history(asset_id, archive_key)
            except Exception as exc:
                LOGGER.warning("Intraday archive read failed: %s", exc)
                recorded = []
            if not recorded:
                raise
            return {
                "asset_id": asset_id, "range": archive_key,
                "period": period, "resolution": resolution,
                "source": "Local Parquet archive (offline intraday snapshot)",
                "currency": asset.currency, "bars": recorded,
                "as_of": datetime.fromtimestamp(recorded[-1]["time"], timezone.utc).isoformat(),
                "offline_cache": True, "is_demo": False, "delayed_or_indicative": True,
            }

    return market.cached((f"replay:{asset_id}", archive_key), 240, load)
