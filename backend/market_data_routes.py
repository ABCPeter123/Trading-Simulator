"""Owner local market-data coverage, incremental-ingest controls and quality API."""
from __future__ import annotations
import os

from fastapi import APIRouter,HTTPException,Query
from pydantic import BaseModel,Field

from . import market_ingestion,market_quality
from .assets import get_instrument

router=APIRouter(prefix="/api/market-data",tags=["Market data operations"])

def _private():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,detail="Private market data operations are unavailable in public demos.")

class Subscription(BaseModel):
    asset_id:str=Field(pattern=r"^[a-z0-9_.-]{1,32}$")
    resolution:str=Field(default="5m",pattern=r"^(1m|5m|15m|1h|1d)$")

@router.get("/subscriptions")
def subscriptions():
    _private()
    return market_ingestion.list_subscriptions()

@router.post("/subscriptions",status_code=201)
def subscribe(body:Subscription):
    _private()
    return market_ingestion.subscribe(body.asset_id,body.resolution)

@router.delete("/subscriptions/{asset_id}/{resolution}")
def unsubscribe(asset_id:str,resolution:str):
    _private()
    return market_ingestion.unsubscribe(asset_id,resolution)

@router.get("/coverage/{asset_id}")
def coverage(asset_id:str,window:str=Query("1Y"),resolution:str=Query("1d")):
    _private()
    get_instrument(asset_id)
    return market_quality.analyze(asset_id,window,resolution)

@router.get("/health")
def health():
    _private()
    entries=market_ingestion.list_subscriptions()
    return {"subscriptions":len(entries),"active":sum(bool(x["active"]) for x in entries),
            "errors":sum(bool(x["failure_code"]) for x in entries),
            "last_updates":[{"asset_id":x["asset_id"],"resolution":x["resolution"],
                             "last_bar":x["last_bar"],"last_success":x["last_success"],
                             "failure_code":x["failure_code"]} for x in entries]}


@router.get("/archived/{asset_id}")
def archived(asset_id:str,window:str=Query("1Y"),resolution:str=Query("1d")):
    """Read recorded OHLCV bars only. Never claim they are current quotes."""
    from datetime import datetime,timezone
    import polars as pl
    from .archive import archive_path
    _private()
    item=get_instrument(asset_id)
    if resolution not in market_quality.SECONDS:
        raise HTTPException(422,detail="Unknown chart interval.")
    key=window if resolution=="1d" else f"{window}_{resolution}"
    path=archive_path(asset_id,key)
    if not path.exists():
        raise HTTPException(404,detail="The selected history has not been archived yet.")
    try:
        rows=pl.read_parquet(path).sort("time").to_dicts()
    except Exception as exc:
        raise HTTPException(503,detail="Archived market history cannot be read.") from exc
    if not rows:
        raise HTTPException(404,detail="No recorded candles for this instrument.")
    return {"asset_id":asset_id,"range":key,"currency":item.currency,
            "bars":rows,"as_of":datetime.fromtimestamp(
                int(rows[-1]["time"]),timezone.utc).isoformat(),
            "source":"Local recorded provider OHLCV, potentially delayed",
            "is_demo":False,"delayed_or_indicative":True,
            "offline_cache":True,"execution_eligible":False}
