"""Incremental, opt-in local market bar ingestion for a bounded watchlist.

The worker requests only the interval since the latest locally archived bar,
with a two-bar overlap for provider corrections. This is a historical
observation collector, not a licensed real-time tape or order book.
"""
from __future__ import annotations
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from fastapi import HTTPException

from .assets import get_instrument
from .archive import archive_path, record_history
from . import market, intraday

DB_PATH = Path(os.environ.get("TRADING_SIM_INGEST_DB",
                             Path(__file__).resolve().parents[1]/"data"/"market_ingestion.sqlite3"))
LOCK=RLock()
MAX_SUBSCRIPTIONS=100
INTERVAL_SECONDS={"1m":60,"5m":300,"15m":900,"1h":3600,"1d":86400}
MIN_POLL={"1m":60,"5m":120,"15m":300,"1h":600,"1d":3600}
SEED_WINDOW={"1m":"7D","5m":"30D","15m":"30D","1h":"6M","1d":"1Y"}


def _db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB_PATH,timeout=12)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA busy_timeout=12000")
    conn.execute("""CREATE TABLE IF NOT EXISTS subscriptions(
        asset_id TEXT NOT NULL,resolution TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,last_attempt TEXT,last_success TEXT,
        last_bar INTEGER,records INTEGER NOT NULL DEFAULT 0,
        failure_code TEXT,PRIMARY KEY(asset_id,resolution))""")
    return conn


def list_subscriptions():
    with LOCK,closing(_db()) as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM subscriptions ORDER BY updated_at DESC LIMIT ?",(MAX_SUBSCRIPTIONS,))]


def subscribe(asset_id:str,resolution:str="5m"):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,detail="Private market ingestion is disabled for public demos.")
    item=get_instrument(asset_id)
    if resolution not in INTERVAL_SECONDS:
        raise HTTPException(422,detail="Ingestion requires 1m, 5m, 15m, 1h or 1d.")
    if not item.ticker or item.kind=="Options":
        raise HTTPException(422,detail="No supported market feed for this instrument.")
    if item.kind=="Funds" and resolution!="1d":
        raise HTTPException(422,detail="Mutual fund NAV history supports daily collection only.")
    now=datetime.now(timezone.utc).isoformat()
    with LOCK,closing(_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current=conn.execute("SELECT COUNT(*) FROM subscriptions WHERE active=1").fetchone()[0]
        existing=conn.execute("SELECT active FROM subscriptions WHERE asset_id=? AND resolution=?",
                              (asset_id,resolution)).fetchone()
        if current>=MAX_SUBSCRIPTIONS and (not existing or not existing["active"]):
            conn.rollback()
            raise HTTPException(409,detail="Maximum 100 active ingestion subscriptions. Disable an existing subscription.")
        conn.execute("""INSERT INTO subscriptions(asset_id,resolution,created_at,updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(asset_id,resolution) DO UPDATE SET active=1,updated_at=excluded.updated_at""",
                     (asset_id,resolution,now,now))
        conn.commit()
    return {"asset_id":asset_id,"resolution":resolution,"active":True,"stored_locally":True}


def unsubscribe(asset_id:str,resolution:str):
    with LOCK,closing(_db()) as conn:
        conn.execute("UPDATE subscriptions SET active=0,updated_at=? WHERE asset_id=? AND resolution=?",
                     (datetime.now(timezone.utc).isoformat(),asset_id,resolution))
        conn.commit()
    return {"asset_id":asset_id,"resolution":resolution,"active":False}


def _recent(asset_id,resolution):
    """Most recent locally recorded bar. Archive data never becomes a live quote."""
    import polars as pl
    key=SEED_WINDOW[resolution] if resolution=="1d" else f"{SEED_WINDOW[resolution]}_{resolution}"
    p=archive_path(asset_id,key)
    if not p.exists():return None
    data=pl.read_parquet(p,columns=["time"])
    return int(data["time"].max()) if not data.is_empty() else None


def ingest_once(asset_id:str,resolution:str,now:datetime|None=None):
    """Sync one subscription; no fabricated bars, no credentials or personal data."""
    now=now or datetime.now(timezone.utc)
    asset=get_instrument(asset_id)
    previous=_recent(asset_id,resolution)
    window=SEED_WINDOW[resolution]
    if previous is None:
        # A first seed uses the existing constrained real-provider adapter.
        response=(market.history(asset_id,window) if resolution=="1d"
                  else intraday.replay_history(asset_id,window,resolution))
        if response.get("offline_cache") or response.get("is_demo"):
            raise ValueError("Cannot seed incremental ingestion from stale/synthetic data.")
        bars=response["bars"]
    else:
        overlap=INTERVAL_SECONDS[resolution]*3
        start=datetime.fromtimestamp(previous-overlap,timezone.utc)
        end=now+timedelta(days=1) if resolution=="1d" else now
        if start>=end: return {"asset_id":asset_id,"resolution":resolution,"added":0,"latest":previous}
        if asset.kind=="Crypto":
            if resolution=="1d":
                # Request actual 86,400-second daily candles. Never use the
                # normal "1D" DISPLAY window, which intentionally means
                # five-minute candles and would corrupt the daily archive.
                start=max(start,now-timedelta(days=240))
                response=market._client.get(
                    "https://api.exchange.coinbase.com/products/"+asset.ticker+"/candles",
                    params={"granularity":86400,"start":start.isoformat(),"end":end.isoformat()})
                response.raise_for_status()
                rows=response.json()
                if not isinstance(rows,list):
                    raise ValueError("Invalid Coinbase daily OHLCV response.")
                bars=[]
                for row in rows:
                    if not isinstance(row,list) or len(row)<6:continue
                    stamp,low,high,opening,closing,vol=row[:6]
                    stamp=int(stamp)
                    # Last daily candle may still be forming.
                    if stamp+86400>now.timestamp():continue
                    bars.append({"time":stamp,"open":float(opening),
                                 "high":float(high),"low":float(low),
                                 "close":float(closing),"volume":float(vol)})
                bars.sort(key=lambda bar:bar["time"])
            else:
                bars=intraday.fetch_coinbase(asset,start,end,resolution)
        else:
            bars=intraday.fetch_yahoo(asset,start,end,resolution)
        response={"asset_id":asset_id,"range":window if resolution=="1d" else f"{window}_{resolution}",
                  "bars":bars,"is_demo":False}
        if bars:record_history(response)
    # Refresh every previously downloaded view of this instrument at this
    # resolution. Each file retains its original history and receives only
    # the latest provider observations. Do not create missing long archives.
    if bars:
        windows={
            "1d":("2Y","5Y","10Y","15Y","20Y","MAX"),
            "1h":("7D","30D","60D","6M","1Y","2Y"),
            "15m":("7D","30D","60D"),
            "5m":("7D","30D","60D"),
            "1m":("7D",),
        }[resolution]
        for window_name in windows:
            key=window_name if resolution=="1d" else f"{window_name}_{resolution}"
            if archive_path(asset_id,key).exists():
                record_history({"asset_id":asset_id,"range":key,
                                "bars":bars,"is_demo":False})
    latest=max((int(b["time"]) for b in bars),default=previous)
    # The number of records returned is not the number of new bars; overlapping
    # observations may update prior data without increasing coverage.
    added=sum(int(b["time"])>(previous or 0) for b in bars)
    return {"asset_id":asset_id,"resolution":resolution,"added":added,
            "latest":latest,"provider":"Coinbase Exchange" if asset.kind=="Crypto" else "Yahoo Finance (unofficial)"}


def run_due(now:datetime|None=None):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":return []
    now=now or datetime.now(timezone.utc)
    completed=[]
    for item in list_subscriptions():
        if not item["active"]:continue
        resolution=item["resolution"]
        last=item["last_attempt"]
        if last:
            age=(now-datetime.fromisoformat(last)).total_seconds()
            cooldown=MIN_POLL[resolution]*(3 if item["failure_code"] else 1)
            if age<cooldown:continue
        # Do not download session-bound symbols while the primary market is
        # closed unless the source has never been seeded. Missing historical
        # candles can still be seeded on demand via the ordinary chart API.
        asset=get_instrument(item["asset_id"])
        if asset.kind not in ("Crypto",):
            # Daily mutual-fund NAVs and other post-close history are only
            # collectible after the session. They never become live quotes.
            from zoneinfo import ZoneInfo
            local=now.astimezone(ZoneInfo("America/New_York"))
            if local.weekday()>=5:
                continue
            if asset.kind=="Funds":
                if not (resolution=="1d" and local.hour>=17):
                    continue
            elif asset.kind=="Indices":
                if resolution=="1d":
                    if local.hour<17:continue
                elif not (9<=local.hour<16):
                    continue
            elif resolution=="1d":
                if local.hour<17:continue
            elif not market.market_open(asset,now):
                continue
        stamp=now.isoformat()
        with LOCK,closing(_db()) as conn:
            conn.execute("UPDATE subscriptions SET last_attempt=? WHERE asset_id=? AND resolution=?",
                         (stamp,item["asset_id"],resolution))
            conn.commit()
        try:
            result=ingest_once(item["asset_id"],resolution,now)
            with LOCK,closing(_db()) as conn:
                conn.execute("""UPDATE subscriptions SET last_success=?,last_bar=?,
                    records=records+?,failure_code=NULL WHERE asset_id=? AND resolution=?""",
                    (stamp,result["latest"],result["added"],item["asset_id"],resolution))
                conn.commit()
            completed.append(result)
        except Exception as exc:
            # Only the type of the failure is persisted. No URLs or financial
            # data should ever be logged to the public repository or CI.
            with LOCK,closing(_db()) as conn:
                conn.execute("UPDATE subscriptions SET failure_code=? WHERE asset_id=? AND resolution=?",
                             (type(exc).__name__,item["asset_id"],resolution))
                conn.commit()
            completed.append({"asset_id":item["asset_id"],"resolution":resolution,
                              "error":type(exc).__name__})
    return completed
