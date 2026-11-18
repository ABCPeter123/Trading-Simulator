"""Private forward-paper ledger for frozen walk-forward portfolio selections.

This monitor observes ONLY completed real sessions newer than its activation
baseline. It models estimated fills at a later observed open, never places
broker orders and never writes to the confirmed-trade journal. Neither private
selected rules nor run output may be committed to the public repository.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from . import (advanced_portfolio_research as adv, blended_portfolio_research as blended,
               performance_objectives as metrics, portfolio_research as pr,
               walkforward_queue)
from .assets import get_instrument
from .market import history

NY = ZoneInfo("America/New_York")
DB_PATH = Path(os.environ.get("TRADING_SIM_PAPER_FORWARD_DB",
    Path(__file__).resolve().parents[1] / "data/paper_forward.sqlite3"))
LOCK = RLock()
MAX_STUDIES = 30
REBALANCE = pr.REBALANCE_SESSIONS
BORROW_RATE = adv.BORROW_RATE_ANNUAL
MARGIN_RATE = adv.MARGIN_RATE_ANNUAL
MAINTENANCE = adv.MAINTENANCE_RATIO


class PaperContinuityError(ValueError):
    """Observed sessions were missed, so a forward study cannot backfill."""


class PaperRiskError(ValueError):
    """The hypothetical ledger breached a hard portfolio risk condition."""


def _private():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1":
        raise HTTPException(403, "Forward-paper research is unavailable in public demos.")


def _now(now=None):
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        raise ValueError("An aware clock is required.")
    return dt.astimezone(timezone.utc)


def _dump(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS paper_studies(
        id TEXT PRIMARY KEY, source_job TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, status TEXT NOT NULL,
        config TEXT NOT NULL, symbols TEXT NOT NULL, capital REAL NOT NULL,
        max_drawdown REAL NOT NULL, starting_session TEXT NOT NULL,
        last_session TEXT NOT NULL, state TEXT NOT NULL,
        audit_reference TEXT NOT NULL, last_error TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS paper_marks(
        study_id TEXT NOT NULL, session TEXT NOT NULL, value REAL NOT NULL,
        cash REAL NOT NULL, gross_pct REAL NOT NULL, drawdown_pct REAL NOT NULL,
        financing_cost REAL NOT NULL, PRIMARY KEY(study_id,session))""")
    c.execute("""CREATE TABLE IF NOT EXISTS paper_fills(
        id TEXT PRIMARY KEY, study_id TEXT NOT NULL, session TEXT NOT NULL,
        symbol TEXT NOT NULL, action TEXT NOT NULL, quantity INTEGER NOT NULL,
        price REAL NOT NULL, fee REAL NOT NULL, delay_sessions INTEGER NOT NULL,
        simulated INTEGER NOT NULL DEFAULT 1)""")
    c.execute("CREATE INDEX IF NOT EXISTS paper_fills_study ON paper_fills(study_id,session)")
    return c


def _portfolio(symbols, at, loader=None):
    """Reject demo/cached/unfinished bars; align actual common USD sessions."""
    load = loader or history
    histories = {}
    for symbol in symbols:
        item = get_instrument(symbol)
        if (item.kind not in ("Stocks", "ETFs") or item.currency != "USD"
                or not item.tradable):
            raise ValueError("Forward paper supports tradable USD stocks and ETFs only.")
        response = load(symbol, "5Y")
        if not isinstance(response, dict) or response.get("is_demo") or response.get("offline_cache"):
            raise ValueError("Only fresh provider-confirmed daily candles are allowed.")
        bars = response.get("bars")
        if not isinstance(bars, list):
            raise ValueError("Missing real daily bars.")
        # Exclude even a possibly completed current-day bar. That prevents
        # turning a still-forming provider candle into a hypothetical fill.
        completed = [b for b in bars
                     if datetime.fromtimestamp(int(b["time"]), NY).date()
                     < at.astimezone(NY).date()]
        if not completed:
            raise ValueError("No completed observed daily bars.")
        histories[symbol] = {**response, "bars": completed}
    latest = [datetime.fromtimestamp(int(histories[s]["bars"][-1]["time"]), NY)
              .date().isoformat() for s in symbols]
    if len(set(latest)) != 1:
        raise ValueError("Portfolio instruments do not share the latest completed session.")
    age = (at.astimezone(NY).date() - datetime.fromisoformat(latest[0]).date()).days
    if not 1 <= age <= 5:
        raise ValueError("Latest completed portfolio session is stale.")
    # For the recent observation window require synchronized member dates,
    # rather than silently treating a missing asset bar as a non-trading day.
    recent = [set(datetime.fromtimestamp(int(b["time"]), NY).date().isoformat()
                  for b in histories[s]["bars"][-35:]) for s in symbols]
    latest_common = set.intersection(*recent)
    if any((dates - latest_common) for dates in recent):
        raise ValueError("Missing or unmatched member session in recent observations.")
    days, market, metadata, _ = pr._prepare(symbols, histories)
    if days[-1] != latest[0]:
        raise ValueError("Portfolio has missing common-session candles.")
    return days, market, metadata


def _weights(config, symbols, closes, meta, i):
    model = config["model"]
    maximum = float(config["max_position_pct"]) / 100.
    if model == "blended_portfolio":
        return blended.blend_weights(
            config["sleeves"], symbols, closes, i, meta, maximum,
            float(config.get("target_investment_pct", 95)) / 100.,
            float(config.get("equity_class_cap_pct", 70)) / 100.,
            bool(config.get("redistribute_excess", False)))
    if model in pr.MODELS:
        return pr._weights(
            model, symbols, closes, i, meta, maximum,
            gross_target=float(config.get("target_investment_pct", 95)) / 100.,
            equity_cap=float(config.get("equity_class_cap_pct", 70)) / 100.,
            redistribute=bool(config.get("redistribute_excess", False)))
    if model in adv.MODELS:
        return adv.weights(model, symbols, closes, i, meta, maximum)
    raise ValueError("Frozen strategy model is unsupported.")


def _safe_targets(config, symbols, closes, meta, length):
    targets = _weights(config, symbols, closes, meta, length)
    if set(targets) != set(symbols):
        raise ValueError("Incomplete model allocation.")
    max_each = float(config["max_position_pct"]) / 100.
    for weight in targets.values():
        if not isinstance(weight, (int, float)) or not math.isfinite(weight):
            raise ValueError("Nonfinite model allocation.")
        if abs(weight) > max_each + 1e-7:
            raise ValueError("Allocation breaches frozen position limit.")
    gross = sum(abs(x) for x in targets.values())
    if gross > 1.5 + 1e-7 or (any(v < 0 for v in targets.values())
                             and config["model"] not in adv.SHORT_MODELS):
        raise ValueError("Unsupported signed or leveraged allocation.")
    if config["model"] not in adv.RESEARCH_ONLY and gross > 1. + 1e-7:
        raise ValueError("Unleveraged model exceeds available capital.")
    return {s: float(targets[s]) for s in symbols}


def _public(row, details=False):
    obj = dict(row)
    config = json.loads(obj["config"])
    state = json.loads(obj["state"])
    audit = json.loads(obj["audit_reference"])
    result = {
        "id":obj["id"], "source_job_id":obj["source_job"],
        "created_at":obj["created_at"], "updated_at":obj["updated_at"],
        "status":obj["status"], "model":config["model"],
        "symbols":json.loads(obj["symbols"]),
        "initial_capital":obj["capital"], "max_drawdown_pct":obj["max_drawdown"],
        "starting_session":obj["starting_session"], "last_session":obj["last_session"],
        "observed_sessions":state["observed_sessions"],
        "last_error":obj["last_error"], "research_only":True,
        "simulated_fills_only":True,
        "cash":round(state["cash"],2), "equity":round(state["equity"],2),
        "positions":state["positions"],
        "peak_equity":round(state["peak"],2),
        "gross_exposure_pct":round(state["gross_pct"],2),
        "current_drawdown_pct":round((state["equity"]/state["peak"]-1)*100,3),
        "financing_paid":round(state["financing_paid"],2),
        "transaction_fees_paid":round(state["transaction_fees_paid"],2),
        "pending_execution":state["pending"] is not None,
        "delay_sessions":config["delay_sessions"],
        "audit_reference":audit,
    }
    if details:
        with closing(_db()) as c:
            marks = [dict(x) for x in c.execute(
                "SELECT session,value,cash,gross_pct,drawdown_pct,financing_cost "
                "FROM paper_marks WHERE study_id=? ORDER BY session",(obj["id"],))]
            fills = [dict(x) for x in c.execute(
                "SELECT session,symbol,action,quantity,price,fee,delay_sessions "
                "FROM paper_fills WHERE study_id=? ORDER BY session,symbol,id",(obj["id"],))]
        curve = [{"time":int(datetime.fromisoformat(m["session"]).replace(
                  tzinfo=timezone.utc).timestamp()),"value":m["value"]} for m in marks]
        # Session count excludes the initial zero-return activation mark.
        stats = metrics.performance(curve, starting_capital=obj["capital"],
                                    risk_free_pct=audit["risk_free_pct"])
        if state["observed_sessions"] < 30:
            # Short paper windows must not display extrapolated annual growth
            # or Sharpe as though they were established performance.
            stats={**stats,"cagr_pct":None,"excess_sharpe":None,
                   "annualized_volatility_pct":None}
        result.update(marks=marks, fills=fills, statistics=stats)
        if state["observed_sessions"] < 30:
            result["drift"]={"status":"insufficient_forward_sessions",
                            "cagr_gap_pct":None,"sharpe_gap":None}
        else:
            reference=audit["objectives"]
            result["drift"]={
                "status":"descriptive_not_predictive",
                "cagr_gap_pct":round(stats["cagr_pct"]-reference["cagr_pct"],3)
                    if stats["cagr_pct"] is not None and reference["cagr_pct"] is not None else None,
                "sharpe_gap":round(stats["excess_sharpe"]-reference["excess_sharpe"],3)
                    if stats["excess_sharpe"] is not None and reference["excess_sharpe"] is not None else None}
    return result


def list_studies():
    _private()
    with LOCK, closing(_db()) as c:
        return [_public(x) for x in c.execute(
            "SELECT * FROM paper_studies ORDER BY created_at DESC LIMIT 50")]


def get_study(study_id):
    _private()
    with LOCK, closing(_db()) as c:
        row = c.execute("SELECT * FROM paper_studies WHERE id=?",(study_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Forward-paper study not found.")
        return _public(row, details=True)


def create(job_id, *, capital=100000., max_drawdown_pct=30., now=None, loader=None):
    _private()
    if (not isinstance(capital, (int,float)) or isinstance(capital,bool)
        or not math.isfinite(capital) or not 100<=capital<=1e9
        or not isinstance(max_drawdown_pct,(int,float)) or isinstance(max_drawdown_pct,bool)
        or not math.isfinite(max_drawdown_pct) or not 5<=max_drawdown_pct<=60):
        raise HTTPException(422,"Invalid forward-paper capital or risk limit.")
    job = walkforward_queue.get_job(job_id)
    result = job.get("result") or {}
    if job["status"] != "completed" or result.get("status") != "completed":
        raise HTTPException(409,"Only completed walk-forward selections can start forward-paper monitoring.")
    audit = result["final_audit"]
    config = audit["selected"]
    symbols = result["symbols"]
    if not 2 <= len(symbols) <= 16 or len(set(symbols)) != len(symbols):
        raise HTTPException(422,"Invalid frozen portfolio.")
    if not config.get("model") or not isinstance(config.get("delay_sessions"),int):
        raise HTTPException(422,"Invalid frozen selection.")
    at = _now(now)
    try:
        days, market, meta = _portfolio(symbols, at, loader)
        closes = {s:[b["close"] for b in market[s]] for s in symbols}
        targets = _safe_targets(config, symbols, closes, meta, len(days))
    except (ValueError,KeyError,TypeError,HTTPException) as exc:
        raise HTTPException(422,"Forward-paper initialization requires fresh synchronized real data and a valid frozen model.") from exc
    audit_reference={"objectives":audit["objectives"],
                     "risk_free_pct":float(result["targets"]["risk_free_pct"])}
    start = days[-1]
    pending={"weights":targets,"remaining":config["delay_sessions"],"signal_session":start}
    state={"cash":float(capital),"equity":float(capital),
           "positions":{s:0 for s in symbols}, "peak":float(capital),
           "gross_pct":0., "observed_sessions":0,
           "pending":pending, "since_signal":0,
           "financing_paid":0.,"transaction_fees_paid":0.}
    with LOCK, closing(_db()) as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT COUNT(*) FROM paper_studies").fetchone()[0]>=MAX_STUDIES:
            raise HTTPException(409,"Forward-paper study limit reached.")
        existing = c.execute("SELECT * FROM paper_studies WHERE source_job=?",
                             (job_id,)).fetchone()
        if existing and existing["status"] == "active":
            c.commit()
            return _public(existing)
        uid = str(uuid4())
        c.execute("""INSERT INTO paper_studies(
            id,source_job,created_at,updated_at,status,config,symbols,capital,
            max_drawdown,starting_session,last_session,state,audit_reference,last_error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid,job_id,at.isoformat(),at.isoformat(),"active",_dump(config),
             _dump(symbols),capital,max_drawdown_pct,start,start,_dump(state),
             _dump(audit_reference),None))
        c.execute("INSERT INTO paper_marks VALUES(?,?,?,?,?,?,?)",
                  (uid,start,capital,capital,0.,0.,0.))
        c.commit()
        return _public(c.execute("SELECT * FROM paper_studies WHERE id=?",(uid,)).fetchone())


def change_status(study_id, status):
    _private()
    if status not in ("active","paused","retired"):
        raise HTTPException(422,"Invalid paper monitoring state.")
    with LOCK, closing(_db()) as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM paper_studies WHERE id=?",(study_id,)).fetchone()
        if row is None:
            raise HTTPException(404,"Forward-paper study not found.")
        if row["status"] == "retired" or (status == "active" and row["status"] != "active"):
            raise HTTPException(409,"A paused paper study cannot resume with a hidden observation gap. Start a fresh paper study.")
        # Do not silently skip sessions while paused and later call the
        # resulting history continuous forward evidence.
        c.execute("UPDATE paper_studies SET status=?,updated_at=? WHERE id=?",
                  (status,_now().isoformat(),study_id))
        c.commit()
        return _public(c.execute("SELECT * FROM paper_studies WHERE id=?",(study_id,)).fetchone())


def _fill(state, config, meta, symbols, today, opens):
    target=state["pending"]["weights"]
    signed = config["model"] in adv.RESEARCH_ONLY
    equity_at_open = state["cash"] + sum(state["positions"][s]*opens[s] for s in symbols)
    if equity_at_open <= 0 or not math.isfinite(equity_at_open):
        raise PaperRiskError("Paper portfolio capital exhausted.")
    slippage=8.  # model-independent conservative research default
    fees=[]
    desired={s:math.trunc(equity_at_open*target[s]/opens[s]) for s in symbols}
    for side in ("sell","buy"):
        for symbol in symbols:
            delta=desired[symbol]-state["positions"][symbol]
            if side=="sell" and delta>=0 or side=="buy" and delta<=0:
                continue
            price=opens[symbol]*(1+(1 if delta>0 else -1)*
                (float(meta[symbol]["spread_bps"])/2.+slippage)/10000.)
            if delta>0 and not signed:
                delta=min(delta,max(0,math.floor((state["cash"]-0.)/price)))
            if delta==0:continue
            before=state["positions"][symbol]
            state["positions"][symbol]+=delta
            state["cash"]-=delta*price
            action=("short_sell" if delta<0 and state["positions"][symbol]<0
                    else "cover" if delta>0 and before<0
                    else "buy" if delta>0 else "sell")
            fees.append((symbol,action,abs(delta),price,0.))
    state["pending"]=None
    return fees


def _advance(c, row, days, market, meta, at):
    symbols=json.loads(row["symbols"])
    config=json.loads(row["config"])
    state=json.loads(row["state"])
    if row["last_session"] not in days:
        raise ValueError("Previous observed paper session missing from source.")
    offset=days.index(row["last_session"])
    # Reconstructing several opens after downtime would turn a live forward
    # observation into hindsight backtesting. End the continuous study.
    if len(days) - offset - 1 > 1:
        raise PaperContinuityError("Missed daily paper-observation checkpoint.")
    pending_orders=[]
    for index in range(offset+1,len(days)):
        day=days[index]
        opens={s:market[s][index]["open"] for s in symbols}
        closes={s:market[s][index]["close"] for s in symbols}
        next_session=state["observed_sessions"]+1
        if state["pending"] is not None:
            state["pending"]["remaining"]-=1
            if state["pending"]["remaining"]==0:
                pending_orders=_fill(state,config,meta,symbols,day,opens)
            else:
                pending_orders=[]
        else:
            pending_orders=[]
        shorts=sum(max(0,-state["positions"][s])*closes[s] for s in symbols)
        margin=max(0.,-state["cash"])
        finance=(shorts*BORROW_RATE+margin*MARGIN_RATE)/252
        state["cash"]-=finance
        state["financing_paid"]+=finance
        state["equity"]=state["cash"]+sum(state["positions"][s]*closes[s] for s in symbols)
        if state["equity"]<=0 or not math.isfinite(state["equity"]):
            raise PaperRiskError("Forward-paper equity exhausted; review exposure.")
        state["peak"]=max(state["peak"],state["equity"])
        gross=sum(abs(state["positions"][s]*closes[s]) for s in symbols)
        state["gross_pct"]=100*gross/state["equity"]
        drawdown=(state["equity"]/state["peak"]-1)*100
        if gross > 0 and state["equity"]/gross < MAINTENANCE:
            raise PaperRiskError("Margin maintenance floor breached; no future paper execution.")
        # Everything for this day is committed atomically with the state.
        for symbol,action,quantity,price,fee in pending_orders:
            c.execute("INSERT INTO paper_fills VALUES(?,?,?,?,?,?,?,?,?,1)",
                      (str(uuid4()),row["id"],day,symbol,action,quantity,price,fee,
                       config["delay_sessions"]))
        c.execute("INSERT INTO paper_marks VALUES(?,?,?,?,?,?,?)",
                  (row["id"],day,state["equity"],state["cash"],state["gross_pct"],
                   drawdown,finance))
        state["observed_sessions"]=next_session
        row=dict(row)
        row["last_session"]=day
        state["since_signal"]+=1
        if drawdown <= -float(row["max_drawdown"]):
            row["status"]="paused"
            row["last_error"]="Paper drawdown stop reached. Inspect the paper ledger."
            break
        if state["since_signal"]>=REBALANCE and state["pending"] is None:
            known={s:[b["close"] for b in market[s][:index+1]] for s in symbols}
            state["pending"]={"weights":_safe_targets(config,symbols,known,meta,index+1),
                              "remaining":config["delay_sessions"],
                              "signal_session":day}
            state["since_signal"]=0
    if row["status"] == "active":
        row["last_error"] = None
    c.execute("""UPDATE paper_studies SET status=?,last_session=?,state=?,
                 last_error=?,updated_at=? WHERE id=?""",
              (row["status"],row["last_session"],_dump(state),row["last_error"],
               at.isoformat(),row["id"]))


def process_one(study_id, *, now=None, loader=None):
    """Idempotent incremental observation; no historical rows from before start."""
    _private()
    at=_now(now)
    with LOCK, closing(_db()) as c:
        row=c.execute("SELECT * FROM paper_studies WHERE id=?",(study_id,)).fetchone()
        if row is None:
            raise HTTPException(404,"Forward-paper study not found.")
        if row["status"] != "active":
            return _public(row)
        symbols=json.loads(row["symbols"])
        try:
            days, market, meta = _portfolio(symbols, at, loader)
            if any(day > row["last_session"] for day in days):
                c.execute("BEGIN IMMEDIATE")
                # The caller and live worker can run concurrently: re-read
                # state under the SQLite write lock before applying any bar.
                current=c.execute("SELECT * FROM paper_studies WHERE id=?",(study_id,)).fetchone()
                if current["status"]=="active":
                    _advance(c,current,days,market,meta,at)
                c.commit()
            else:
                c.execute("UPDATE paper_studies SET last_error=NULL WHERE id=?",(study_id,))
        except (ValueError,TypeError,KeyError,HTTPException,ZeroDivisionError) as exc:
            c.rollback()
            # Fail closed and retain already committed observed sessions.
            broken = isinstance(exc, (PaperContinuityError, PaperRiskError))
            c.execute("UPDATE paper_studies SET status=?,last_error=?,updated_at=? WHERE id=?",
                      ("paused" if broken else "active",
                       "Paper observation stopped ("+type(exc).__name__+")."
                       if broken else "Paper data check failed ("+type(exc).__name__+").",
                       at.isoformat(),study_id))
        return _public(c.execute("SELECT * FROM paper_studies WHERE id=?",(study_id,)).fetchone())


def process_all(*, now=None, loader=None):
    _private()
    with LOCK, closing(_db()) as c:
        ids=[r[0] for r in c.execute(
            "SELECT id FROM paper_studies WHERE status='active'")]
    return [process_one(uid,now=now,loader=loader) for uid in ids]
