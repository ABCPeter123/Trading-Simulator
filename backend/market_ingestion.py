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
MAX_DUE_PER_CYCLE=10
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
    conn.execute("""CREATE TABLE IF NOT EXISTS reconciliation_jobs(
        asset_id TEXT NOT NULL, resolution TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('bootstrap','reconcile')),
        due_at TEXT NOT NULL, last_attempt TEXT, last_success TEXT,
        failures INTEGER NOT NULL DEFAULT 0, error_code TEXT,
        verified_bars INTEGER NOT NULL DEFAULT 0,
        verified_through INTEGER, status TEXT NOT NULL DEFAULT 'pending',
        PRIMARY KEY(asset_id,resolution,kind))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS collector_heartbeat(
        id INTEGER PRIMARY KEY CHECK(id=1),
        checked_at TEXT NOT NULL, state TEXT NOT NULL,
        attempted INTEGER NOT NULL DEFAULT 0)""")
    return conn



def record_heartbeat(state: str, attempted: int = 0,
                     now: datetime | None = None) -> None:
    """Record worker activity only. API queries never claim a worker is alive."""
    if state not in ("polling", "idle"):
        raise ValueError("Invalid collector state.")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    with LOCK, closing(_db()) as conn:
        conn.execute("""INSERT INTO collector_heartbeat(id,checked_at,state,attempted)
                        VALUES(1,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                        checked_at=excluded.checked_at,
                        state=excluded.state,
                        attempted=excluded.attempted""",
                     (stamp, state, int(attempted)))
        conn.commit()


def collector_health(now: datetime | None = None) -> dict:
    """Recent heartbeat is evidence of activity, never a delivery guarantee."""
    now = now or datetime.now(timezone.utc)
    with LOCK, closing(_db()) as conn:
        item = conn.execute(
            "SELECT checked_at,state,attempted FROM collector_heartbeat WHERE id=1"
        ).fetchone()
    if item is None:
        return {"state": "unverified", "last_heartbeat": None,
                "heartbeat_age_seconds": None, "last_attempted": 0}
    try:
        previous = datetime.fromisoformat(item["checked_at"])
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        elapsed = max(0, int((now - previous).total_seconds()))
    except ValueError:
        return {"state": "unverified", "last_heartbeat": None,
                "heartbeat_age_seconds": None, "last_attempted": 0}
    # A poll can take longer than the nominal 30-second interval while
    # waiting for providers. "stale" means no recent confirmed heartbeat.
    return {"state": item["state"] if elapsed <= 120 else "stale",
            "last_heartbeat": item["checked_at"], "heartbeat_age_seconds": elapsed,
            "last_attempted": int(item["attempted"])}


def list_subscriptions():
    with LOCK,closing(_db()) as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM subscriptions ORDER BY active DESC, COALESCE(last_attempt, created_at) ASC LIMIT ?",(MAX_SUBSCRIPTIONS*5,))]


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
        # Durable bootstrap is queued immediately, with recurring reconciliation
        # gated on a successful bootstrap. Re-subscribing never overwrites a
        # completed job or needlessly downloads all historical candles again.
        conn.execute("""INSERT OR IGNORE INTO reconciliation_jobs
            (asset_id,resolution,kind,due_at) VALUES(?,?, 'bootstrap',?)""",
            (asset_id,resolution,now))
        conn.execute("""INSERT OR IGNORE INTO reconciliation_jobs
            (asset_id,resolution,kind,due_at) VALUES(?,?, 'reconcile',?)""",
            (asset_id,resolution,now))
        conn.commit()
    return {"asset_id":asset_id,"resolution":resolution,"active":True,
            "stored_locally":True,"backfill_queued":True}



BOOTSTRAP_WINDOW = {"1m": "7D", "5m": "60D", "15m": "60D",
                    "1h": "2Y", "1d": "MAX"}
# Short overlapping windows verified hourly against provider-returned observations.
VERIFY_SPAN_DAYS = {"1m": 2, "5m": 7, "15m": 7, "1h": 7, "1d": 21}
RECONCILE_SECONDS = 3600
MAX_RECONCILE_JOBS_PER_CYCLE = 1


def list_reconciliation_jobs():
    with LOCK, closing(_db()) as conn:
        return [dict(row) for row in conn.execute("""
            SELECT j.* FROM reconciliation_jobs j
            JOIN subscriptions s ON s.asset_id=j.asset_id
              AND s.resolution=j.resolution
            WHERE s.active=1
            ORDER BY j.due_at,j.asset_id,j.resolution,j.kind
            LIMIT 250""")]


def _fetch_reconcile_bars(asset, resolution, kind, now):
    """Bypass normal HTTP history cache; never treat an offline fallback as new proof."""
    if kind == "bootstrap":
        window = BOOTSTRAP_WINDOW[resolution]
        if resolution == "1d":
            return (market.coinbase_candles(asset, window) if asset.kind == "Crypto"
                    else market.yahoo_candles(asset, window)), window
        days = intraday.SPAN_DAYS[window]
    else:
        window = BOOTSTRAP_WINDOW[resolution]
        days = VERIFY_SPAN_DAYS[resolution]
    end = now if resolution != "1d" else now + timedelta(days=1)
    start = end - timedelta(days=days)
    if asset.kind == "Crypto":
        if resolution == "1d":
            # The 3M Coinbase chart uses daily OHLCV; 1M/1D chart windows
            # use hourly/minute granularity and MUST NOT enter a daily archive.
            bars = [bar for bar in market.coinbase_candles(asset, "3M")
                    if bar["time"] >= start.timestamp()]
        else:
            bars = intraday.fetch_coinbase(asset, start, end, resolution)
    else:
        bars = intraday.fetch_yahoo(asset, start, end, resolution)
    return bars, window


def _merge_verified(asset_id, resolution, bars, window):
    """Check all provider-returned bars are recorded with correct OHLCV.

    This proves fidelity to *one provider response*, not all market events,
    missing sessions, or exchange accuracy. Never fabricate absent candles.
    """
    import polars as pl
    if not bars:
        raise ValueError("Provider returned no observations.")
    readings = {}
    for bar in bars:
        if not intraday._valid(bar):
            raise ValueError("Provider returned malformed OHLCV.")
        stamp = int(bar["time"])
        value = tuple(float(bar[field]) for field in ("open","high","low","close","volume"))
        if stamp in readings and readings[stamp] != value:
            raise ValueError("Conflicting provider candles at identical timestamp.")
        readings[stamp] = value
    key = window if resolution == "1d" else f"{window}_{resolution}"
    # Preserve original archive on malformed/conflicting inputs.
    from .archive import record_history
    record_history({"asset_id":asset_id,"range":key,"bars":bars})
    path = archive_path(asset_id,key)
    timestamps = list(readings)
    observed = (pl.scan_parquet(path).filter(
        pl.col("time").is_in(timestamps)).select(
        ["time","open","high","low","close","volume"]).collect().to_dicts())
    stored = {int(row["time"]):tuple(float(row[field]) for field in
             ("open","high","low","close","volume")) for row in observed}
    # Each provider observation must be present once and match exactly.
    if len(observed) != len(stored) or stored != readings:
        raise ValueError("Archive does not match observed provider candles.")
    # Keep previously created chart windows synchronized; a timestamp
    # may exist in distinct range views but never twice within one archive.
    if resolution == "1d":
        aliases = ("1Y","2Y","5Y","10Y","15Y","20Y","MAX")
    else:
        aliases = {
            "1m":("7D",),"5m":("7D","30D","60D"),
            "15m":("7D","30D","60D"),
            "1h":("7D","30D","60D","6M","1Y","2Y"),
        }[resolution]
    for span in aliases:
        alias = span if resolution == "1d" else f"{span}_{resolution}"
        if alias != key:
            alias_path = archive_path(asset_id,alias)
            if not alias_path.exists():
                continue
            # Never turn an existing short-window chart into MAX history by
            # copying 20 years of bootstrap candles into its Parquet file.
            existing_start = pl.scan_parquet(alias_path).select(
                pl.col("time").min()).collect().item()
            if existing_start is None:
                continue
            within_window = [bar for bar in bars if int(bar["time"]) >= existing_start]
            if within_window:
                record_history({"asset_id":asset_id,"range":alias,
                                "bars":within_window})
    return {"verified_bars":len(readings),"verified_through":max(readings)}


def execute_reconciliation(asset_id, resolution, kind, now=None):
    now = now or datetime.now(timezone.utc)
    asset = get_instrument(asset_id)
    if not asset.ticker:
        raise ValueError("Subscription has no provider ticker.")
    bars, window = _fetch_reconcile_bars(asset, resolution, kind, now)
    return _merge_verified(asset_id, resolution, bars, window)


def run_reconciliation_due(now=None, execute=execute_reconciliation):
    """Process a bounded number of durable jobs. Retry indefinitely but slowly.

    A failed job remains queued with exponential, capped backoff. It is never
    counted as verified. Each run gives incremental live polling a chance.
    """
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1":
        return []
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    with LOCK, closing(_db()) as conn:
        # Migrate existing watchlists from before reconciliation queues existed.
        for kind in ("bootstrap", "reconcile"):
            conn.execute("""INSERT OR IGNORE INTO reconciliation_jobs
                (asset_id,resolution,kind,due_at)
                SELECT asset_id,resolution,?,? FROM subscriptions WHERE active=1""",
                (kind,stamp))
        conn.commit()
        due = [dict(row) for row in conn.execute("""
            SELECT j.* FROM reconciliation_jobs j JOIN subscriptions s
              ON j.asset_id=s.asset_id AND j.resolution=s.resolution
            WHERE s.active=1 AND j.due_at<=?
              AND (j.kind='reconcile' OR j.last_success IS NULL)
              AND (j.kind='bootstrap' OR EXISTS (
                SELECT 1 FROM reconciliation_jobs b
                WHERE b.asset_id=j.asset_id AND b.resolution=j.resolution
                  AND b.kind='bootstrap' AND b.last_success IS NOT NULL))
            ORDER BY CASE WHEN j.kind='bootstrap' THEN 0 ELSE 1 END,
              j.due_at,j.asset_id LIMIT ?""",
            (stamp, MAX_RECONCILE_JOBS_PER_CYCLE)).fetchall()]
    completed = []
    for job in due:
        try:
            result = execute(job["asset_id"],job["resolution"],job["kind"],now)
            due_at = (now + timedelta(seconds=RECONCILE_SECONDS)).isoformat()
            with LOCK, closing(_db()) as conn:
                conn.execute("""UPDATE reconciliation_jobs SET
                    last_attempt=?,last_success=?,due_at=?,failures=0,
                    error_code=NULL,verified_bars=?,verified_through=?,
                    status='provider_checked'
                    WHERE asset_id=? AND resolution=? AND kind=?""",
                    (stamp,stamp,due_at,result["verified_bars"],
                     result["verified_through"],job["asset_id"],
                     job["resolution"],job["kind"]))
                conn.commit()
            completed.append({"asset_id":job["asset_id"],"resolution":job["resolution"],
                              "kind":job["kind"],"status":"provider_checked"})
        except Exception as exc:
            failures = int(job["failures"])+1
            # 1m, 2m, 4m ... 60m, then every 60m forever.
            backoff = min(RECONCILE_SECONDS, 60*2**min(failures-1, 6))
            due_at = (now+timedelta(seconds=backoff)).isoformat()
            with LOCK, closing(_db()) as conn:
                conn.execute("""UPDATE reconciliation_jobs SET
                    last_attempt=?,due_at=?,failures=?,error_code=?,
                    status='retry_pending'
                    WHERE asset_id=? AND resolution=? AND kind=?""",
                    (stamp,due_at,failures,type(exc).__name__,job["asset_id"],
                     job["resolution"],job["kind"]))
                conn.commit()
            completed.append({"asset_id":job["asset_id"],"resolution":job["resolution"],
                              "kind":job["kind"],"status":"retry_pending",
                              "error":type(exc).__name__})
    return completed


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
        # A wider universe must not saturate Yahoo/Coinbase in one worker tick.
        # The oldest last_attempt is first, so later watches are not starved.
        if len(completed) >= MAX_DUE_PER_CYCLE:
            break
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
