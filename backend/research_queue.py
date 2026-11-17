"""Durable laptop-only research queue served through the authenticated private API.

Website requests are small configurations; the Windows background worker
downloads historical candles, runs portfolio models, and persists results.
Nothing is queued on Vercel, and website navigation never kills jobs.
"""
from __future__ import annotations

import json
from contextlib import closing
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException

from . import portfolio_research

DB_PATH = Path(os.environ.get(
    "TRADING_SIM_RESEARCH_QUEUE_DB",
    Path(__file__).resolve().parents[1] / "data" / "research_queue.sqlite3",
))
LOCK = RLock()
MAX_PENDING = 20
MAX_STORED = 300
LEASE_TIMEOUT_MINUTES = 30
STATUSES = ("queued", "running", "completed", "failed", "cancelled")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS research_jobs(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind='portfolio_comparison'),
        params TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')),
        progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL,
        result_run_id TEXT,
        error_code TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        started_at TEXT, finished_at TEXT, attempt INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS research_jobs_order ON research_jobs(status, created_at)")
    return conn


def _public(row):
    data=dict(row)
    params=json.loads(data.pop("params"))
    return {
        "id":data["id"], "kind":data["kind"], "status":data["status"],
        "symbols":params["symbols"],
        "max_drawdown_pct":params["max_drawdown_pct"],
        "max_position_pct":params["max_position_pct"],
        "progress":data["progress"], "stage":data["stage"],
        "result_run_id":data["result_run_id"],
        "error_code":data["error_code"],
        "created_at":data["created_at"], "updated_at":data["updated_at"],
        "started_at":data["started_at"], "finished_at":data["finished_at"],
    }


def enqueue(symbols: list[str], max_drawdown_pct: float = 25.,
            max_position_pct: float = 35.):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1":
        raise HTTPException(403, "Private research queue is unavailable in demo mode.")
    # Same strict basket and numeric constraints as the synchronous optimizer.
    basket=portfolio_research._validate_basket(symbols)
    if (not math.isfinite(max_drawdown_pct) or not 1<=max_drawdown_pct<=50 or
        not math.isfinite(max_position_pct) or not 5<=max_position_pct<=50):
        raise HTTPException(422, "Invalid portfolio research risk limits.")
    params={"symbols":basket,"max_drawdown_pct":max_drawdown_pct,
            "max_position_pct":max_position_pct}
    moment=_now()
    with LOCK:
        with closing(_connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            active=conn.execute("SELECT COUNT(*) FROM research_jobs WHERE status IN ('queued','running')").fetchone()[0]
            if active>=MAX_PENDING:
                raise HTTPException(429, "Research queue is full. Wait for existing jobs to complete.")
            # Do not silently delete user research or queue history; require
            # conscious cleanup if maximum retained jobs is reached.
            stored=conn.execute("SELECT COUNT(*) FROM research_jobs").fetchone()[0]
            if stored>=MAX_STORED:
                raise HTTPException(409, "Research job history is full. Archive old history locally.")
            job_id=str(uuid4())
            conn.execute("""INSERT INTO research_jobs
                (id,kind,params,status,progress,stage,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (job_id,"portfolio_comparison",json.dumps(params),"queued",0,"Waiting for laptop research worker",moment,moment))
            job=conn.execute("SELECT * FROM research_jobs WHERE id=?",(job_id,)).fetchone()
            return _public(job)


def list_jobs(limit: int = 50):
    with LOCK:
        with closing(_connect()) as conn, conn:
            rows=conn.execute(
                "SELECT * FROM research_jobs ORDER BY created_at DESC LIMIT ?", (min(max(limit,1),100),)
            ).fetchall()
            return [_public(x) for x in rows]


def get_job(job_id: str):
    with LOCK:
        with closing(_connect()) as conn, conn:
            row=conn.execute("SELECT * FROM research_jobs WHERE id=?",(job_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Research job not found.")
            return _public(row)


def cancel(job_id: str):
    with LOCK:
        with closing(_connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            job=conn.execute("SELECT * FROM research_jobs WHERE id=?",(job_id,)).fetchone()
            if job is None:
                raise HTTPException(404, "Research job not found.")
            if job["status"] in ("queued","running"):
                moment=_now()
                conn.execute("""UPDATE research_jobs SET status='cancelled',stage='Cancelled',
                    updated_at=?,finished_at=? WHERE id=? AND status IN ('queued','running')""",
                    (moment,moment,job_id))
            return _public(conn.execute("SELECT * FROM research_jobs WHERE id=?",(job_id,)).fetchone())


class JobCancelled(Exception):
    pass


def _is_cancelled(job_id):
    with closing(_connect()) as conn, conn:
        row=conn.execute("SELECT status FROM research_jobs WHERE id=?",(job_id,)).fetchone()
        return row is None or row["status"]=="cancelled"


def _progress(job_id, percent, stage):
    if _is_cancelled(job_id):
        raise JobCancelled()
    with closing(_connect()) as conn, conn:
        conn.execute("""UPDATE research_jobs SET progress=?,stage=?,updated_at=?
                     WHERE id=? AND status='running'""",
                     (max(0,min(99,int(percent))),stage[:100],_now(),job_id))
    if _is_cancelled(job_id):
        raise JobCancelled()


def _claim_next():
    with LOCK:
        with closing(_connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            # A worker crash / PC shutdown makes RUNNING jobs recoverable.
            # If its original result already persisted, process_one will link
            # it instead of recomputing that experiment.
            old=(datetime.now(timezone.utc)-timedelta(minutes=LEASE_TIMEOUT_MINUTES)).isoformat()
            conn.execute("""UPDATE research_jobs SET status='queued',
                  stage='Recovered after interrupted worker',progress=0,updated_at=?
                  WHERE status='running' AND updated_at<?""",(_now(),old))
            row=conn.execute("SELECT * FROM research_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return None
            moment=_now()
            conn.execute("""UPDATE research_jobs SET status='running',
                stage='Preparing historical data',progress=1,attempt=attempt+1,
                started_at=COALESCE(started_at,?),updated_at=?
                WHERE id=? AND status='queued'""",(moment,moment,row["id"]))
            return _public(conn.execute("SELECT * FROM research_jobs WHERE id=?",(row["id"],)).fetchone())


def _finish(job_id, status, stage, result=None, code=None):
    with LOCK:
        with closing(_connect()) as conn, conn:
            conn.execute("""UPDATE research_jobs SET status=?,progress=?,stage=?,
               result_run_id=?,error_code=?,finished_at=?,updated_at=?
               WHERE id=? AND status='running'""",
               (status,100 if status=="completed" else 0,stage,result,code,_now(),_now(),job_id))
    return get_job(job_id)


def process_one():
    """Process at most one queued research study, from a laptop worker only."""
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1":
        raise RuntimeError("Research worker must not run in public demo.")
    job=_claim_next()
    if job is None:
        return None
    job_id=job["id"]
    try:
        if _is_cancelled(job_id):
            return get_job(job_id)
        try:
            # A previous worker may have died after persisting the result
            # but before updating the queue. The UUID is shared deliberately.
            portfolio_research.load_run(job_id)
        except HTTPException as exc:
            if exc.status_code!=404:
                raise
        else:
            return _finish(job_id,"completed","Completed",result=job_id)
        def update(progress:int, stage:str):
            _progress(job_id,progress,stage)
        portfolio_research.compare(
            job["symbols"], max_drawdown_pct=job["max_drawdown_pct"],
            max_position_pct=job["max_position_pct"], run_id=job_id,
            progress=update, cancelled=lambda: _is_cancelled(job_id),
        )
        if _is_cancelled(job_id):
            return get_job(job_id)
        return _finish(job_id,"completed","Completed",result=job_id)
    except JobCancelled:
        return get_job(job_id)
    except Exception as exc:
        # Never persist exception messages. Providers can include private URLs,
        # ticker requests, account identifiers or strategy details.
        return _finish(job_id,"failed","Research failed",code=type(exc).__name__)
