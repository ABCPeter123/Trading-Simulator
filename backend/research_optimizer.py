"""Private strategy discovery using chronological train/validation/held-out test.

Candidate selection occurs on training/validation only. Test data is examined
exactly once after selection. Neither code nor chosen parameters are committed.
All strategies, scores, and curves are saved to Git-ignored local SQLite.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException

from .assets import get_instrument
from .market import history
from .strategy_library import store as store_private_strategy

DB_PATH=Path(os.environ.get("TRADING_SIM_RESEARCH_DB",Path(__file__).resolve().parents[1]/"data/research_optimization.sqlite3"))
LOCK=RLock()
FAST=(5,10,15,20)
SLOW=(30,50,75,100)

def _db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB_PATH,timeout=15)
    conn.row_factory=sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS optimization_runs (
       id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, created_at TEXT NOT NULL,
       data_source TEXT NOT NULL, bars_count INTEGER NOT NULL,
       payload TEXT NOT NULL)""")
    return conn

def _smas(bars,period):
    values=[None]*len(bars)
    total=0.
    for i,bar in enumerate(bars):
        total+=float(bar["close"])
        if i>=period:total-=float(bars[i-period]["close"])
        if i>=period-1:values[i]=total/period
    return values

def _stats(curve,trades,capital):
    if not curve:return {"return_pct":0.,"max_drawdown_pct":0.,"annualized_volatility_pct":None,
                         "sharpe":None,"sortino":None,"trades":0,"equity_curve":[]}
    vals=[x["value"] for x in curve]
    returns=[b/a-1 for a,b in zip(vals,vals[1:]) if a>0]
    vol=stdev(returns) if len(returns)>=2 else 0.
    annual_vol=vol*math.sqrt(252)*100 if returns else None
    sharpe=mean(returns)/vol*math.sqrt(252) if vol>1e-12 else None
    negatives=[x for x in returns if x<0]
    downside=math.sqrt(sum(x*x for x in negatives)/len(returns)) if returns else 0.
    sortino=mean(returns)/downside*math.sqrt(252) if downside>1e-12 else None
    peak=capital;dd=0.
    for x in vals:
        peak=max(peak,x)
        if peak:dd=min(dd,(x/peak-1)*100)
    return {"return_pct":(vals[-1]/capital-1)*100,
            "max_drawdown_pct":dd,"annualized_volatility_pct":annual_vol,
            "sharpe":sharpe,"sortino":sortino,"trades":len(trades),
            "equity_curve":curve,"executions":trades}

def _segment(bars,fast,slow,start,end,allocation,spread_bps):
    """At index i open, the rule reads only through index i-1 close."""
    # Do not expose the target period to the selection algorithm.
    cap=100000.
    cash=cap;shares=0;trades=[];curve=[]
    fast_values=_smas(bars[:end],fast)
    slow_values=_smas(bars[:end],slow)
    for i in range(start,end):
        if i>=2 and None not in (fast_values[i-2],fast_values[i-1],
                                  slow_values[i-2],slow_values[i-1]):
            a0,b0=fast_values[i-2],slow_values[i-2]
            a1,b1=fast_values[i-1],slow_values[i-1]
            side="buy" if a0<=b0 and a1>b1 else "sell" if a0>=b0 and a1<b1 else None
            if side=="buy" and shares==0:
                fill=float(bars[i]["open"])*(1+(spread_bps/2+2)/10000)
                budget=min(cap*allocation/100,cash)
                qty=max(0,int(budget/(fill*1.0002)))
                fee=max(1.,qty*.005) if qty else 0.
                if qty and qty*fill+fee<=cash:
                    cash-=qty*fill+fee;shares+=qty
                    trades.append({"time":bars[i]["time"],"side":"buy","quantity":qty,
                                   "price":fill,"fee":fee,"source":"next_open"})
            elif side=="sell" and shares>0:
                fill=float(bars[i]["open"])*(1-(spread_bps/2+2)/10000)
                fee=max(1.,shares*.005)
                cash+=shares*fill-fee
                trades.append({"time":bars[i]["time"],"side":"sell",
                               "quantity":shares,"price":fill,"fee":fee,"source":"next_open"})
                shares=0
        curve.append({"time":bars[i]["time"],"value":cash+shares*float(bars[i]["close"])})
    return _stats(curve,trades,cap)

def _public_run(row):
    result=json.loads(row["payload"])
    return {"id":row["id"],"asset_id":row["asset_id"],"created_at":row["created_at"],
            "data_source":row["data_source"],"bars_count":row["bars_count"],**result}

def optimize(asset_id:str,max_drawdown_pct:float=15.,allocation_pct:float=20.,data=None):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,detail="Private strategy optimization is disabled in the shared public demo.")
    if not math.isfinite(max_drawdown_pct) or not 1<=max_drawdown_pct<=50:
        raise HTTPException(422,detail="Drawdown limit must be 1-50%.")
    if not math.isfinite(allocation_pct) or not 1<=allocation_pct<=25:
        raise HTTPException(422,detail="Allocation limit must be 1-25%.")
    instrument=get_instrument(asset_id)
    if instrument.kind not in ("Stocks","ETFs") or instrument.currency!="USD":
        raise HTTPException(422,detail="This optimizer supports USD stocks and ETFs.")
    source=data if data is not None else history(asset_id,"5Y")
    bars=source["bars"]
    if len(bars)<350 or any(
        any(not math.isfinite(float(b[k])) or float(b[k])<=0 for k in ("open","high","low","close"))
        for b in bars
    ):
        raise HTTPException(422,detail="At least 350 valid daily candles are required.")
    if any(int(b["time"])>=int(bars[i+1]["time"]) for i,b in enumerate(bars[:-1])):
        raise HTTPException(422,detail="Historical candles must be strictly increasing.")
    size=len(bars);train_end=int(size*.6);valid_end=int(size*.8)
    ranking=[]
    for fast in FAST:
        for slow in SLOW:
            train=_segment(bars,fast,slow,100,train_end,allocation_pct,instrument.spread_bps)
            val=_segment(bars,fast,slow,train_end,valid_end,allocation_pct,instrument.spread_bps)
            adequate=train["trades"]>=1 and val["trades"]>=1
            valid_risk=abs(val["max_drawdown_pct"])<=max_drawdown_pct
            # Explicitly rank on validation-only return and downside penalty,
            # with trade activity and drawdown guardrails; never on test results.
            score=(val["return_pct"]-1.5*abs(val["max_drawdown_pct"])
                   -(3.0 if val["trades"]<3 else 0.))
            ranking.append({"fast":fast,"slow":slow,"train":{
                k:v for k,v in train.items() if k not in ("equity_curve","executions")
            },"validation":{
                k:v for k,v in val.items() if k not in ("equity_curve","executions")
            },"score":score,"qualified":bool(adequate and valid_risk)})
    eligible=[x for x in ranking if x["qualified"]]
    eligible.sort(key=lambda x:x["score"],reverse=True)
    ranked=sorted(ranking,key=lambda x:x["score"],reverse=True)
    selected=eligible[0] if eligible else None
    evaluation=None
    if selected:
        fast,slow=selected["fast"],selected["slow"]
        train=_segment(bars,fast,slow,100,train_end,allocation_pct,instrument.spread_bps)
        validation=_segment(bars,fast,slow,train_end,valid_end,allocation_pct,instrument.spread_bps)
        heldout=_segment(bars,fast,slow,valid_end,size,allocation_pct,instrument.spread_bps)
        # Symbol, sizing, and crossover rule are private research output.
        strategy=(f"WHEN SMA({fast}) CROSSES ABOVE SMA({slow}) BUY {allocation_pct:g}%\n"
                  f"WHEN SMA({fast}) CROSSES BELOW SMA({slow}) SELL 100%")
        evaluation={"fast":fast,"slow":slow,"strategy_code":strategy,
          "train":train,"validation":validation,"held_out_test":heldout,
          "warning":"Selection used training/validation only. The held-out test is a single historical sample, not a profitability guarantee."}
    result={
        "selection_method":"Validation net return minus 1.5 times absolute drawdown, plus a low-turnover penalty",
        "test_used_for_selection":False,
        "assumptions":"Daily completed bars; signal at prior close, next bar open fill; estimated spread/slippage and share fees; long-only, no leverage.",
        "train_bars":train_end,"validation_bars":valid_end-train_end,
        "test_bars":size-valid_end,"max_drawdown_limit_pct":max_drawdown_pct,
        "allocation_pct":allocation_pct,"candidate_count":len(ranking),
        "eligible_count":len(eligible),"candidates":ranked,
        "selected":evaluation,
        "qualification_note":"No candidate meets both trade-activity and drawdown constraints." if not selected else
                             "A historical candidate passed the validation screen; it is NOT automatically deployed.",
    }
    run_id=str(uuid4());stamp=datetime.now(timezone.utc).isoformat()
    with LOCK:
        conn=_db()
        try:
            with conn:
                conn.execute("INSERT INTO optimization_runs VALUES(?,?,?,?,?,?)",
                             (run_id,asset_id,stamp,source.get("source","local research"),
                              size,json.dumps(result,allow_nan=False)))
        finally:conn.close()
    return {"id":run_id,"asset_id":asset_id,"created_at":stamp,
            "data_source":source.get("source","local research"),"bars_count":size,**result}

def list_runs(limit:int=20):
    with LOCK:
        conn=_db()
        try:
            rows=conn.execute("SELECT * FROM optimization_runs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
            # Avoid transferring huge curves unless the owner requests the run.
            result=[]
            for row in rows:
                p=json.loads(row["payload"])
                selected=p["selected"]
                result.append({"id":row["id"],"asset_id":row["asset_id"],"created_at":row["created_at"],
                               "candidate_count":p["candidate_count"],
                               "eligible_count":p["eligible_count"],
                               "selected":{k:selected[k] for k in ("fast","slow")} if selected else None})
            return result
        finally:conn.close()

def load_run(run_id:str):
    with LOCK:
        conn=_db()
        try:
            row=conn.execute("SELECT * FROM optimization_runs WHERE id=?",(run_id,)).fetchone()
            if row is None:raise HTTPException(404,detail="Research run not found.")
            return _public_run(row)
        finally:conn.close()

def save_selected(run_id:str,name:str):
    record=load_run(run_id)
    if not record["selected"]:
        raise HTTPException(409,detail="No candidate qualified for publication to the private library.")
    return store_private_strategy("single",name,
      record["selected"]["strategy_code"],[record["asset_id"]],
      source_run_id=run_id)
