"""Private, multi-asset portfolio strategy comparison with no future-bar reads.

Cross-asset strategy research is intentionally separate from single-asset
SMA discovery and live order deployment. Research is persisted in a private
Git-ignored SQLite file and never automatically sends broker orders.
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
from .research_optimizer import _stats

DB_PATH = Path(os.environ.get(
    "TRADING_SIM_PORTFOLIO_RESEARCH_DB",
    Path(__file__).resolve().parents[1] / "data" / "portfolio_research.sqlite3",
))
LOCK = RLock()
MAX_SYMBOLS = 10
STARTING_CAPITAL = 100000.0
REBALANCE_SESSIONS = 21
WARMUP = 180
MODELS = ("equal_weight", "inverse_volatility", "trend_filter",
          "relative_momentum", "volatility_target")
GROUP_CAPS = {"equity": .70, "bond": .55, "commodity": .35, "real_estate": .20, "crypto": .10}
BONDS = frozenset(("tlt", "ief", "shy", "bnd", "lqd", "hyg", "tip", "agg", "vgit"))
COMMODITIES = frozenset(("gld", "slv", "uso", "dbc", "pdbc", "iau", "sgol"))
REAL_ESTATE = frozenset(("vnq", "reit", "iyr", "xlre"))
CRYPTO_ETFS = frozenset(("ibit",))


def _group(symbol: str, kind: str) -> str:
    if kind == "Crypto" or symbol in CRYPTO_ETFS:
        return "crypto"
    if symbol in REAL_ESTATE:
        return "real_estate"
    if symbol in BONDS:
        return "bond"
    if symbol in COMMODITIES:
        return "commodity"
    return "equity"


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS portfolio_research_runs (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
        basket TEXT NOT NULL, payload TEXT NOT NULL
    )""")
    return conn


def _validate_basket(symbols: list[str]):
    if not isinstance(symbols, list) or not 2 <= len(symbols) <= MAX_SYMBOLS:
        raise HTTPException(422, detail="Research requires 2-10 portfolio instruments.")
    basket = []
    for symbol in symbols:
        if not isinstance(symbol, str) or not 1 <= len(symbol) <= 32:
            raise HTTPException(422, detail="Invalid instrument symbol.")
        key = symbol.lower().strip()
        if not key.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise HTTPException(422, detail="Invalid instrument symbol.")
        if key in basket:
            raise HTTPException(422, detail="Portfolio symbols must be unique.")
        instrument = get_instrument(key)
        if instrument.currency != "USD" or instrument.kind not in ("Stocks", "ETFs", "Crypto"):
            raise HTTPException(422, detail="Current portfolio research requires USD stocks, ETFs or crypto.")
        basket.append(key)
    return basket


def _prepare(symbols, histories):
    """Use actual overlapping daily sessions, never fill a missing observation."""
    maps, metadata, sources = {}, {}, {}
    for symbol in symbols:
        raw = histories[symbol]
        if raw.get("is_demo"):
            raise HTTPException(422, detail="Synthetic demo market data cannot be treated as historical research.")
        bars = raw.get("bars")
        if not isinstance(bars, list):
            raise HTTPException(422, detail="Missing historical candles.")
        current = {}
        last = -1
        for bar in bars:
            try:
                t = int(bar["time"])
                op, close = float(bar["open"]), float(bar["close"])
                high, low = float(bar["high"]), float(bar["low"])
            except (KeyError, TypeError, ValueError):
                raise HTTPException(422, detail="Invalid historical OHLC candle.") from None
            if (t <= last or not all(math.isfinite(v) and v > 0
                                     for v in (op, close, high, low)) or
                low > min(op, close) or high < max(op, close)):
                raise HTTPException(422, detail="Unsorted, nonfinite or inconsistent OHLC candle.")
            day = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
            if day in current:
                raise HTTPException(422, detail="Expected daily rather than intraday market bars.")
            last = t
            current[day] = {"time": t, "open": op, "close": close}
        maps[symbol] = current
        item = get_instrument(symbol)
        metadata[symbol] = {"group": _group(symbol, item.kind),
                            "spread_bps": float(item.spread_bps),
                            "kind": item.kind}
        sources[symbol] = str(raw.get("source") or "unknown provider")[:120]
    shared = sorted(set.intersection(*(set(maps[s]) for s in symbols)))
    if len(shared) < 450:
        raise HTTPException(422, detail="Portfolio requires at least 450 actual overlapping trading sessions.")
    if shared[-1] <= shared[0]:
        raise HTTPException(422, detail="No valid historical overlap.")
    # One timeline for every strategy; no backfilling stale or closed markets.
    market = {s: [maps[s][d] for d in shared] for s in symbols}
    return shared, market, metadata, sources


def _returns(prices, i, window=60):
    start = max(1, i-window)
    return [prices[k] / prices[k-1]-1 for k in range(start, i)]


def _vol(prices, i, window=60):
    values = _returns(prices, i, window)
    return max(stdev(values), .002) if len(values) > 1 else .02


def _corr(a, b):
    if len(a) < 3 or len(b) != len(a):
        return None
    aa, bb = mean(a), mean(b)
    da = sum((x-aa)**2 for x in a)
    db = sum((y-bb)**2 for y in b)
    if da <= 1e-16 or db <= 1e-16:
        return None
    result = sum((x-aa)*(y-bb) for x,y in zip(a,b)) / math.sqrt(da*db)
    return round(max(-1., min(1., result)), 4)


def _weights(model, symbols, closes, i, metadata, max_weight):
    """All signals and risk estimates read only through previous session i-1."""
    vol = {s:_vol(closes[s], i) for s in symbols}
    recent = {s:closes[s][i-1] for s in symbols}
    inv = {s:1/vol[s] for s in symbols}
    if model == "equal_weight":
        raw = {s:1. for s in symbols}
    elif model == "inverse_volatility":
        raw = inv
    elif model == "trend_filter":
        raw = {s:inv[s] if recent[s] > mean(closes[s][i-126:i]) else 0.
               for s in symbols}
    elif model == "relative_momentum":
        strength = {s: .5*(recent[s]/closes[s][i-64]-1) +
                      .5*(recent[s]/closes[s][i-127]-1)
                    for s in symbols}
        chosen = set(sorted(symbols,key=lambda s:strength[s],reverse=True)
                     [:max(2, math.ceil(len(symbols)/3))])
        raw = {s:inv[s] if s in chosen and strength[s]>0 else 0.
               for s in symbols}
    elif model == "volatility_target":
        raw = inv
    else:
        raise ValueError("Unknown allocation model")
    total = sum(raw.values())
    if total <= 0:
        return {s:0. for s in symbols}
    # Shrink to a target annualized portfolio risk, based on the LAST 60
    # observed close-to-close returns, without using current-session prices.
    gross = .95
    if model == "volatility_target":
        base = {s:raw[s]/total for s in symbols}
        observations = [_returns(closes[s],i) for s in symbols]
        days = min(len(x) for x in observations)
        if days >= 25:
            series = [sum(base[s]*observations[j][-days+k]
                          for j,s in enumerate(symbols)) for k in range(days)]
            realized = stdev(series)*math.sqrt(252)
            if realized > 1e-8:
                gross = min(gross, .12/realized)
    targets = {s:min(max_weight, gross*raw[s]/total) for s in symbols}
    # Caps on risk categories, including crypto. Keep residual in cash;
    # never redistribute excess into a highly correlated subgroup.
    for group, cap in GROUP_CAPS.items():
        names = [s for s in symbols if metadata[s]["group"]==group]
        amount = sum(targets[s] for s in names)
        if amount > cap:
            for s in names:
                targets[s] *= cap/amount
    return targets


def _segment(model, symbols, market, metadata, start, stop, max_weight):
    """One shared cash ledger and next-open fills, never prior-close fills."""
    cash = STARTING_CAPITAL
    holdings = {s:0. for s in symbols}
    closes = {s:[b["close"] for b in market[s]] for s in symbols}
    trades, curve, total_fees = [], [], 0.
    exposure_total = 0.
    rebalance_samples = []
    for i in range(start, stop):
        opens = {s:market[s][i]["open"] for s in symbols}
        if (i-start)%REBALANCE_SESSIONS==0:
            targets = _weights(model,symbols,closes,i,metadata,max_weight)
            total_equity = cash+sum(holdings[s]*opens[s] for s in symbols)
            # Sell first, freeing cash for reallocations.
            for side in ("sell","buy"):
                for s in symbols:
                    px = opens[s]*(1+(1 if side=="buy" else -1)*
                                   (metadata[s]["spread_bps"]/2+2)/10000)
                    desired = (total_equity*targets[s])/px
                    # Fractional crypto; integer equity/ETF shares.
                    if metadata[s]["kind"]!="Crypto":
                        desired = math.floor(desired+1e-9)
                    delta = desired-holdings[s]
                    if side=="sell" and delta>=-1e-8:
                        continue
                    if side=="buy" and delta<=1e-8:
                        continue
                    qty = min(holdings[s],-delta) if side=="sell" else delta
                    if side=="buy":
                        # Fees are included in cash checks; never borrow.
                        qty = min(qty,max(0.,(cash-1)/max(px,1e-9)))
                        if metadata[s]["kind"]!="Crypto":
                            qty = math.floor(qty+1e-9)
                    if qty*px<1 or qty<=1e-9:
                        continue
                    fee=max(1.,qty*.005)
                    if side=="buy":
                        while qty>0 and qty*px+fee>cash+1e-6:
                            qty = qty*.999 if metadata[s]["kind"]=="Crypto" else qty-1
                            fee=max(1.,qty*.005)
                        if qty<=0:continue
                        cash-=qty*px+fee
                        holdings[s]+=qty
                    else:
                        cash+=qty*px-fee
                        holdings[s]-=qty
                        if abs(holdings[s])<1e-8:holdings[s]=0.
                    total_fees+=fee
                    trades.append({"time":market[s][i]["time"],"symbol":s,
                                   "side":side,"quantity":round(qty,8),
                                   "price":round(px,6),"fee":round(fee,6),
                                   "notional":round(qty*px,2),
                                   "execution":"next_session_open"})
            equity_open = cash+sum(holdings[s]*opens[s] for s in symbols)
            current = {s:holdings[s]*opens[s]/equity_open for s in symbols}
            rebalance_samples.append({"time":market[symbols[0]][i]["time"],
                                       "weights":{k:round(v,6) for k,v in current.items()},
                                       "cash_pct":round(cash/equity_open*100,2)})
        value = cash+sum(holdings[s]*closes[s][i] for s in symbols)
        if value<=0 or not math.isfinite(value):
            raise ArithmeticError("Invalid simulated portfolio equity")
        exposure_total+=sum(holdings[s]*closes[s][i] for s in symbols)/value
        curve.append({"time":market[symbols[0]][i]["time"],"value":round(value,4)})
    stats = _stats(curve,trades,STARTING_CAPITAL)
    turnover=sum(t["notional"] for t in trades)/STARTING_CAPITAL*100
    value = curve[-1]["value"]
    weights = {s:holdings[s]*closes[s][stop-1]/value for s in symbols}
    stats.update({"fees":round(total_fees,2),"turnover_pct":round(turnover,2),
                  "cash_pct":round(cash/value*100,2),
                  "average_invested_pct":round(exposure_total/(stop-start)*100,2),
                  "final_weights_pct":{s:round(weights[s]*100,2) for s in symbols},
                  "effective_positions":round(1/sum(v*v for v in weights.values()),2)
                                         if sum(v*v for v in weights.values())>1e-12 else 0.,
                  "rebalances":rebalance_samples,
                  "starting_capital":STARTING_CAPITAL,
                  "ending_equity":round(value,2)})
    return stats


def _compact(metric):
    return {k:v for k,v in metric.items()
            if k not in ("equity_curve","executions","rebalances")}


def _correlations(symbols, market, end):
    closes = {s:[b["close"] for b in market[s]] for s in symbols}
    window = min(126,end-1)
    values = {s:_returns(closes[s],end,window) for s in symbols}
    return {s:{t:(1. if s==t else _corr(values[s],values[t]))
               for t in symbols} for s in symbols}


def compare(symbols:list[str], max_drawdown_pct:float=25.,
            max_position_pct:float=35., data=None):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,detail="Owner portfolio research is unavailable in public demo.")
    if not 1<=max_drawdown_pct<=50 or not math.isfinite(max_drawdown_pct):
        raise HTTPException(422,detail="Maximum validation drawdown must be 1-50%.")
    if not 5<=max_position_pct<=50 or not math.isfinite(max_position_pct):
        raise HTTPException(422,detail="Maximum single-position weight must be 5-50%.")
    symbols=_validate_basket(symbols)
    if data is None:
        histories = {s:history(s,"5Y") for s in symbols}
    else:
        if not isinstance(data,dict) or set(data)!=set(symbols):
            raise HTTPException(422,detail="Must provide data for every instrument.")
        histories = data
    days,market,metadata,sources=_prepare(symbols,histories)
    n=len(days);train_end=int(n*.6);test_start=int(n*.8)
    candidates=[]
    for model in MODELS:
        train=_segment(model,symbols,market,metadata,WARMUP,train_end,max_position_pct/100)
        valid=_segment(model,symbols,market,metadata,train_end,test_start,max_position_pct/100)
        allowed=(abs(valid["max_drawdown_pct"])<=max_drawdown_pct
                 and valid["trades"]>0 and valid["average_invested_pct"]>=5)
        # Validation score only; avoid using held-out sample to select.
        score=(valid["return_pct"]-1.5*abs(valid["max_drawdown_pct"])
               -.025*valid["turnover_pct"])
        candidates.append({"model":model,"score":round(score,4),
                           "qualified":bool(allowed),
                           "train":_compact(train),"validation":_compact(valid)})
    candidates.sort(key=lambda c:(c["score"],c["model"]),reverse=True)
    qualified=[c for c in candidates if c["qualified"]]
    winner=qualified[0]["model"] if qualified else None
    # A single held-out evaluation is permitted once selection is frozen.
    selected=None
    if winner:
        heldout=_segment(winner,symbols,market,metadata,test_start,n,max_position_pct/100)
        equal=_segment("equal_weight",symbols,market,metadata,test_start,n,max_position_pct/100)
        chosen=next(c for c in candidates if c["model"]==winner)
        selected={"model":winner,"train":_segment(winner,symbols,market,metadata,
                    WARMUP,train_end,max_position_pct/100),
                  "validation":_segment(winner,symbols,market,metadata,
                    train_end,test_start,max_position_pct/100),
                  "held_out_test":heldout,
                  "held_out_equal_weight_benchmark":equal,
                  "warning":"Historical research only. A single held-out period cannot validate future performance. No strategy was deployed."}
    groups={group:[s for s in symbols if metadata[s]["group"]==group]
            for group in GROUP_CAPS}
    record={
        "basket":symbols,"groups":{k:v for k,v in groups.items() if v},
        "sources":sources,"first_session":days[0],"last_session":days[-1],
        "sessions":n,"train_sessions":train_end-WARMUP,
        "validation_sessions":test_start-train_end,"test_sessions":n-test_start,
        "warmup_sessions":WARMUP,"rebalance_sessions":REBALANCE_SESSIONS,
        "max_drawdown_limit_pct":max_drawdown_pct,
        "max_position_pct":max_position_pct,
        "candidate_count":len(candidates),"eligible_count":len(qualified),
        "models":list(MODELS),"candidates":candidates,
        "selected":selected,"correlation_matrix":_correlations(symbols,market,test_start),
        "test_used_for_selection":False,
        "assumptions":("USD historical daily bars, common observed trading sessions only; "
                       "signals use completed previous-session closes; trades execute at next common-session open; "
                       "monthly rebalancing, shared cash, long-only, no leverage; "
                       "spread plus 2 bps slippage per fill and minimum $1 commission; "
                       "crypto fractions and integer stock/ETF shares; "
                       "no dividends, financing, FX, taxes, shorting, or broker fills. "
                       "Crypto weekends are excluded if combined with market-day assets. "
                       "Single-asset max weight and asset-group caps apply; unused capacity stays in cash."),
        "qualification_note":("One validation-qualified portfolio model selected using validation only."
                               if winner else "No portfolio model met validation drawdown and activity limits."),
    }
    identity=str(uuid4());stamp=datetime.now(timezone.utc).isoformat()
    with LOCK:
        conn=_db()
        try:
            with conn:
                conn.execute("INSERT INTO portfolio_research_runs VALUES(?,?,?,?)",
                             (identity,stamp,json.dumps(symbols),
                              json.dumps(record,allow_nan=False)))
        finally:
            conn.close()
    return {"id":identity,"created_at":stamp,**record}


def list_runs(limit=20):
    with LOCK:
        conn=_db()
        try:
            rows=conn.execute("SELECT * FROM portfolio_research_runs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
            return [{"id":r["id"],"created_at":r["created_at"],
                     "basket":json.loads(r["basket"]),
                     "selected":json.loads(r["payload"])["selected"]["model"]
                         if json.loads(r["payload"])["selected"] else None}
                    for r in rows]
        finally:
            conn.close()


def load_run(run_id:str):
    with LOCK:
        conn=_db()
        try:
            row=conn.execute("SELECT * FROM portfolio_research_runs WHERE id=?",(run_id,)).fetchone()
            if row is None:raise HTTPException(404,detail="Portfolio research run not found.")
            return {"id":row["id"],"created_at":row["created_at"],**json.loads(row["payload"])}
        finally:
            conn.close()
