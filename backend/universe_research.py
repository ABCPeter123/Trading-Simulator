"""Private, resumable universe-wide strategy tournament.

Screens every eligible known instrument with actual daily OHLCV. A run ranks
portfolio templates on training/validation only and presents the top ten.
Held-out and hypothetical future scenarios are computed after selection.
No live orders, no short-share execution, no synthetic prices in histories.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean, stdev
from threading import RLock
from uuid import uuid4
import json
import math
import os
import random
import sqlite3
import time

from fastapi import HTTPException

from . import assets, portfolio_research as pr
from .archive import load_archived_history
from .market import history

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("TRADING_SIM_UNIVERSE_DB", ROOT/"data/universe_research.sqlite3"))
LOCK = RLock()
CANDIDATE_MODELS = tuple(pr.MODELS)
# Predefined portfolio groups are starting configurations, not guaranteed winners.
BASKET_SEEDS = {
    "diversified": ("spy","qqq","ief","gld","eem","vnq","vti","xlv"),
    "defensive": ("shy","ief","tlt","tip","gld","vti","xlp","xlu"),
    "growth": ("qqq","vgt","xlk","spy","iwm","xly","vti","gld"),
    "sectors": ("xlf","xle","xlv","xli","xlp","xly","xlu","xlg"),
    "international": ("spy","efa","eem","ewj","ewc","vxus","gld","ief"),
    "income": ("schd","vym","dgro","vti","lqd","tip","vnq","shy"),
    "hedged": ("spy","tlt","gld","ief","shy","sqqq","xlp","vixy"),
    "leveraged_etf": ("spy","qqq","tqqq","upro","gld","ief","shy","xlp"),
    "canadian": ("xbal","vfv","vdy","vab","zsp","xiu","xgro","zeb"),
    "quality": ("qual","usmv","mtum","spy","vti","ief","gld","xlp"),
}
# The explicit seeds allow even a small but diverse archive to yield valid
# experiments. Dynamic baskets sample the entire screened inventory.
LEVERAGED_IDS = frozenset(("tqqq","sqqq","upro","spxu","vixy","cweb"))
SHORT_PROXY_IDS = frozenset(("sqqq","spxu"))
COST_ASSUMPTIONS = {
    "broker": "Wealthsimple indicative cash account model",
    "commission_usd": 0.0,
    "fx_conversion_bps": 150.0,
    "base_currency": "CAD",
    "slippage_bps": 8.0,
    "delay_sessions": 1,
    "delayed_stress_sessions": 2,
    "time_target_hours": 12,
}
MAX_QUEUE = 2
MAX_STORED = 50


def _connection():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=30, isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS universe_jobs(
       id TEXT PRIMARY KEY, status TEXT NOT NULL,
       created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
       progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL,
       scanned INTEGER NOT NULL DEFAULT 0, eligible INTEGER NOT NULL DEFAULT 0,
       error_code TEXT, params TEXT NOT NULL, result TEXT)""")
    return c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _public(row, detail=False):
    data=dict(row)
    out={k:data[k] for k in ("id","status","created_at","updated_at",
                             "progress","stage","scanned","eligible","error_code")}
    out["params"]=json.loads(data["params"])
    if detail and data["result"]:
        out["result"]=json.loads(data["result"])
    else:
        out["result"]=None
    return out


def enqueue(scope="all", delay_sessions=1, max_drawdown_pct=30, max_position_pct=35):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,detail="Owner research is unavailable in public demos.")
    if scope not in ("all","etfs","stocks") or delay_sessions not in (1,2):
        raise HTTPException(422, detail="Invalid research scope or fill latency.")
    if not 5<=max_drawdown_pct<=60 or not 10<=max_position_pct<=50:
        raise HTTPException(422,detail="Invalid research risk parameters.")
    with LOCK,closing(_connection()) as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT count(*) FROM universe_jobs WHERE status IN ('queued','running')").fetchone()[0]>=MAX_QUEUE:
            raise HTTPException(429, detail="A universe scan is already queued or running.")
        if c.execute("SELECT count(*) FROM universe_jobs").fetchone()[0]>=MAX_STORED:
            raise HTTPException(409,detail="Archive old universe research before adding more jobs.")
        identity=str(uuid4()); now=_now()
        args={"scope":scope,"delay_sessions":delay_sessions,
              "max_drawdown_pct":max_drawdown_pct,"max_position_pct":max_position_pct}
        c.execute("""INSERT INTO universe_jobs
          (id,status,created_at,updated_at,progress,stage,params)
          VALUES (?,'queued',?,?,0,'Awaiting local research worker',?)""",
          (identity,now,now,json.dumps(args)))
        c.commit()
        return _public(c.execute("SELECT * FROM universe_jobs WHERE id=?",(identity,)).fetchone())


def list_jobs(limit=20):
    with LOCK,closing(_connection()) as c:
        return [_public(x) for x in c.execute(
            "SELECT * FROM universe_jobs ORDER BY created_at DESC LIMIT ?",(min(50,max(1,limit)),))]


def get_job(identity):
    with LOCK,closing(_connection()) as c:
        row=c.execute("SELECT * FROM universe_jobs WHERE id=?",(identity,)).fetchone()
        if row is None:raise HTTPException(404,detail="Research scan not found.")
        return _public(row, detail=True)


def _progress(identity, pct, stage, scanned=None, eligible=None):
    with closing(_connection()) as c:
        params=[min(99,max(0,int(pct))),str(stage)[:110],_now()]
        sql="UPDATE universe_jobs SET progress=?,stage=?,updated_at=?"
        if scanned is not None:sql+=",scanned=?";params.append(scanned)
        if eligible is not None:sql+=",eligible=?";params.append(eligible)
        params.append(identity)
        c.execute(sql+" WHERE id=? AND status='running'",params)
        state=c.execute("SELECT status FROM universe_jobs WHERE id=?",(identity,)).fetchone()
        if state is None or state[0]!="running":raise InterruptedError("Research scan cancelled.")


def cancel(identity):
    with LOCK,closing(_connection()) as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE universe_jobs SET status='cancelled',stage='Cancelled',updated_at=? "
                  "WHERE id=? AND status IN ('queued','running')",(_now(),identity))
        c.commit()
    return get_job(identity)


def _read(asset_id, load=None):
    """Prefer real owner archives. For missing archives fetch one real 5Y window."""
    if load is not None:
        return load(asset_id)
    for window in ("5Y","MAX","10Y","20Y"):
        try:
            bars=load_archived_history(asset_id,window)
            if len(bars)>=500:
                return {"bars":bars[-1800:],"source":"Local recorded provider OHLCV","offline_cache":True}
        except (OSError,ValueError,KeyError):
            pass
    # Unofficial provider request is rate-limited by the scanner itself.
    return history(asset_id,"5Y")


def _quality(bars):
    if not isinstance(bars,list) or len(bars)<500:return False
    prev=-1
    for bar in bars:
        try:
            t=int(bar["time"])
            op,hi,lo,close=(float(bar[k]) for k in ("open","high","low","close"))
            if t<=prev or min(op,hi,lo,close)<=0 or not all(
                    math.isfinite(v) for v in (op,hi,lo,close)
            ) or lo>min(op,close) or hi<max(op,close):
                return False
            prev=t
        except (KeyError,ValueError,TypeError):
            return False
    return True


def _universe(scope):
    # Deterministic catalog order. Research-only references, not broker-approved
    # tradability, are still screened and separately marked as ineligible.
    names=assets.list_instruments(limit=2000)
    wanted={"stocks":{"Stocks"},"etfs":{"ETFs"}}.get(scope)
    return [x["id"] for x in names if wanted is None
            or assets.get_instrument(x["id"]).kind in wanted]


def _basket_candidates(histories, eligible):
    if not eligible:
        return []
    names=set(eligible)
    baskets=[]
    for label,seed in BASKET_SEEDS.items():
        selected=[name for name in seed if name in names]
        if len(selected)>=2:
            baskets.append((label,selected[:10]))
    # Group-screen every instrument. These baskets are formed from training
    # and validation only. Do not screen using held-out returns.
    by_group=defaultdict(list)
    latest=min(int(histories[s]["bars"][-1]["time"]) for s in eligible)
    # Fixed absolute training cutoff shared by every asset. Selection of
    # basket membership cannot use the validation or test calendar years.
    training_cutoff=latest-2*365*86400
    for sym in eligible:
        item=assets.get_instrument(sym)
        group=pr._group(sym,item.kind)
        bars=histories[sym]["bars"]
        sample=[bar for bar in bars if int(bar["time"])<=training_cutoff]
        if len(sample)<180:continue
        strength=sample[-1]["close"]/sample[-127]["close"]-1
        by_group[group].append((float(strength),sym))
    for g in by_group:by_group[g].sort(reverse=True)
    # Evaluate sector/instrument breadth without trying 10^338 combinations.
    leaders=[x[1] for v in by_group.values() for x in v[:12]]
    for i in range(0,min(len(leaders),96),8):
        basket=list(dict.fromkeys(leaders[i:i+8]))
        if len(basket)>=2:
            baskets.append((f"screened_{i//8+1}",basket))
    if len(baskets)<2 and len(eligible)>=2:
        baskets.append(("available_universe",eligible[:10]))
    return baskets


def _scenarios(curve,seed=9):
    """Hypothetical daily returns, NOT predictions. Deterministic reproducible."""
    vals=[float(p["value"]) for p in curve]
    changes=[b/a-1 for a,b in zip(vals,vals[1:]) if a>0]
    if len(changes)<10:return {"status":"insufficient_observations","paths":[]}
    rng=random.Random(seed)
    horizon=30; paths=[]
    for label,stress in (("ordinary",0.),("slower_execution",-0.00035),
                         ("broad_market_shock",-0.004),("rebound",0.002)):
        finals=[];worsts=[]
        for _ in range(120):
            value=100.;peak=value;worst=0.
            for day in range(horizon):
                draw=rng.choice(changes[-min(len(changes),180):])
                extra=stress
                if label=="broad_market_shock" and day==0:
                    extra-=.12
                value=max(0.01,value*(1+max(-.99,draw+extra)))
                peak=max(peak,value);worst=min(worst,value/peak-1)
            finals.append((value/100-1)*100);worsts.append(worst*100)
        finals.sort();worsts.sort()
        paths.append({"name":label,"horizon_sessions":horizon,
                      "p05_return_pct":round(finals[6],2),
                      "median_return_pct":round(finals[60],2),
                      "p95_return_pct":round(finals[113],2),
                      "median_max_drawdown_pct":round(worsts[60],2)})
    return {"status":"hypothetical_resampled_history","paths":paths,
            "method":"Historical daily strategy-return bootstrap with explicit adverse shocks; NOT a forecast or guaranteed probability."}


def run_study(params, *, loader=None, report=None, pause=time.sleep):
    """Return a transparent top-ten ranking without using held-out for selection."""
    report=report or (lambda *args:None)
    universe=_universe(params["scope"]);histories={};rejected={}
    for ix,sym in enumerate(universe):
        item=assets.get_instrument(sym)
        try:
            if item.kind not in ("Stocks","ETFs") or item.currency not in ("USD","CAD") or not item.ticker:
                rejected[sym]="unsupported_broker_product_or_currency"
                continue
            response=_read(sym,load=loader)
            if response.get("is_demo") or not _quality(response.get("bars")):
                raise ValueError("Insufficient or invalid real daily OHLCV")
            histories[sym]={"bars":response["bars"][-1800:],
                            "source":response.get("source","historical provider")}
        except (HTTPException,ValueError,OSError,KeyError,TypeError):
            rejected[sym]="missing_or_invalid_ohlcv"
        if ix%10==0 or ix+1==len(universe):
            report(5+int(51*(ix+1)/max(1,len(universe))),
                   f"Screening {ix+1}/{len(universe)} market instruments",
                   ix+1,len(histories))
        if loader is None and ix<len(universe)-1 and sym not in histories:
            pause(.4)
    baskets=_basket_candidates(histories,list(histories))
    ranked=[];discarded=[];evaluated=0
    # Five reusable portfolio templates × every viable basket. All candidates
    # use training/validation only; the final 20% is untouched by scoring.
    for ix,(label,symbols) in enumerate(baskets):
        try:
            source={x:histories[x] for x in symbols}
            if any(assets.get_instrument(s).currency=="CAD" for s in symbols):
                if "usdcad" not in histories:
                    fx=_read("usdcad",load=loader)
                    if not _quality(fx.get("bars")):raise ValueError("Missing real FX history")
                    histories["usdcad"]=fx
                source["usdcad"]=histories["usdcad"]
            days,market,metadata,_=pr._prepare(symbols,source)
            n=len(days);train_end=int(n*.6);test_start=int(n*.8)
            if train_end<=pr.WARMUP or test_start-train_end<50:
                raise ValueError("Insufficient separate validation history")
            for model in CANDIDATE_MODELS:
                evaluated+=1
                broker={**COST_ASSUMPTIONS,
                        "delay_sessions":params["delay_sessions"]}
                train=pr._segment(model,symbols,market,metadata,pr.WARMUP,
                                  train_end,params["max_position_pct"]/100,
                                  broker=broker)
                valid=pr._segment(model,symbols,market,metadata,train_end,
                                  test_start,params["max_position_pct"]/100,
                                  broker=broker)
                passes=(abs(valid["max_drawdown_pct"])<=params["max_drawdown_pct"]
                        and valid["trades"]>0
                        and valid["average_invested_pct"]>=5)
                # Decline underfit templates rather than always pretending
                # there must be ten good choices.
                score=round(valid["return_pct"]-1.7*abs(valid["max_drawdown_pct"])
                            -.025*valid["turnover_pct"]
                            -(4 if valid["trades"]<2 else 0),4)
                if passes:
                    ranked.append({"basket_type":label,"symbols":symbols,
                                   "model":model,"score":score,
                                   "train":pr._compact(train),
                                   "validation":pr._compact(valid),
                                   "_market":market,"_metadata":metadata,
                                   "_test_start":test_start,"_n":n})
            report(58+int(34*(ix+1)/max(1,len(baskets))),
                   f"Comparing {ix+1}/{len(baskets)} portfolio baskets",
                   len(universe),len(histories))
        except (HTTPException,ValueError,ArithmeticError,TypeError,KeyError) as exc:
            discarded.append({"basket":label,"reason":type(exc).__name__})
    ranked.sort(key=lambda x:(-x["score"],x["basket_type"],x["model"]))
    leaders=[]
    for i,item in enumerate(ranked[:10]):
        broker={**COST_ASSUMPTIONS,"delay_sessions":params["delay_sessions"]}
        slow={**broker,"delay_sessions":2,"slippage_bps":20}
        test=pr._segment(item["model"],item["symbols"],item["_market"],
                         item["_metadata"],item["_test_start"],item["_n"],
                         params["max_position_pct"]/100,broker=broker)
        stress=pr._segment(item["model"],item["symbols"],item["_market"],
                           item["_metadata"],item["_test_start"],item["_n"],
                           params["max_position_pct"]/100,broker=slow)
        leaders.append({
            "rank":i+1,"basket_type":item["basket_type"],"symbols":item["symbols"],
            "model":item["model"],"validation_score":item["score"],
            "training":item["train"],"validation":item["validation"],
            "held_out":pr._compact(test),
            "delayed_execution_stress":pr._compact(stress),
            "hypothetical_scenarios":_scenarios(test["equity_curve"],seed=42+i),
            "execution_model":"Next common-session open from completed prior session; "
                              "2-session +20bps adverse execution stress. "
                              "Calendar latency may exceed 12h.",
            "restricted_research":any(s in LEVERAGED_IDS for s in item["symbols"]),
            "short_proxy_research":any(s in SHORT_PROXY_IDS for s in item["symbols"]),
            "no_real_order":True,
        })
    report(98,"Saving ranked research and hypothetical scenarios",
           len(universe),len(histories))
    return {
        "universe_count":len(universe),"screened_count":len(universe),
        "eligible_count":sum(1 for sym in universe if sym in histories and sym not in rejected),
        "excluded_count":len(rejected),"exclusions":rejected,
        "basket_count":len(baskets),"candidates_evaluated":evaluated,
        "qualified_candidates":len(ranked),"rejected_baskets":discarded,
        "top10":leaders,
        "selection_method":"Validation-only ranking; held-out results and simulated future scenarios are never selection criteria.",
        "execution_assumptions":{**COST_ASSUMPTIONS,"configured_delay_sessions":params["delay_sessions"],
                                 "commission_note":"USD $0 listed-stock/ETF commission. FX 1.5% assumed on any cross-currency trade; this is conservative and account-dependent."},
        "test_used_for_selection":False,
        "limitations":[
            "The entire reference catalog is checked; only USD/CAD stocks and ETFs with sufficient actual daily history enter the present cash-account optimizer. Futures, currencies, crypto, options and unsupported contract types are explicitly excluded, not falsely treated as executable.",
            "Only symbols with sufficient actual valid historical daily data are evaluated. Exclusions are reported, not backfilled with synthetic observations.",
            "Broker eligibility varies by account and instrument. Shorting shares is not supported by Wealthsimple; inverse/leveraged ETFs are separate risky research products, never automatic shorts.",
            "No direct Wealthsimple broker-price API, order routing, options margin engine, cash settlement, borrowing, taxes or dividend-adjusted total returns.",
            "Signals from completed daily candles can take more than 12 calendar hours to reach the next regular-session open. A two-session stress test measures a longer delay.",
            "Hypothetical future paths resample historical strategy outcomes and add shocks. They are not predictions or calibrated probabilities.",
            "Ticker universe and available listings introduce survivorship bias. Historical OHLCV can be incomplete and requires point-in-time symbol membership and corporate-action data for stronger conclusions.",
        ],
        "automation":"Never deploys, shorts, leverages on margin, or submits brokerage orders.",
    }


def process_one():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        return None
    with LOCK,closing(_connection()) as c:
        c.execute("BEGIN IMMEDIATE")
        # Interrupted scans return to the queue. Entire scan is deterministic;
        # validated archives avoid re-downloading completed history.
        old=(datetime.now(timezone.utc)-timedelta(minutes=45)).isoformat()
        c.execute("UPDATE universe_jobs SET status='queued',stage='Recovered after interrupted worker' "
                  "WHERE status='running' AND updated_at<?",(old,))
        row=c.execute("SELECT * FROM universe_jobs WHERE status='queued' "
                      "ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            c.commit()
            return None
        identity=row["id"]
        c.execute("UPDATE universe_jobs SET status='running',progress=1,"
                  "stage='Loading actual historical archives',updated_at=? WHERE id=?",
                  (_now(),identity))
        c.commit()
    try:
        def report(pct,stage,scanned,eligible):
            _progress(identity,pct,stage,scanned,eligible)
        result=run_study(json.loads(row["params"]), report=report)
        with LOCK,closing(_connection()) as c:
            c.execute("UPDATE universe_jobs SET status='completed',progress=100,"
                      "stage='Research complete',result=?,updated_at=? "
                      "WHERE id=? AND status='running'",
                      (json.dumps(result,allow_nan=False),_now(),identity))
            c.commit()
    except InterruptedError:
        return get_job(identity)
    except Exception as exc:
        with LOCK,closing(_connection()) as c:
            c.execute("UPDATE universe_jobs SET status='failed',stage='Research failed',"
                      "error_code=?,updated_at=? WHERE id=? AND status='running'",
                      (type(exc).__name__,_now(),identity))
            c.commit()
    return get_job(identity)
