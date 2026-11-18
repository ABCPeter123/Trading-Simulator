"""Durable, private queue for bounded custom historical strategy evaluations."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
import json
import os
import sqlite3

from fastapi import HTTPException
from . import strategy_period_analysis as analysis

ROOT=Path(__file__).resolve().parents[1]
DB_PATH=Path(os.environ.get("TRADING_SIM_PERIOD_DB", ROOT/"data"/"strategy_period.sqlite3"))
LOCK=RLock()
MAX_PENDING=2
MAX_STORED=100


def _connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB_PATH,timeout=30,isolation_level=None)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS period_jobs (
        id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
        stage TEXT NOT NULL, error_code TEXT, params TEXT NOT NULL, result TEXT
    )""")
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def _public(row, detail=False):
    data=dict(row)
    return {**{k:data[k] for k in ("id","status","created_at","updated_at",
                                  "progress","stage","error_code")},
            "result":json.loads(data["result"]) if detail and data["result"] else None}


def enqueue(payload):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,"Private strategy analysis is disabled in public demos.")
    params=analysis.validate_request(payload)
    with LOCK,closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        count=conn.execute("SELECT COUNT(*) FROM period_jobs WHERE status IN ('queued','running')").fetchone()[0]
        if count>=MAX_PENDING:
            raise HTTPException(429,"Too many custom studies queued. Wait for a study to finish.")
        stored=conn.execute("SELECT COUNT(*) FROM period_jobs").fetchone()[0]
        if stored>=MAX_STORED:
            # Retain only a bounded private archive. Never remove running/queued jobs.
            conn.execute("DELETE FROM period_jobs WHERE id IN (SELECT id FROM period_jobs "
                         "WHERE status IN ('completed','failed','cancelled') "
                         "ORDER BY updated_at ASC LIMIT 20)")
        uid=str(uuid4());now=_now()
        conn.execute("INSERT INTO period_jobs (id,status,created_at,updated_at,stage,params) "
                     "VALUES (?,'queued',?,?,?,?)",
                     (uid,now,now,"Queued for local historical analysis",json.dumps(params)))
        conn.commit()
        return _public(conn.execute("SELECT * FROM period_jobs WHERE id=?",(uid,)).fetchone())


def get_job(uid):
    with LOCK,closing(_connect()) as conn:
        row=conn.execute("SELECT * FROM period_jobs WHERE id=?",(uid,)).fetchone()
    if not row:raise HTTPException(404,"Period study not found.")
    return _public(row,detail=True)


def cancel(uid):
    with LOCK,closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE period_jobs SET status='cancelled',stage='Cancelled',updated_at=? "
                     "WHERE id=? AND status IN ('queued','running')",(_now(),uid))
        conn.commit()
    return get_job(uid)


def _report(uid,pct,stage):
    with LOCK,closing(_connect()) as conn:
        conn.execute("UPDATE period_jobs SET progress=?,stage=?,updated_at=? "
                     "WHERE id=? AND status='running'",
                     (min(99,max(0,int(pct))),str(stage)[:120],_now(),uid))
        row=conn.execute("SELECT status FROM period_jobs WHERE id=?",(uid,)).fetchone()
        if row is None or row["status"]!="running":
            raise InterruptedError("Custom period study cancelled.")


def process_one():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        return None
    with LOCK,closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        stale=(datetime.now(timezone.utc)-timedelta(minutes=45)).isoformat()
        conn.execute("UPDATE period_jobs SET status='queued',stage='Resuming interrupted study' "
                     "WHERE status='running' AND updated_at<?",(stale,))
        row=conn.execute("SELECT * FROM period_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            conn.commit()
            return None
        uid=row["id"]
        conn.execute("UPDATE period_jobs SET status='running',progress=1,"
                     "stage='Preparing historical data',updated_at=? WHERE id=?",(_now(),uid))
        conn.commit()
    try:
        result=analysis.analyze(json.loads(row["params"]),report=lambda pct,stage:_report(uid,pct,stage))
        with LOCK,closing(_connect()) as conn:
            conn.execute("UPDATE period_jobs SET status='completed',progress=100,"
                         "stage='Historical analysis complete',result=?,updated_at=? "
                         "WHERE id=? AND status='running'",
                         (json.dumps(result,allow_nan=False),_now(),uid))
            conn.commit()
    except InterruptedError:
        return get_job(uid)
    except Exception as exc:
        # No strategy symbols, private parameters, execution records or exception details in logs.
        with LOCK,closing(_connect()) as conn:
            conn.execute("UPDATE period_jobs SET status='failed',stage='Historical analysis failed',"
                         "error_code=?,updated_at=? WHERE id=? AND status='running'",
                         (type(exc).__name__,_now(),uid))
            conn.commit()
    return get_job(uid)
