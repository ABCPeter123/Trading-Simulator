"""Local-only API. Start via: python -m uvicorn backend.main:app --reload"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .assets import get_instrument
from .ledger import account_snapshot, reset_account, submit_order
from .market import history, quote, market_open
from .strategy import sma_backtest
from .archive import archive_stats

app = FastAPI(title="Trading Simulator Local API", version="0.2.0")

class NewOrder(BaseModel):
    asset_id: str
    side: Literal["buy", "sell"]
    quantity: str = Field(min_length=1, max_length=40)

@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "local", "version": "0.2.0"}

@app.get("/api/market/{asset_id}")
def market_history(asset_id: str, range: str = Query("1M")):
    return history(asset_id, range)

@app.get("/api/quotes/{asset_id}")
def market_quote(asset_id: str):
    return quote(asset_id)

@app.get("/api/account")
def get_account():
    unpriced = account_snapshot()
    prices = {}
    for position in unpriced["positions"]:
        try:
            prices[position["asset_id"]] = quote(position["asset_id"])
        except HTTPException:
            pass  # Report unpriced positions explicitly. Never invent marks.
    return account_snapshot(prices)

@app.post("/api/orders")
def place_order(order: NewOrder):
    instrument = get_instrument(order.asset_id)
    # Recheck session and actual quote timestamp per order, even if quote was cached.
    if not market_open(instrument):
        raise HTTPException(409, detail="Market session closed.")
    latest = quote(order.asset_id)
    quote_age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest["timestamp"])).total_seconds()
    if not (-60 <= quote_age <= (120 if instrument.kind == "Crypto" else 1200)):
        raise HTTPException(409, detail="Price is stale. Please refresh before trading.")
    # The server obtains the reference quote; client-supplied prices are ignored.
    fill = submit_order(order.asset_id, order.side, order.quantity, latest)
    return {"fill": fill, "account": get_account()}

@app.post("/api/account/reset")
def reset():
    reset_account()
    return get_account()

@app.get("/api/backtest/{asset_id}")
def backtest(asset_id: str, fast: int = Query(10, ge=2, le=100), slow: int = Query(30, ge=3, le=100)):
    return sma_backtest(asset_id, fast, slow)

@app.get("/api/archive/{asset_id}")
def get_archive_stats(asset_id: str, range: str = Query("1Y")):
    return archive_stats(asset_id, range)
