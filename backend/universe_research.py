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

from . import assets, portfolio_research as pr, advanced_portfolio_research as adv, performance_objectives as objectives
from . import blended_portfolio_research as blends
from . import basket_optimizer, practical_selection
from .archive import load_archived_history
from .market import history

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("TRADING_SIM_UNIVERSE_DB", ROOT/"data/universe_research.sqlite3"))
LOCK = RLock()
CANDIDATE_MODELS = tuple(pr.MODELS) + tuple(adv.MODELS) + ("blended_portfolio",)
# General-purpose deterministic candidate templates, not owner-selected strategies.
BLEND_TEMPLATES = (
    (("equal_weight",50),("trend_filter",50)),
    (("relative_momentum",50),("inverse_volatility",50)),
    (("relative_momentum",40),("trend_filter",35),("defensive_rotation",25)),
    (("inverse_volatility",60),("equity_hedge",40)),
)

def _model_configs(include_blends=True):
    for model in CANDIDATE_MODELS:
        if model!="blended_portfolio":
            yield model,None
        elif include_blends:
            for template in BLEND_TEMPLATES:
                yield model,[{"model":name,"weight_pct":weight} for name,weight in template]


def _balanced_breakdown(valid,regimes,stability=None):
    worst=regimes["worst_regime_return_pct"]
    missed=(max(0,stability["window_count"]-stability["positive_windows"])
            if stability is not None and stability["sufficient_history"] else 0)
    components={
        "return_points":round(valid["return_pct"],6),
        "drawdown_points":round(-1.7*abs(valid["max_drawdown_pct"]),6),
        "turnover_points":round(-.025*valid["turnover_pct"],6),
        "volatility_points":round(-.08*(valid.get("annualized_volatility_pct") or 0.),6),
        "worst_regime_points":round(-.12*abs(min(0,worst)),6),
        "few_trades_points":-4. if valid["trades"]<2 else 0.,
        "losing_validation_windows_points":-8.*missed,
    }
    return {"eligible":True,"components":components,
            "total":round(sum(components.values()),4),
            "definition":"Validation-only heuristic points, not a forecast."}


def _same_basket_validation_penalty(valid,quality,control,control_quality):
    """No final test data; soft penalty for failing an identical basket control.

    Keep a zero debit for a genuine win, and a separately inspectable
    diagnostic for an underperformer. Do not treat equal weight as a strategy
    winner by itself or force the winner to beat a particular risk preference.
    """
    if control is None or control_quality is None:
        return 0.,None
    gap=float(valid["return_pct"])-float(control["return_pct"])
    reference=control_quality.get("excess_sharpe")
    selected=quality.get("excess_sharpe")
    sharpe_gap=(selected-reference if selected is not None and reference is not None
                else None)
    loss=min(60.,max(0.,-gap))
    if sharpe_gap is not None:
        loss+=min(20.,12.*max(0.,-sharpe_gap))
    penalty=round(loss,6)
    return penalty,{
        "same_basket_return_pct":round(control["return_pct"],4),
        "excess_return_points":round(gap,4),
        "same_basket_excess_sharpe":reference,
        "excess_sharpe_delta":round(sharpe_gap,4) if sharpe_gap is not None else None,
        "beats_same_basket_return":gap>0,
        "beats_same_basket_risk_adjusted":sharpe_gap is not None and sharpe_gap>0,
        "note":"Validation-only; no audit data used in model selection.",
    }


def _basket_correlation_penalty(symbols,market,train_end):
    """Training-only diversification diagnostic, no held-out return reads."""
    correlations=pr._correlations(symbols,market,train_end)
    pairs=[correlations[left][right]
           for i,left in enumerate(symbols) for right in symbols[i+1:]
           if correlations[left][right] is not None]
    if not pairs:
        return 0.,None
    avg_positive=sum(max(0.,value) for value in pairs)/len(pairs)
    # A small soft debit discourages collections of near-identical indexes,
    # without blocking an all-equity-only or defensively hedged strategy.
    return round(16*max(0.,avg_positive-.50),6),round(avg_positive,4)


def _execution_cost_audit(result,market,metadata,slippage):
    """Separate cash ledger charges from adverse modeled fill-price adjustments.

    The two categories must not be summed as if they were identical broker fees.
    Actual intraday price impact, borrow availability and fills are unknown.
    """
    opens={sym:{bar["time"]:float(bar["open"]) for bar in market[sym]}
           for sym in metadata}
    spread=slip=0.
    for execution in result.get("executions",[]):
        symbol=execution["symbol"]
        price=opens[symbol].get(execution["time"])
        if price is None:continue
        notional=abs(float(execution["quantity"]))*price
        spread+=notional*float(metadata[symbol]["spread_bps"])/20000
        slip+=notional*slippage/10000
    explicit=float(result.get("fees",0.))
    financing=float(result.get("margin_interest",0.))
    borrow=float(result.get("short_borrow_cost",0.))
    return {"explicit_total_usd":round(explicit,2),
            "transaction_and_fx_usd":round(explicit-financing-borrow,2),
            "margin_interest_usd":round(financing,2),
            "short_borrow_usd":round(borrow,2),
            "estimated_spread_usd":round(spread,2),
            "estimated_slippage_usd":round(slip,2),
            "implicit_costs_already_in_fill_prices":True,
            "method":"Trade sizes times real session open and assumed half spread/slippage; estimated, not realized broker fills."}

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
    "multi_sector_16": ("xlf","xle","xlv","xli","xlp","xly","xlu","xlk",
                        "xlb","xlre","ief","tlt","gld","efa","eem","spy"),
    "multi_asset_16": ("vti","iwm","efa","eem","ewj","ewc","xlv","xle",
                        "xlp","xlu","ief","shy","tip","gld","vnq","lqd"),
}
# The explicit seeds allow even a small but diverse archive to yield valid
# experiments. Dynamic baskets sample the entire screened inventory.
LEVERAGED_IDS = frozenset(("tqqq","sqqq","upro","spxu","vixy","cweb"))
SHORT_PROXY_IDS = frozenset(("sqqq","spxu"))
COST_ASSUMPTIONS = {
    "broker": "Wealthsimple indicative cash account model",
    "commission_usd": 0.0,
    "fx_conversion_bps": 150.0,
    "base_currency": "USD",
    "slippage_bps": 8.0,
    "delay_sessions": 1,
    "delayed_stress_sessions": 2,
    "time_target_hours": 12,
    "short_borrow_rate_annual": adv.BORROW_RATE_ANNUAL,
    "margin_rate_annual": adv.MARGIN_RATE_ANNUAL,
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


def enqueue(scope="all", delay_sessions=1, max_drawdown_pct=30, max_position_pct=35,
            research_objective="balanced", target_cagr_pct=55.,
            target_sharpe=2., risk_free_pct=3.,
            target_investment_pct=95., equity_class_cap_pct=70.,
            redistribute_excess=False,base_currency="USD",slippage_bps=8.,
            commission_usd=0.,fx_conversion_bps=150.,include_blends=True,
            basket_search="focused",selection_policy="return_risk",rebalance_sessions=21,
            assumed_gain_tax_pct=25.):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,detail="Owner research is unavailable in public demos.")
    if scope not in ("all","etfs","stocks") or delay_sessions not in (1,2):
        raise HTTPException(422, detail="Invalid research scope or fill latency.")
    if type(rebalance_sessions) is not int or rebalance_sessions not in pr.SUPPORTED_REBALANCE_SESSIONS:
        raise HTTPException(422, detail="Unsupported portfolio rebalance cadence.")
    if not 5<=max_drawdown_pct<=60 or not 10<=max_position_pct<=50:
        raise HTTPException(422,detail="Invalid research risk parameters.")
    if research_objective not in ("balanced","high_performance"):
        raise HTTPException(422,detail="Unsupported research objective.")
    if (not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
                for x in (target_cagr_pct,target_sharpe,risk_free_pct))
        or not 10<=target_cagr_pct<=100 or not .5<=target_sharpe<=5
        or not 0<=risk_free_pct<=15):
        raise HTTPException(422,detail="Invalid performance targets or risk-free assumption.")
    if (not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
                for x in (target_investment_pct,equity_class_cap_pct))
        or not 5<=target_investment_pct<=100 or not 10<=equity_class_cap_pct<=100
        or type(redistribute_excess) is not bool):
        raise HTTPException(422,detail="Invalid investment or asset-class concentration settings.")
    if basket_search not in ("focused","expanded") or selection_policy not in (
            "return_risk","execution_robust"):
        raise HTTPException(422,detail="Invalid basket search or validation selection policy.")
    if type(assumed_gain_tax_pct) not in (int,float) or not math.isfinite(assumed_gain_tax_pct) or not 0<=assumed_gain_tax_pct<=50:
        raise HTTPException(422,detail="Invalid effective tax sensitivity assumption.")
    if base_currency not in ("USD","CAD") or type(include_blends) is not bool:
        raise HTTPException(422,detail="Invalid research account or strategy mix setting.")
    if type(slippage_bps) not in (int,float) or not math.isfinite(slippage_bps) or not 0<=slippage_bps<=100:
        raise HTTPException(422,detail="Invalid research slippage assumption.")
    if any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=bound
           for x,bound in ((commission_usd,30),(fx_conversion_bps,300))):
        raise HTTPException(422,detail="Invalid commission or conversion assumption.")
    with LOCK,closing(_connection()) as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT count(*) FROM universe_jobs WHERE status IN ('queued','running')").fetchone()[0]>=MAX_QUEUE:
            raise HTTPException(429, detail="A universe scan is already queued or running.")
        if c.execute("SELECT count(*) FROM universe_jobs").fetchone()[0]>=MAX_STORED:
            raise HTTPException(409,detail="Archive old universe research before adding more jobs.")
        identity=str(uuid4()); now=_now()
        args={"scope":scope,"delay_sessions":delay_sessions,
              "rebalance_sessions":rebalance_sessions,
              "max_drawdown_pct":max_drawdown_pct,"max_position_pct":max_position_pct,
              "research_objective":research_objective,
              "target_cagr_pct":float(target_cagr_pct),
              "target_sharpe":float(target_sharpe),
              "risk_free_pct":float(risk_free_pct),
              "target_investment_pct":float(target_investment_pct),
              "equity_class_cap_pct":float(equity_class_cap_pct),
              "redistribute_excess":redistribute_excess,
              "base_currency":base_currency,"slippage_bps":float(slippage_bps),
              "commission_usd":float(commission_usd),
              "fx_conversion_bps":float(fx_conversion_bps),
              "include_blends":include_blends,
              "basket_search":basket_search,"selection_policy":selection_policy,
              "assumed_gain_tax_pct":float(assumed_gain_tax_pct)}
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
    """Prefer longest valid local archive, then maximum real provider history."""
    if load is not None:
        return load(asset_id)
    candidate=None
    for window in ("MAX","20Y","15Y","10Y","5Y"):
        try:
            bars=load_archived_history(asset_id,window)
            if len(bars)>=500 and (candidate is None or len(bars)>len(candidate)):
                candidate=bars
        except (OSError,ValueError,KeyError):
            pass
    # A short existing archive is not proof that the provider lacks older
    # history. Request MAX once; retain the longest valid real observation
    # window, even if the provider is unavailable afterward.
    try:
        provider=history(asset_id,"MAX")
        actual=provider.get("bars")
        if _quality(actual) and (candidate is None or len(actual)>=len(candidate)):
            return provider
    except (HTTPException,OSError,ValueError,KeyError,TypeError):
        pass
    if candidate:
        return {"bars":candidate,"source":"Local recorded provider OHLCV",
                "offline_cache":True}
    raise ValueError("Maximum available market history unavailable")


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
            baskets.append((label,selected[:16]))
    # Group-screen every instrument. These baskets are formed from training
    # and validation only. Do not screen using held-out returns.
    by_group=defaultdict(list)
    # Earlier than the 60% training boundary of *every* screened symbol.
    # An absolute two-year lookback could leak held-out years once MAX
    # data spans decades, so anchor screening to actual observed history.
    training_cutoff=min(
        int(histories[s]["bars"][max(1,int(len(histories[s]["bars"])*.60)-1)]["time"])
        for s in eligible
    )
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
    # Alternate training-only group leaders so a broad diversified 16-asset
    # portfolio is tested when the catalog provides sufficient coverage.
    mixed=[]
    for g in ("equity","bond","commodity","real_estate"):
        mixed.extend(sym for _,sym in by_group.get(g,[])[:4])
    if len(mixed)>=4:
        baskets.append(("screened_multi_class_16",mixed[:16]))
    if len(baskets)<2 and len(eligible)>=2:
        baskets.append(("available_universe",eligible[:16]))
    return baskets


def _scenarios(curve,seed=9):
    """Hypothetical daily returns, NOT predictions. Deterministic reproducible."""
    vals=[float(p["value"]) for p in curve]
    changes=[b/a-1 for a,b in zip(vals,vals[1:]) if a>0]
    if len(changes)<10:return {"status":"insufficient_observations","paths":[]}
    rng=random.Random(seed)
    paths=[]
    for horizon in (10,30,60,120):
      for label,stress in (("ordinary",0.),("slower_execution",-0.00035),
                           ("broad_market_shock",-0.004),("rebound",0.002)):
          finals=[];worsts=[];track=[[] for _ in range(horizon)]
          for _ in range(120):
              value=100.;peak=value;worst=0.
              for day in range(horizon):
                  draw=rng.choice(changes[-min(len(changes),180):])
                  extra=stress
                  if label=="broad_market_shock" and day==0:
                      extra-=.12
                  value=max(0.01,value*(1+max(-.99,draw+extra)))
                  track[day].append((value/100-1)*100)
                  peak=max(peak,value);worst=min(worst,value/peak-1)
              finals.append((value/100-1)*100);worsts.append(worst*100)
          finals.sort();worsts.sort()
          daily=[]
          for day,values in enumerate(track,1):
              values.sort()
              daily.append({"session":day,"p05_return_pct":round(values[6],2),
                            "median_return_pct":round(values[60],2),
                            "p95_return_pct":round(values[113],2)})
          paths.append({"name":label,"horizon_sessions":horizon,
                        "p05_return_pct":round(finals[6],2),
                        "median_return_pct":round(finals[60],2),
                        "p95_return_pct":round(finals[113],2),
                        "median_max_drawdown_pct":round(worsts[60],2),
                        "daily":daily})
    return {"status":"hypothetical_resampled_history","paths":paths,
            "method":"Historical daily strategy-return bootstrap with explicit adverse shocks; NOT a forecast or guaranteed probability."}


def run_study(params, *, loader=None, report=None, pause=time.sleep):
    """Return a transparent top-ten ranking without using held-out for selection."""
    report=report or (lambda *args:None)
    mode=params.get("research_objective","balanced")
    if mode not in ("balanced","high_performance"):
        raise ValueError("Invalid research objective")
    risk_free=float(params.get("risk_free_pct",3.))
    target_cagr=float(params.get("target_cagr_pct",55.))
    target_sharpe=float(params.get("target_sharpe",2.))
    if (not all(math.isfinite(v) for v in (risk_free,target_cagr,target_sharpe))
        or not 0<=risk_free<=15 or not 10<=target_cagr<=100
        or not .5<=target_sharpe<=5):
        raise ValueError("Invalid objective targets")
    investment=float(params.get("target_investment_pct",95.))
    equity_cap=float(params.get("equity_class_cap_pct",70.))
    redistribute=params.get("redistribute_excess",False)
    if (not all(math.isfinite(v) for v in (investment,equity_cap))
        or not 5<=investment<=100 or not 10<=equity_cap<=100
        or type(redistribute) is not bool):
        raise ValueError("Invalid capital allocation settings")
    # Job-local broker assumptions never leak across research runs.
    broker_assumptions={**COST_ASSUMPTIONS,
                        "base_currency":params.get("base_currency","USD"),
                        "slippage_bps":params.get("slippage_bps",8.),
                        "commission_usd":params.get("commission_usd",0.),
                        "fx_conversion_bps":params.get("fx_conversion_bps",150.)}
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
            histories[sym]={"bars":response["bars"],
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
    screen={"baskets":[],"cutoff_session":None,"screened":0,"pool_size":0,
            "method":"Focused deterministic basket seeds and training-only momentum screens."}
    if params.get("basket_search","focused")=="expanded" and histories:
        def grouping(symbol):
            item=assets.get_instrument(symbol)
            return pr._group(symbol,item.kind)
        screen=basket_optimizer.discover(histories,list(histories),grouping)
        prior={tuple(sorted(symbols)) for _,symbols in baskets}
        for label,symbols in screen["baskets"]:
            key=tuple(sorted(symbols))
            if key not in prior:
                prior.add(key);baskets.append((label,symbols))
    ranked=[];discarded=[];evaluated=0
    model_counts={name:0 for name in CANDIDATE_MODELS}
    # Cash, defensive, leveraged and short research models × viable baskets. All candidates
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
            corr_penalty,avg_positive_corr=_basket_correlation_penalty(
                symbols,market,train_end)
            common_broker={**broker_assumptions,
                           "delay_sessions":params["delay_sessions"],
                           "rebalance_sessions":params.get("rebalance_sessions",pr.REBALANCE_SESSIONS)}
            if mode=="high_performance":
                common_broker.update(target_investment_pct=investment,
                                     equity_class_cap_pct=equity_cap,
                                     redistribute_excess=redistribute)
            # Calculate once per basket on validation ONLY. Equal-weight is a
            # real independently funded control with identical fees and dates,
            # not an invented performance hurdle or a future-data lookup.
            try:
                equal_control=pr._segment("equal_weight",symbols,market,metadata,
                                           train_end,test_start,
                                           params["max_position_pct"]/100,
                                           broker=common_broker)
                equal_quality=objectives.performance(equal_control["equity_curve"],
                                                      risk_free_pct=risk_free)
            except (ValueError,ArithmeticError,ZeroDivisionError):
                equal_control=None
                equal_quality=None
            for model,sleeves in _model_configs(params.get("include_blends",True)):
                evaluated+=1
                broker={**common_broker}
                if mode!="high_performance":
                    broker.pop("target_investment_pct",None)
                    broker.pop("equity_class_cap_pct",None)
                    broker.pop("redistribute_excess",None)
                if sleeves is not None:
                    researcher=blends.segment;argument=sleeves
                else:
                    researcher=adv.segment if model in adv.MODELS else pr._segment
                    argument=model
                try:
                    train=researcher(argument,symbols,market,metadata,pr.WARMUP,
                                     train_end,params["max_position_pct"]/100,
                                     broker=broker)
                    valid=researcher(argument,symbols,market,metadata,train_end,
                                     test_start,params["max_position_pct"]/100,
                                     broker=broker)
                except (ArithmeticError, ValueError, ZeroDivisionError):
                    continue
                model_counts[model]+=1
                regimes=adv.scenario_grade(valid["equity_curve"],market,symbols,train_end)
                train_stable=train.get("ending_equity",0)>0
                passes=(train_stable
                        and abs(valid["max_drawdown_pct"])<=params["max_drawdown_pct"]
                        and valid["trades"]>0
                        and valid["average_invested_pct"]>=5
                        and not valid.get("margin_calls",0))
                # Selection uses validation ONLY. Drawdown, volatility,
                # turnover and performance in adverse observed regimes are
                # explicit penalizers rather than return alone.
                worst=regimes["worst_regime_return_pct"]
                volatility=valid.get("annualized_volatility_pct") or 0.
                if mode=="high_performance":
                    breakdown,quality,stability=objectives.score_breakdown(
                        valid,valid["equity_curve"],risk_free,
                        drawdown_limit=params["max_drawdown_pct"],
                        target_cagr_pct=target_cagr,target_sharpe=target_sharpe)
                    score=breakdown["total"]
                else:
                    quality=objectives.performance(valid["equity_curve"],
                                                   risk_free_pct=risk_free)
                    stability=objectives.validation_windows(
                        valid["equity_curve"],risk_free_pct=risk_free)
                    breakdown=_balanced_breakdown(valid,regimes,stability)
                    score=breakdown["total"]
                # Relative performance is part of validation ranking, not
                # evaluated from the sealed 20% test. Underperforming a
                # same-basket equal-weight control earns no fake alpha credit.
                benchmark_penalty,benchmark_advantage=_same_basket_validation_penalty(
                    valid,quality,equal_control,equal_quality)
                breakdown={**breakdown,
                           "components":{**breakdown["components"],
                                         "same_basket_underperformance_points":-benchmark_penalty},
                           "total":round(score-benchmark_penalty,4)}
                breakdown={**breakdown,
                           "components":{**breakdown["components"],
                                         "training_basket_correlation_points":-corr_penalty},
                           "total":round(score-corr_penalty,4)}
                score=breakdown["total"]
                validation_stress=None
                if passes and score>-1e5 and params.get("selection_policy","return_risk")=="execution_robust":
                    stressed_broker={**broker,"delay_sessions":2,
                                     "slippage_bps":max(20.,broker["slippage_bps"])}
                    try:
                        stressed=researcher(argument,symbols,market,metadata,
                                            train_end,test_start,
                                            params["max_position_pct"]/100,
                                            broker=stressed_broker)
                        # Stress guardrails use the validation segment ONLY.
                        # The final held-out history stays sealed.
                        if (not stressed["trades"] or stressed.get("margin_calls",0)
                            or abs(stressed["max_drawdown_pct"])>params["max_drawdown_pct"]):
                            continue
                        if mode=="high_performance":
                            stress_details,_,_=objectives.score_breakdown(
                                stressed,stressed["equity_curve"],risk_free,
                                drawdown_limit=params["max_drawdown_pct"],
                                target_cagr_pct=target_cagr,target_sharpe=target_sharpe)
                        else:
                            stress_regimes=adv.scenario_grade(stressed["equity_curve"],
                                                               market,symbols,train_end)
                            stress_stability=objectives.validation_windows(
                                stressed["equity_curve"],risk_free_pct=risk_free)
                            stress_details=_balanced_breakdown(stressed,stress_regimes,
                                                               stress_stability)
                        if not stress_details["eligible"]:continue
                        # Only downside execution deterioration is penalized;
                        # an unexpectedly better stress outcome cannot earn bonus points.
                        score_without_reference=score+benchmark_penalty+corr_penalty
                        penalty=round(-.5*max(0.,score_without_reference-stress_details["total"]),6)
                        breakdown={**breakdown,
                                   "components":{**breakdown["components"],
                                                 "execution_stress_points":penalty},
                                   "total":round(score+penalty,4)}
                        score=breakdown["total"]
                        validation_stress={"return_pct":stressed["return_pct"],
                            "max_drawdown_pct":stressed["max_drawdown_pct"],
                            "score":stress_details["total"],
                            "delay_sessions":2,
                            "slippage_bps":stressed_broker["slippage_bps"],
                            "selection_only_validation_data":True}
                    except (ArithmeticError,ValueError,ZeroDivisionError):
                        continue
                if passes and score>-1e5:
                    ranked.append({"basket_type":label,"symbols":symbols,
                                   "model":model,"sleeves":sleeves,
                                   "validation_benchmark_advantage":benchmark_advantage,
                                   "training_avg_positive_pair_correlation":avg_positive_corr,
                                   "score_breakdown":breakdown,"score":score,
                                   "validation_execution_stress":validation_stress,
                                   "validation_objectives":quality,
                                   "validation_stability":stability,
                                   "train":pr._compact(train),
                                   "validation":pr._compact(valid),
                                   "regime_validation":regimes,
                                   "_validation_curve":valid["equity_curve"],
                                   "_validation_executions":valid["executions"],
                                   "_market":market,"_metadata":metadata,
                                   "_test_start":test_start,"_n":n,
                                   "_first_session":days[0],
                                   "_last_session":days[-1]})
            report(58+int(34*(ix+1)/max(1,len(baskets))),
                   f"Comparing {ix+1}/{len(baskets)} portfolio baskets",
                   len(universe),len(histories))
        except (HTTPException,ValueError,ArithmeticError,TypeError,KeyError) as exc:
            discarded.append({"basket":label,"reason":type(exc).__name__})
    ranked.sort(key=lambda x:(-x["score"],x["basket_type"],x["model"]))
    # An identical set of symbols and sleeve rules cannot count as multiple
    # independent candidates just because two basket-screening labels found it.
    unique=[];keys=set()
    for row in ranked:
        identifier=(tuple(sorted(row["symbols"])),row["model"],
                    tuple((sleeve["model"],sleeve["weight_pct"])
                          for sleeve in row["sleeves"] or []))
        if identifier in keys:continue
        keys.add(identifier)
        unique.append(row)
    ranked=unique
    # The Pareto frontier is diagnostic only. Neither it nor the held-out test
    # can override the explicitly validation-only ranking.
    if mode=="high_performance":
        for item in ranked:
            quality=item["validation_objectives"]
            item["pareto_optimal"]=(
                quality["cagr_pct"] is not None and
                quality["excess_sharpe"] is not None and
                not any(other is not item and objectives.dominates(other,item)
                        for other in ranked))
    # User-facing selection is ONE executable portfolio. No seeded bucket
    # representatives, model-family quotas or final-audit return sorting.
    # Price-ledger fees are already netted; taxes are an explicit reserve
    # sensitivity and never masquerade as a legal tax estimate.
    selected,practical=practical_selection.choose(
        ranked,max_drawdown_pct=params["max_drawdown_pct"],
        tax_rate_pct=float(params.get("assumed_gain_tax_pct",25.)),
        base_currency=broker_assumptions["base_currency"],
        require_delay_stress=params.get("selection_policy","return_risk")=="execution_robust")
    chosen=[selected] if selected is not None else []
    leaders=[]
    for i,item in enumerate(chosen):
        broker={**broker_assumptions,"delay_sessions":params["delay_sessions"],
                "rebalance_sessions":params.get("rebalance_sessions",pr.REBALANCE_SESSIONS)}
        if mode=="high_performance" and (item["model"] in pr.MODELS or item["sleeves"] is not None):
            broker.update(target_investment_pct=investment,
                          equity_class_cap_pct=equity_cap,
                          redistribute_excess=redistribute)
        slow={**broker,"delay_sessions":2,"slippage_bps":max(20.,broker["slippage_bps"])}
        researcher=(blends.segment if item["sleeves"] is not None else
                    adv.segment if item["model"] in adv.MODELS else pr._segment)
        argument=item["sleeves"] if item["sleeves"] is not None else item["model"]
        test=researcher(argument,item["symbols"],item["_market"],
                         item["_metadata"],item["_test_start"],item["_n"],
                         params["max_position_pct"]/100,broker=broker)
        stress=researcher(argument,item["symbols"],item["_market"],
                           item["_metadata"],item["_test_start"],item["_n"],
                           params["max_position_pct"]/100,broker=slow)
        validation_quality=item["validation_objectives"]
        heldout_quality=objectives.performance(
            test["equity_curve"],risk_free_pct=risk_free)
        stress_quality=objectives.performance(
            stress["equity_curve"],risk_free_pct=risk_free)
        sufficient_test=heldout_quality["sessions"]>=126
        targets_observed=(sufficient_test and
            heldout_quality["cagr_pct"] is not None and
            heldout_quality["excess_sharpe"] is not None and
            heldout_quality["cagr_pct"]>=target_cagr and
            heldout_quality["excess_sharpe"]>=target_sharpe and
            abs(test["max_drawdown_pct"])<=params["max_drawdown_pct"])
        leaders.append({
            "rank":i+1,
            "validation_objectives":validation_quality,
            "validation_stability":item["validation_stability"],
            "validation_benchmark_advantage":item["validation_benchmark_advantage"],
            "training_avg_positive_pair_correlation":item["training_avg_positive_pair_correlation"],
            "validation_quality_label":(
                "benchmark_advantage" if item["validation_benchmark_advantage"] is not None
                and item["validation_benchmark_advantage"]["beats_same_basket_return"]
                and item["validation_benchmark_advantage"]["beats_same_basket_risk_adjusted"]
                else "not_yet_demonstrated"),
            "held_out_objectives":heldout_quality,
            "delayed_stress_objectives":stress_quality,
            "pareto_optimal_validation":bool(item.get("pareto_optimal",False)),
            "held_out_target_observed":bool(targets_observed),
            "held_out_target_evaluable":sufficient_test,"basket_type":item["basket_type"],"symbols":item["symbols"],
            "model":item["model"],"sleeves":item["sleeves"],
            "score_breakdown":item["score_breakdown"],
            "validation_execution_stress":item["validation_execution_stress"],
            "held_out_cost_audit":_execution_cost_audit(test,item["_market"],item["_metadata"],broker["slippage_bps"]),
            "validation_score":practical["selected"]["score"],
            "original_validation_score":item["score"],
            "practical_selection":practical["selected"],
            "training":item["train"],"validation":item["validation"],
            "validation_regimes":item["regime_validation"],
            "held_out_regimes":adv.scenario_grade(test["equity_curve"],
                item["_market"],item["symbols"],item["_test_start"]),
            "coverage":{"first_session":item["_first_session"],
                        "last_session":item["_last_session"],"common_sessions":item["_n"]},
            "research_only":item["model"] in adv.RESEARCH_ONLY or item["sleeves"] is not None,
            "held_out":pr._compact(test),
            "delayed_execution_stress":pr._compact(stress),
            "hypothetical_scenarios":_scenarios(item["_validation_curve"],seed=42+i),
            "scenario_calibration":"Validation-period strategy outcomes only; held-out prices are not used for projections.",
            "execution_model":"Next common-session open from completed prior session; "
                              "2-session +20bps adverse execution stress. "
                              "Calendar latency may exceed 12h.",
            "restricted_research":any(s in LEVERAGED_IDS for s in item["symbols"]),
            "short_proxy_research":any(s in SHORT_PROXY_IDS for s in item["symbols"]),
            "no_real_order":True,
            "held_out_execution_sample":test["executions"][:40],
        })
    report(98,"Saving ranked research and hypothetical scenarios",
           len(universe),len(histories))
    return {
        "universe_count":len(universe),"screened_count":len(universe),
        "eligible_count":sum(1 for sym in universe if sym in histories and sym not in rejected),
        "excluded_count":len(rejected),"exclusions":rejected,
        "basket_count":len(baskets),"candidates_evaluated":evaluated,
        "basket_search":params.get("basket_search","focused"),
        "selection_policy":params.get("selection_policy","return_risk"),
        "asset_screen":{"screen_cutoff":screen.get("cutoff_session"),
                        "screened_instruments":screen.get("screened",0),
                        "screened_pool":screen.get("pool_size",0),
                        "generated_baskets":len(screen.get("baskets",[])),
                        "method":screen["method"]},
        "candidate_model_counts":model_counts,
        "historical_coverage":{"universe_earliest_session":min((
            datetime.fromtimestamp(int(h["bars"][0]["time"]),timezone.utc).date().isoformat()
            for h in histories.values() if h.get("bars")),default=None),
            "universe_latest_session":max((
            datetime.fromtimestamp(int(h["bars"][-1]["time"]),timezone.utc).date().isoformat()
            for h in histories.values() if h.get("bars")),default=None),
            "method":"Maximum available provider or locally recorded daily history; overlap depends on each basket"},
        "qualified_candidates":len(ranked),"rejected_baskets":discarded,
        "research_objective":mode,
        "objective_targets":{"cagr_pct":target_cagr,
                             "excess_sharpe":target_sharpe,
                             "risk_free_pct":risk_free,
                             "max_drawdown_pct":params["max_drawdown_pct"]},
        "pareto_candidate_count":sum(bool(item.get("pareto_optimal",False)) for item in ranked),
        "shortlist_targets_observed":sum(bool(item["held_out_target_observed"]) for item in leaders),
        "top10":leaders,
        "best_strategy":leaders[0] if leaders else None,
        "single_best_selection":practical,
        "selection_method":(
            ("Expanded correlation-aware asset search; " if params.get("basket_search","focused")=="expanded" else "Focused asset screening; ")
            +("Execution-stressed validation ranking; " if params.get("selection_policy","return_risk")=="execution_robust" else "Standard validation ranking; ")
            +(
            "High-performance discovery: shortlist candidates using validation-only "
            "annualized compound growth and cash-rate-adjusted Sharpe with caps, "
            "penalties for drawdowns, turnover and negative validation subperiods. "
            "The final 20% is evaluated only AFTER ranking. A three-window stability "
            "diagnostic is not a trained walk-forward model. Validation ranking "
            "penalizes underperformance versus a same-basket equal-weight control; "
            "a single manually cash-executable candidate is selected by "
            "validation Sharpe, drawdown and realistic fee, FX, tax-sensitivity "
            "and delayed-execution penalties."
            if mode=="high_performance" else
            "Choose one cash-executable portfolio using Sharpe, drawdown, "
            "same-basket benchmark, realistic trading costs, delayed-fill stress, "
            "FX/account complexity and assumed realized-gain tax sensitivity. "
            "No family buckets or extra winners. Held-out tests never select the model.")),
        "shortlist_is_global_top_ten":False,
        "selection_is_single_practical_candidate":True,
        "execution_assumptions":{**broker_assumptions,"configured_delay_sessions":params["delay_sessions"],
                                  "rebalance_sessions":params.get("rebalance_sessions",pr.REBALANCE_SESSIONS),
                                 "long_only_target_investment_pct":investment if mode=="high_performance" else 95.,
                                 "long_only_equity_class_cap_pct":equity_cap if mode=="high_performance" else 70.,
                                 "long_only_redistribute_excess":redistribute if mode=="high_performance" else False,
                                 "commission_note":"User-configured per-order commission and FX bps apply only when currency differs from the funding account. Estimates, not verified broker charges.",
                                 "assumed_gain_tax_pct":float(params.get("assumed_gain_tax_pct",25.)),
                                 "tax_method":"Positive realized sale profits times an assumed effective rate, for ranking sensitivity only. No accurate after-tax equity."},
        "test_used_for_selection":False,
        "limitations":[
            "Expanded asset search screens only observations before the earliest training cutoff; validation and held-out prices cannot influence basket constituents, but the catalog may still have survivorship bias.",
            "Execution-robust selection tests a second-session 20bps-minimum slippage scenario on validation only and penalizes deterioration; daily open bars cannot establish executable 12-hour intraday liquidity.",
            "Blended portfolios use one shared long-only cash and transaction ledger. They are research-only until supported by the strategy importer and live monitor.",
            "Historical coverage may exclude delisted symbols; verify point-in-time survivorship and corporate-action adjustments before relying on results.",
            "Explicit fees and implicit spread/slippage are reported separately; implicit costs are already in modeled fill prices and must not be double-counted.",
            "The high-performance goal is an optimization target, not a return guarantee. A three-window validation diagnostic does not constitute walk-forward model refitting, a deflated Sharpe ratio, or a live forward trial.",
            "The risk-free rate for excess Sharpe is a constant user-specified annual assumption, not a historical cash yield series; the simulator does not credit cash interest.",
            "Observed held-out target achievements are descriptive only and require at least 126 held-out sessions. They cannot establish yearly consistency or a replicable investment edge.",
            "The current provider-backed universe covers available USD/CAD stocks and ETFs. Futures, currencies, crypto and option contracts need separate historical pricing and execution models; excluded instruments are reported.",
            "Only symbols with sufficient actual valid historical daily data are evaluated. Exclusions are reported, not backfilled with synthetic observations.",
            "Research-only short and margin models use synthetic negative holdings, 6% annual short borrow and 8.5% margin funding assumptions, with 25% maintenance margin. These are approximations and cannot be deployed as Wealthsimple share shorts.",
            "No direct Wealthsimple broker-price API, order routing, options margin engine, cash settlement, legal tax calculation or dividend-adjusted total returns.",
            "The optional positive realized gain tax-reserve approximation does not account for loss offsets, capital-gain inclusion, business income classification, registered account rules or investor circumstances; it is not after-tax performance.",
            "The single best candidate is based solely on pre-audit validation; signed shares and riskier leveraged/inverse ETF proxies are disqualified for simple cash-account operation.",
            "Signals from completed daily candles can take more than 12 calendar hours to reach the next regular-session open. A two-session stress test measures a longer delay.",
            "Rebalance sessions count daily shared close signals, not intraday opportunities. Daily cadence can increase costs and does not guarantee trades.",
            "Hypothetical future paths resample historical strategy outcomes and add shocks. They are not predictions or calibrated probabilities.",
            "Ticker universe and available listings introduce survivorship bias. Historical OHLCV can be incomplete and requires point-in-time symbol membership and corporate-action data for stronger conclusions.",
        ],
        "automation":"Runs signed margin and short exposure in private historical research only. Never submits any brokerage order.",
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
