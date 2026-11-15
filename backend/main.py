"""Local-only API. Start via: python -m uvicorn backend.main:app --reload"""
from __future__ import annotations
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .assets import get_instrument
from .ledger import account_snapshot, reset_account, submit_order
from .market import history, quote
from .strategy import sma_backtest

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
    get_instrument(order.asset_id)
    # The server obtains a fresh quote; it never trusts an order's client price.
    latest = quote(order.asset_id)
    fill = submit_order(order.asset_id, order.side, order.quantity, latest)
    return {"fill": fill, "account": get_account()}

@app.post("/api/account/reset")
def reset():
    reset_account()
    return get_account()

@app.get("/api/backtest/{asset_id}")
def backtest(asset_id: str, fast: int = Query(10, ge=2, le=100), slow: int = Query(30, ge=3, le=100)):
    return sma_backtest(asset_id, fast, slow)
