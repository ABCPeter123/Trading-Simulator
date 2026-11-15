"""Historical OHLCV and quote adapters. No synthetic fallback.

Crypto: public Coinbase Exchange API. Others: unofficial Yahoo Finance/yfinance
for local personal research. Yahoo may delay, throttle, or stop serving requests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from threading import Lock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo
import math

import httpx
import yfinance as yf
from fastapi import HTTPException
from .assets import Instrument, get_instrument

RANGE_CONFIG = {
    "1D": ("5d", "5m", 300),
    "1W": ("7d", "30m", 300),
    "1M": ("1mo", "1h", 400),
    "3M": ("3mo", "1d", 300),
    "1Y": ("1y", "1d", 400),
}
COINBASE_SECONDS = {"1D": 300, "1W": 3600, "1M": 21600, "3M": 86400, "1Y": 86400}
COINBASE_DAYS = {"1D": 1, "1W": 7, "1M": 30, "3M": 90, "1Y": 365}
_client = httpx.Client(timeout=13, headers={"User-Agent": "TradingSimLocal/0.2"})
_lock = Lock()
_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

def clear_cache() -> None:
    with _lock:
        _cache.clear()

def cached(key: tuple[str, str], seconds: int, loader) -> dict[str, Any]:
    with _lock:
        current = _cache.get(key)
        if current and monotonic() - current[0] < seconds:
            return current[1]
    result = loader()
    with _lock:
        _cache[key] = (monotonic(), result)
    return result

def f(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Invalid market value")
    return result

def coinbase_candles(asset: Instrument, window: str) -> list[dict[str, float | int]]:
    step = COINBASE_SECONDS[window]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=COINBASE_DAYS[window])
    rows_by_time: dict[int, dict] = {}
    chunk_end = end
    # API limit: up to 300 intervals per request. Fetch from the end backward.
    while chunk_end > start and len(rows_by_time) < 450:
        chunk_start = max(start, chunk_end - timedelta(seconds=step * 290))
        try:
            resp = _client.get(
                f"https://api.exchange.coinbase.com/products/{asset.ticker}/candles",
                params={"granularity": step, "start": chunk_start.isoformat(), "end": chunk_end.isoformat()},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, detail=f"Coinbase price service unavailable: {type(exc).__name__}") from exc
        if not isinstance(data, list):
            raise HTTPException(503, detail="Coinbase returned an unexpected response.")
        for row in data:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                timestamp, low, high, opening, closing, volume = row[:6]
                item = {"time": int(timestamp), "open": f(opening), "high": f(high),
                        "low": f(low), "close": f(closing), "volume": f(volume)}
                if item["time"] <= int(end.timestamp()):
                    rows_by_time[item["time"]] = item
            except (TypeError, ValueError, OverflowError):
                continue
        chunk_end = chunk_start - timedelta(seconds=1)
        if len(rows_by_time) >= 440:
            break
    return sorted(rows_by_time.values(), key=lambda bar: bar["time"])[-400:]

def yahoo_candles(asset: Instrument, window: str) -> list[dict[str, float | int]]:
    period, interval, limit = RANGE_CONFIG[window]
    try:
        data = yf.Ticker(asset.ticker).history(period=period, interval=interval, auto_adjust=False, timeout=12)
    except Exception as exc:
        raise HTTPException(503, detail=f"Yahoo Finance price service unavailable: {type(exc).__name__}") from exc
    result = []
    for timestamp, row in data.tail(limit).iterrows():
        try:
            # Some FX and index feeds have no exchange-reported volume.
            # Preserve their legitimate OHLC bars with 0 volume instead of discarding them.
            raw_volume = row.get("Volume", 0)
            volume = float(raw_volume)
            volume = volume if math.isfinite(volume) and volume >= 0 else 0.0
            item = {"time": int(timestamp.timestamp()), "open": f(row["Open"]), "high": f(row["High"]),
                    "low": f(row["Low"]), "close": f(row["Close"]), "volume": volume}
            if all(item[k] > 0 for k in ("open", "high", "low", "close")):
                result.append(item)
        except (ValueError, TypeError, OverflowError):
            continue
    return result

def history(asset_id: str, window: str) -> dict[str, Any]:
    instrument = get_instrument(asset_id)
    if window not in RANGE_CONFIG:
        raise HTTPException(400, detail="Unsupported chart range.")
    if not instrument.ticker:
        raise HTTPException(422, detail="Select an actual dated option contract to load option history.")
    def load():
        bars = coinbase_candles(instrument, window) if instrument.kind == "Crypto" else yahoo_candles(instrument, window)
        if not bars:
            raise HTTPException(503, detail="No market data available for this symbol and timeframe.")
        return {
            "asset_id": asset_id, "range": window, "source": "Coinbase Exchange" if instrument.kind == "Crypto" else "Yahoo Finance (unofficial)",
            "currency": instrument.currency, "bars": bars,
            "as_of": datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc).isoformat(),
            "is_demo": False, "delayed_or_indicative": instrument.kind != "Crypto",
        }
    return cached(("history:"+asset_id, window), 75 if window in ("1D", "1W") else 240, load)

def market_open(instrument: Instrument, now: datetime | None = None) -> bool:
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    if instrument.kind == "Crypto":
        return True
    if instrument.kind in ("Stocks", "ETFs", "Futures"):
        return now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0)
    if instrument.kind == "Forex":
        return (now.weekday() == 6 and now.hour >= 17) or now.weekday() in (0, 1, 2, 3) or (now.weekday() == 4 and now.hour < 17)
    return False

def quote(asset_id: str) -> dict[str, Any]:
    instrument = get_instrument(asset_id)
    if not instrument.ticker:
        raise HTTPException(422, detail="Illustrative option placeholder has no live price.")
    def load():
        now = datetime.now(timezone.utc)
        if instrument.kind == "Crypto":
            try:
                response = _client.get(f"https://api.exchange.coinbase.com/products/{instrument.ticker}/ticker")
                response.raise_for_status()
                data = response.json()
                price, bid, ask = f(data["price"]), f(data["bid"]), f(data["ask"])
                timestamp = datetime.fromisoformat(data["time"].replace("Z", "+00:00"))
                if price <= 0 or bid <= 0 or ask <= 0 or bid > ask:
                    raise ValueError("Invalid ticker")
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise HTTPException(503, detail=f"Unable to obtain Coinbase quote: {type(exc).__name__}") from exc
            source = "Coinbase Exchange"
        else:
            # Yahoo returns historical candles, not executable bid/ask order book.
            # Last 5-minute bar close is an *indicative* reference, never a live quote.
            try:
                df = yf.Ticker(instrument.ticker).history(period="5d", interval="5m", auto_adjust=False, timeout=12)
                valid = df["Close"].dropna()
                if valid.empty:
                    raise ValueError("No close prices")
                price = f(valid.iloc[-1])
                timestamp = valid.index[-1].to_pydatetime().astimezone(timezone.utc)
                bid = ask = None
            except Exception as exc:
                raise HTTPException(503, detail=f"Unable to obtain Yahoo price: {type(exc).__name__}") from exc
            source = "Yahoo Finance (unofficial, indicative)"
        age = (now - timestamp).total_seconds()
        # Conservative trading guard. Weekends/holidays and stale quotes cannot trade.
        fresh = -60 <= age <= (120 if instrument.kind == "Crypto" else 1200)
        is_open = market_open(instrument)
        return {
            "asset_id": asset_id, "price": price, "bid": bid, "ask": ask,
            "currency": instrument.currency, "timestamp": timestamp.isoformat(),
            "source": source, "as_of_age_seconds": max(age, 0),
            "market_open": is_open, "fresh": fresh, "tradable": instrument.tradable and is_open and fresh,
            "spread_bps": instrument.spread_bps,
            "execution_model": "exchange_bid_ask_plus_slippage" if bid is not None else "indicative_close_plus_assumed_spread_and_slippage",
            "block_reason": ("Contract/currency not supported" if not instrument.tradable else
                             "Market session closed" if not is_open else
                             "Quote is stale" if not fresh else None),
        }
    return cached(("quote",asset_id), 12 if instrument.kind == "Crypto" else 45, load)
