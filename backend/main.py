"""Local-only API. Start via: python -m uvicorn backend.main:app --reload"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .assets import get_instrument, list_instruments, search_yahoo, import_yahoo
from .ledger import account_snapshot, reset_account, submit_order
from .market import history, quote, market_open
from .strategy import sma_backtest
from .archive import archive_stats
from .arcade import start_run, get_run, list_runs, submit_order as submit_arcade_order, cancel_order, set_strategy, advance_run, set_risk
from .arcade_dsl import compile_rules, EXAMPLES

app = FastAPI(title="Trading Simulator Local API", version="0.8.0")

class NewOrder(BaseModel):
    asset_id: str
    side: Literal["buy", "sell"]
    quantity: str = Field(min_length=1, max_length=40)

@app.get("/api/instruments")
def instruments(search: str = Query("", max_length=80), category: str = Query("", max_length=30), limit: int = Query(500, ge=1, le=500)):
    return list_instruments(search, category, limit)

@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "local", "version": "0.8.0"}

@app.get("/api/market/{asset_id}")
def market_history(asset_id: str, range: str = Query("1M"), resolution: str | None = Query(None)):
    if resolution is None:
        return history(asset_id, range)  # existing consumers keep their original range behavior
    from .intraday import replay_history
    return replay_history(asset_id, range, resolution)

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

# Arcade endpoints never return candles beyond the current game timestamp.
class ArcadeStart(BaseModel):
    asset_id: str
    starting_point: float = Field(default=0.3, ge=0.15, le=0.75)
    period: Literal["7D", "30D", "60D", "6M", "1Y", "2Y", "5Y", "10Y", "MAX"] = "5Y"
    resolution: Literal["1m", "5m", "15m", "1h", "1d"] = "1d"
    start_date: str | None = Field(default=None, max_length=10)

class ArcadeOrder(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["market", "limit", "stop"] = "market"
    size: str = Field(min_length=1, max_length=40)
    size_type: Literal["percent", "units"] = "percent"
    price: str | None = None

class ArcadeAdvance(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    until_action: bool = False

class ArcadeStrategy(BaseModel):
    code: str = Field(max_length=1800)

@app.get("/api/arcade/runs")
def arcade_runs():
    return list_runs()

@app.get("/api/arcade/examples")
def arcade_examples():
    return {"examples": EXAMPLES}

@app.post("/api/arcade/validate")
def arcade_validate(strategy: ArcadeStrategy):
    return {"valid": True, "rules": [rule.to_dict() for rule in compile_rules(strategy.code)]}

@app.post("/api/arcade/new")
def arcade_new(request: ArcadeStart):
    return start_run(request.asset_id, request.starting_point, request.period, request.start_date, request.resolution)

@app.get("/api/arcade/{run_id}")
def arcade_get(run_id: str):
    return get_run(run_id)

@app.post("/api/arcade/{run_id}/orders")
def arcade_order(run_id: str, order: ArcadeOrder):
    return submit_arcade_order(run_id, order.side, order.kind, order.size, order.size_type, order.price)

@app.delete("/api/arcade/{run_id}/orders/{order_id}")
def arcade_cancel(run_id: str, order_id: str):
    return cancel_order(run_id, order_id)

@app.post("/api/arcade/{run_id}/advance")
def arcade_advance(run_id: str, request: ArcadeAdvance):
    return advance_run(run_id, request.count, request.until_action)

@app.put("/api/arcade/{run_id}/strategy")
def arcade_strategy(run_id: str, strategy: ArcadeStrategy):
    return set_strategy(run_id, strategy.code)

class ArcadeRisk(BaseModel):
    stop_loss_pct: float = Field(default=0, ge=0, le=75)
    take_profit_pct: float = Field(default=0, ge=0, le=75)

@app.put("/api/arcade/{run_id}/risk")
def arcade_risk(run_id: str, risk: ArcadeRisk):
    return set_risk(run_id, risk.stop_loss_pct, risk.take_profit_pct)

@app.get("/api/instruments/discover")
def discover_instruments(search: str = Query(..., min_length=2, max_length=60)):
    return search_yahoo(search)

class ImportTicker(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)

@app.post("/api/instruments/import")
def add_instrument(request: ImportTicker):
    return import_yahoo(request.symbol)

# Multi-asset Arcade lives in a separate SQLite table, preserving older saves.
from . import portfolio_arcade as portfolio

class PortfolioSeasonStart(BaseModel):
    asset_ids: list[str] = Field(min_length=2, max_length=5)
    period: Literal["7D", "30D", "60D", "6M", "1Y", "2Y", "5Y", "10Y", "MAX"] = "5Y"
    resolution: Literal["1m", "5m", "15m", "1h", "1d"] = "1d"
    starting_point: float = Field(default=0.3, ge=0.15, le=0.75)
    start_date: str | None = Field(default=None, max_length=10)

class PortfolioOrder(BaseModel):
    asset_id: str
    side: Literal["buy", "sell"]
    kind: Literal["market", "limit", "stop"] = "market"
    size: str = Field(min_length=1, max_length=40)
    size_type: Literal["percent", "units"] = "percent"
    price: str | None = None

@app.get("/api/portfolio-seasons")
def portfolio_runs():
    return portfolio.list_seasons()

@app.post("/api/portfolio-seasons")
def portfolio_new(request: PortfolioSeasonStart):
    return portfolio.create_season(request.asset_ids, request.period,
                                    request.starting_point, request.start_date, request.resolution)

@app.get("/api/portfolio-seasons/{run_id}")
def portfolio_get(run_id: str):
    return portfolio.get_season(run_id)

@app.post("/api/portfolio-seasons/{run_id}/advance")
def portfolio_step(run_id: str, request: ArcadeAdvance):
    return portfolio.advance(run_id, request.count, request.until_action)

@app.post("/api/portfolio-seasons/{run_id}/orders")
def portfolio_order(run_id: str, request: PortfolioOrder):
    return portfolio.order(run_id, request.asset_id, request.side,
                           request.kind, request.size, request.size_type, request.price)

@app.delete("/api/portfolio-seasons/{run_id}/orders/{order_id}")
def portfolio_cancel(run_id: str, order_id: str):
    return portfolio.cancel(run_id, order_id)

@app.put("/api/portfolio-seasons/{run_id}/strategy")
def portfolio_strategy(run_id: str, request: ArcadeStrategy):
    return portfolio.strategy(run_id, request.code)

@app.put("/api/portfolio-seasons/{run_id}/risk")
def portfolio_risk(run_id: str, request: ArcadeRisk):
    return portfolio.risk(run_id, request.stop_loss_pct, request.take_profit_pct)

@app.get("/api/portfolio-seasons/{run_id}/analytics")
def portfolio_analytics(run_id: str):
    return portfolio.get_analysis(run_id)

@app.get("/api/arcade/{run_id}/analytics")
def arcade_analytics(run_id: str):
    from .arcade import get_analysis
    return get_analysis(run_id)
