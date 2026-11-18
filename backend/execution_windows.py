"""Private observed intraday execution-capacity diagnostics for live recommendations.

This is NOT an order simulator with broker fills: a completed 5-minute OHLCV
bar can describe hypothetical capacity at its opening price but cannot prove
that a human saw the signal, submitted an order, or received a fill.
No actual fills, model settings, recommendations or account records are
ever copied into public artifacts. All observations are stored in local data/.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone, time as localtime
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from . import live_machine
from .assets import get_instrument
from .market import history

DB_PATH=Path(os.environ.get("TRADING_SIM_EXECUTION_WINDOWS_DB",
    Path(__file__).resolve().parents[1]/"data"/"execution_windows.sqlite3"))
NY=ZoneInfo("America/New_York")
LOCK=RLock()
DELAYS_MINUTES=(5,30,60)
STEP_SECONDS=300
WINDOW_HOURS=12.
MAX_PARTICIPATION=.01
SLIPPAGE_BPS=8.
MAX_SCAN_SIGNALS=20
MAX_SCAN_AGE_HOURS=96


def _private():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,"Owner-only execution evidence is disabled in the public demo.")


def _clock(now=None):
    result=now or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("Execution observer requires an aware timestamp.")
    return result.astimezone(timezone.utc)


def _connection():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=20,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA busy_timeout=20000")
    c.execute("""CREATE TABLE IF NOT EXISTS execution_observations (
        signal_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL, side TEXT NOT NULL, signal_at TEXT NOT NULL,
        observed_at TEXT NOT NULL, window_end TEXT NOT NULL, status TEXT NOT NULL,
        results TEXT NOT NULL, last_error TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS observation_time ON execution_observations(observed_at)")
    return c


def _as_time(value):
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("Timestamps must include timezone.")
    return d.astimezone(timezone.utc)


def _end(signal):
    created=_as_time(signal["created_at"])
    expires=_as_time(signal["expires_at"])
    return min(created+timedelta(hours=WINDOW_HOURS),expires)


def _clean_bars(response,now):
    if (not isinstance(response,dict)
        or response.get("is_demo") or response.get("offline_cache")
        or not isinstance(response.get("bars"),list)):
        raise ValueError("Intraday source unavailable, demo or cached.")
    bars=[];previous=None
    for row in response["bars"]:
        if not isinstance(row,dict):raise ValueError("Invalid candle.")
        try:
            t=int(row["time"])
            op=float(row["open"]);hi=float(row["high"])
            low=float(row["low"]);close=float(row["close"])
            volume=float(row["volume"])
        except (TypeError,ValueError,KeyError,OverflowError):
            raise ValueError("Malformed OHLCV candle.") from None
        if (previous is not None and t<=previous or
            not all(math.isfinite(x) for x in (op,hi,low,close,volume))
            or min(op,hi,low,close)<=0 or volume<0 or
            low>min(op,close) or hi<max(op,close) or hi<low):
            raise ValueError("Unsorted, nonfinite or inconsistent OHLCV candle.")
        previous=t
        start=datetime.fromtimestamp(t,timezone.utc)
        et=start.astimezone(NY)
        if et.weekday()>=5 or not(localtime(9,30)<=et.time()<localtime(16)):
            continue
        # Only finished regular-session 5-minute bars count. Never use
        # an in-progress bar, even when Yahoo has returned its provisional open.
        if start+timedelta(seconds=STEP_SECONDS)>now:
            continue
        bars.append({"time":start,"open":op,"volume":volume})
    return bars


def _scenario(signal, bars, now, delay, *, instrument):
    created=_as_time(signal["created_at"])
    window_end=_end(signal)
    start=created+timedelta(minutes=delay)
    # Do not use a candle that started exactly when an update generated a
    # signal: the snapshot's opening auction was not yet an observed fill.
    eligible=[bar for bar in bars
              if bar["time"]>=start and bar["time"]>=created and
                 bar["time"]+timedelta(seconds=STEP_SECONDS)<=window_end]
    result={"delay_minutes":delay,"window_hours":WINDOW_HOURS,
            "capacity_fraction":MAX_PARTICIPATION,
            "status":"awaiting_completed_bar" if now<window_end else "no_completed_bar_observed",
            "first_bar":None,"observed_at":None,"hours_since_signal":None,
            "estimated_price_usd":None,"price_change_pct":None,
            "requested_shares":None,"capacity_shares":None,
            "estimated_fillable_shares":None,"capacity_pct":None,
            "retrospective":None,"regular_session_only":True}
    if not eligible:
        return result
    first=eligible[0]
    if first["volume"]<=0:
        result["status"]="volume_unavailable"
        return result
    volume_share=math.floor(first["volume"]*MAX_PARTICIPATION)
    ref=float(signal["price_reference"])
    notional=signal.get("suggested_notional")
    if (notional is None or type(notional) not in (float,int)
        or not math.isfinite(float(notional)) or notional<=0):
        result["status"]="notional_unavailable"
        return result
    half_spread=float(instrument.spread_bps)/2
    adjustment=(half_spread+SLIPPAGE_BPS)/10000
    estimate=first["open"]*(1+adjustment if signal["side"]=="buy" else 1-adjustment)
    if not math.isfinite(estimate) or estimate<=0 or ref<=0:
        raise ValueError("Invalid modeled price.")
    required=math.ceil(float(notional)/estimate)
    executable=min(required,volume_share)
    observed=first["time"]+timedelta(seconds=STEP_SECONDS)
    result.update(
        status="capacity_observed" if executable>=required else "partial_capacity_observed",
        first_bar=first["time"].isoformat(),observed_at=observed.isoformat(),
        hours_since_signal=round((first["time"]-created).total_seconds()/3600,4),
        estimated_price_usd=round(estimate,6),
        price_change_pct=round((estimate/ref-1)*100,4),
        requested_shares=required,capacity_shares=volume_share,
        estimated_fillable_shares=executable,
        capacity_pct=round(executable/required*100,2),
        retrospective=(now-observed)>timedelta(minutes=10))
    return result


def evaluate(signal, response, *, now=None):
    """Assess one recommendation, not the signal author's strategy source."""
    _private()
    at=_clock(now)
    created=_as_time(signal["created_at"])
    end=_end(signal)
    if (created>at or end<=created or signal["side"] not in ("buy","sell")
        or float(signal["price_reference"])<=0):
        raise ValueError("Invalid recommendation time, side or reference.")
    instrument=get_instrument(signal["asset_id"])
    if instrument.kind not in ("Stocks","ETFs") or instrument.currency!="USD":
        raise ValueError("Only USD stocks and ETFs may use the five-minute observer.")
    bars=_clean_bars(response,at)
    results=[_scenario(signal,bars,at,delay,instrument=instrument)
             for delay in DELAYS_MINUTES]
    return {"signal_id":signal["id"],"symbol":signal["asset_id"],
            "side":signal["side"],"signal_at":created.isoformat(),
            "window_end":end.isoformat(),"observed_at":at.isoformat(),
            "status":"window_elapsed" if at>=end else "window_active",
            "scenarios":results,"source":"indicative five-minute provider OHLCV",
            "executed":False,
            "limitation":"Observed volume fraction and candle open, not executable order-book liquidity or broker fills."}


def _persist(result):
    with LOCK,closing(_connection()) as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("""INSERT INTO execution_observations(
          signal_id,symbol,side,signal_at,observed_at,window_end,status,results,last_error)
          VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(signal_id) DO UPDATE SET
          observed_at=excluded.observed_at,
          status=excluded.status,results=excluded.results,last_error=NULL""",
          (result["signal_id"],result["symbol"],result["side"],
           result["signal_at"],result["observed_at"],result["window_end"],
           result["status"],json.dumps(result,allow_nan=False,separators=(",",":")),None))
        c.commit()


def observations(limit=60):
    _private()
    with LOCK,closing(_connection()) as c:
        rows=c.execute("SELECT results FROM execution_observations "
                       "ORDER BY observed_at DESC LIMIT ?",(min(max(int(limit),1),100),))
        return [json.loads(r["results"]) for r in rows]


def _recent_signals(now,*,signal_rows=None):
    signals=live_machine.signals(limit=100) if signal_rows is None else signal_rows
    eligible=[]
    for s in signals:
        try:
            at=_as_time(s["created_at"])
        except (ValueError,KeyError,TypeError):
            continue
        hours=(now-at).total_seconds()/3600
        if 0<=hours<=MAX_SCAN_AGE_HOURS and s.get("side") in ("buy","sell"):
            eligible.append(s)
        if len(eligible)>=MAX_SCAN_SIGNALS:break
    return eligible


def process_all(*, now=None, loader=None, signal_rows=None):
    """Bounded worker check, intentionally independent of the trade ledger.

    Re-reading five-minute data later is retrospective *observation*. It does
    not make previously unseen candles into a real-time execution record.
    """
    _private()
    at=_clock(now)
    load=loader or history
    signals=_recent_signals(at,signal_rows=signal_rows)
    output=[]
    by_symbol={}
    for signal in signals:
        symbol=signal["asset_id"]
        try:
            if symbol not in by_symbol:by_symbol[symbol]=load(symbol,"1D")
            report=evaluate(signal,by_symbol[symbol],now=at)
            _persist(report)
            output.append(report)
        except (ValueError,TypeError,KeyError,HTTPException) as exc:
            # Keep previous valid evidence intact on feed/shape failure.
            # A failed refresh must not overwrite a verified earlier bar.
            output.append({"signal_id":signal.get("id"),"status":"data_unavailable",
                           "error_code":type(exc).__name__})
    return output
