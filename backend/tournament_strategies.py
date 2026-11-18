"""Private immutable executable portfolio models promoted from completed tournaments.

The public repository contains only the interpreter and schema, never a user's
rankings, selected parameters or trades. Actual versions live in Git-ignored data/.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
import json
import math
import os
import sqlite3

from fastapi import HTTPException

from . import portfolio_research as pr, universe_research, advanced_portfolio_research as adv
from . import blended_portfolio_research as blends

DB_PATH = Path(os.environ.get("TRADING_SIM_TOURNAMENT_STRATEGIES_DB",
    Path(__file__).resolve().parents[1] / "data" / "tournament_strategies.sqlite3"))
LOCK = RLock()
MAX_SAVED = 300


def _private():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1":
        raise HTTPException(403, detail="Tournament strategies are unavailable in the public demo.")


def validate_spec(spec):
    """Decode an immutable model; fail closed rather than substitute a different rule."""
    if not isinstance(spec, dict) or spec.get("version") not in (1,2):
        raise HTTPException(422, detail="Unsupported tournament strategy version.")
    symbols = spec.get("symbols")
    if not isinstance(symbols, list) or not 2 <= len(symbols) <= 16 or len(set(
            str(s) for s in symbols)) != len(symbols):
        raise HTTPException(422, detail="Tournament model requires 2-16 distinct assets.")
    for s in symbols:
        if not isinstance(s, str) or not s or len(s) > 32 or not all(
                c.isascii() and (c.isalnum() or c in "._-") for c in s):
            raise HTTPException(422, detail="Invalid tournament model instrument.")
    blended=spec.get("model")=="blended_portfolio"
    advanced=spec.get("model") in adv.MODELS or blended
    if spec.get("model") not in pr.MODELS and not advanced:
        raise HTTPException(422, detail="Unsupported portfolio allocation model.")
    if blended:
        try:
            blends.validate_sleeves(spec.get("sleeves"))
        except (ValueError,TypeError) as exc:
            raise HTTPException(422,detail="Invalid blended portfolio sleeves.") from exc
    elif "sleeves" in spec:
        raise HTTPException(422,detail="Only blended portfolios may define sleeves.")
    if advanced != (spec["version"]==2):
        raise HTTPException(422, detail="Strategy model does not match its executable version.")
    if bool(spec.get("research_only",False)) != (spec.get("model") in adv.RESEARCH_ONLY or blended):
        raise HTTPException(422, detail="Incorrect research-only capability setting.")
    weight = spec.get("max_position_pct")
    if type(weight) not in (float,int) or not math.isfinite(weight) or not 10 <= weight <= 50:
        raise HTTPException(422, detail="Invalid tournament position cap.")
    if type(spec.get("delay_sessions")) is not int or spec["delay_sessions"] not in (1, 2):
        raise HTTPException(422, detail="Invalid tournament execution latency.")
    if spec.get("rebalance_sessions") != pr.REBALANCE_SESSIONS:
        raise HTTPException(422, detail="Unsupported tournament rebalance cadence.")
    keys=("target_investment_pct","equity_class_cap_pct","redistribute_excess")
    if any(k in spec for k in keys):
        if advanced and not blended:
            raise HTTPException(422,detail="Advanced allocation models use their own exposure budgets.")
        investment=spec.get("target_investment_pct",95.)
        equity=spec.get("equity_class_cap_pct",70.)
        redistributed=spec.get("redistribute_excess",False)
        if (type(investment) not in (int,float) or not math.isfinite(investment)
            or not 5<=investment<=100 or type(equity) not in (int,float)
            or not math.isfinite(equity) or not 10<=equity<=100
            or type(redistributed) is not bool):
            raise HTTPException(422,detail="Invalid custom tournament model exposure controls.")
    # Optional settings are part of immutable historical provenance. They
    # cannot bypass research-only deployment restrictions.
    currency=spec.get("base_currency","USD")
    if currency not in ("USD","CAD"):
        raise HTTPException(422,detail="Invalid research funding currency.")
    for key,upper in (("slippage_bps",100.),("commission_usd",30.),
                      ("fx_conversion_bps",300.)):
        value=spec.get(key)
        if value is not None and (type(value) not in (int,float)
                                  or not math.isfinite(value) or not 0<=value<=upper):
            raise HTTPException(422,detail="Invalid immutable research execution setting.")
    return spec


def _connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS tournament_strategies(
        id TEXT PRIMARY KEY, source_job_id TEXT NOT NULL, source_rank INTEGER NOT NULL,
        name TEXT NOT NULL, spec TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(source_job_id,source_rank)
    )""")
    return db


def _public(row):
    d = dict(row)
    spec = validate_spec(json.loads(d.pop("spec")))
    return {**d, "mode": "portfolio_model", "version":spec["version"],
            "symbols": spec["symbols"],
            "model": spec["model"], "max_position_pct": spec["max_position_pct"],
            "sleeves":spec.get("sleeves"),"base_currency":spec.get("base_currency","USD"),
            "slippage_bps":spec.get("slippage_bps",8.),
            "commission_usd":spec.get("commission_usd",0.),
            "fx_conversion_bps":spec.get("fx_conversion_bps",150.),
            "delay_sessions": spec["delay_sessions"], "rebalance_sessions": spec["rebalance_sessions"],
            "restricted_research": spec.get("restricted_research", False),
            "short_proxy_research": spec.get("short_proxy_research", False),
            "research_only":spec.get("research_only",False),
            "target_investment_pct":spec.get("target_investment_pct",95.),
            "equity_class_cap_pct":spec.get("equity_class_cap_pct",70.),
            "redistribute_excess":spec.get("redistribute_excess",False),
            "code": json.dumps(spec, sort_keys=True, separators=(",", ":"))}


def import_rank(job_id: str, rank: int):
    _private()
    if type(rank) is not int or not 1 <= rank <= 10:
        raise HTTPException(422, detail="Select a ranked strategy from 1 to 10.")
    study = universe_research.get_job(job_id)
    if study["status"] != "completed" or not study.get("result"):
        raise HTTPException(409, detail="Only completed tournament results can be imported.")
    winner = next((w for w in study["result"].get("top10", [])
                   if w.get("rank") == rank), None)
    if winner is None:
        raise HTTPException(404, detail="This tournament does not have that ranked strategy.")
    spec = validate_spec({
        "version": 2 if winner["model"] in adv.MODELS or winner["model"]=="blended_portfolio" else 1,
        "symbols": winner["symbols"],
        "model": winner["model"],
        **({"sleeves":winner["sleeves"]} if winner["model"]=="blended_portfolio" else {}),
        "max_position_pct": float(study["params"]["max_position_pct"]),
        "delay_sessions": int(study["params"]["delay_sessions"]),
        "rebalance_sessions": pr.REBALANCE_SESSIONS,
        "restricted_research": bool(winner.get("restricted_research", False)),
        "short_proxy_research": bool(winner.get("short_proxy_research", False)),
        "research_only":bool(winner.get("research_only",False)),
        "base_currency":study["params"].get("base_currency","USD"),
        "slippage_bps":float(study["params"].get("slippage_bps",8.)),
        "commission_usd":float(study["params"].get("commission_usd",0.)),
        "fx_conversion_bps":float(study["params"].get("fx_conversion_bps",150.)),
        **({"target_investment_pct":float(study["params"].get("target_investment_pct",95.)),
            "equity_class_cap_pct":float(study["params"].get("equity_class_cap_pct",70.)),
            "redistribute_excess":bool(study["params"].get("redistribute_excess",False))}
           if study["params"].get("research_objective")=="high_performance"
           and (winner["model"] in pr.MODELS or winner["model"]=="blended_portfolio") else {}),
    })
    with LOCK, closing(_connection()) as conn, conn:
        previous = conn.execute("SELECT * FROM tournament_strategies WHERE source_job_id=? "
                                "AND source_rank=?", (job_id,rank)).fetchone()
        if previous:
            return _public(previous)
        if conn.execute("SELECT COUNT(*) FROM tournament_strategies").fetchone()[0]>=MAX_SAVED:
            raise HTTPException(409, detail="Private tournament strategy library is full.")
        identifier="tm-"+str(uuid4())
        name=f"Tournament #{rank}: {winner['basket_type'].replace('_',' ')} / {winner['model'].replace('_',' ')}"
        conn.execute("INSERT INTO tournament_strategies VALUES(?,?,?,?,?,?)",
                     (identifier,job_id,rank,name,
                      json.dumps(spec, separators=(",", ":"),sort_keys=True),
                      datetime.now(timezone.utc).isoformat()))
        record=conn.execute("SELECT * FROM tournament_strategies WHERE id=?",(identifier,)).fetchone()
        return _public(record)


def get(strategy_id: str):
    _private()
    with LOCK, closing(_connection()) as conn:
        record=conn.execute("SELECT * FROM tournament_strategies WHERE id=?",(strategy_id,)).fetchone()
    if record is None:
        raise HTTPException(404, detail="Tournament strategy version not found.")
    return _public(record)


def list_saved():
    _private()
    with LOCK, closing(_connection()) as conn:
        records=conn.execute("SELECT * FROM tournament_strategies ORDER BY created_at DESC").fetchall()
        return [_public(x) for x in records]
