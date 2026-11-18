"""Private, durable local worker queue for rolling walk-forward optimization."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
import json,os,sqlite3
from fastapi import HTTPException
from . import walkforward_optimizer as engine

ROOT=Path(__file__).resolve().parents[1]
DB_PATH=Path(os.environ.get("TRADING_SIM_WALKFORWARD_DB",ROOT/"data"/"walkforward_research.sqlite3"))
LOCK=RLock()
MAX_PENDING=2
MAX_STORED=100


def _connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=30,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS walkforward_jobs (
      id TEXT PRIMARY KEY,status TEXT NOT NULL,created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,
      stage TEXT NOT NULL,error_code TEXT,params TEXT NOT NULL,result TEXT)""")
    return c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _public(row,detail=False):
    d=dict(row)
    result=json.loads(d["result"]) if detail and d["result"] else None
    return {**{k:d[k] for k in
              ("id","status","created_at","updated_at","progress","stage","error_code")},
            "result":result}


def enqueue(payload):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,"Private research unavailable in public demos.")
    params=engine.validate_request(payload)
    with LOCK,closing(_connect()) as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT count(*) FROM walkforward_jobs WHERE status IN ('queued','running')").fetchone()[0]>=MAX_PENDING:
            raise HTTPException(429,"Too many walk-forward studies are already queued.")
        if c.execute("SELECT count(*) FROM walkforward_jobs").fetchone()[0]>=MAX_STORED:
            c.execute("DELETE FROM walkforward_jobs WHERE id IN "
                      "(SELECT id FROM walkforward_jobs WHERE status IN ('completed','failed','cancelled') "
                      "ORDER BY updated_at ASC LIMIT 20)")
        uid=str(uuid4());now=_now()
        c.execute("INSERT INTO walkforward_jobs(id,status,created_at,updated_at,stage,params) "
                  "VALUES(?,'queued',?,?,?,?)",
                  (uid,now,now,"Queued for private walk-forward evaluation",json.dumps(params)))
        c.commit()
        return _public(c.execute("SELECT * FROM walkforward_jobs WHERE id=?",(uid,)).fetchone())


def get_job(uid):
    with LOCK,closing(_connect()) as c:
        row=c.execute("SELECT * FROM walkforward_jobs WHERE id=?",(uid,)).fetchone()
    if row is None:raise HTTPException(404,"Walk-forward study not found.")
    return _public(row,True)


def list_jobs(limit=12):
    with LOCK,closing(_connect()) as c:
        return [_public(row) for row in c.execute(
            "SELECT * FROM walkforward_jobs ORDER BY created_at DESC LIMIT ?",
            (min(max(1,limit),30),))]


def cancel(uid):
    with LOCK,closing(_connect()) as c:
        c.execute("UPDATE walkforward_jobs SET status='cancelled',stage='Cancelled',updated_at=? "
                  "WHERE id=? AND status IN ('queued','running')",(_now(),uid))
    return get_job(uid)


def _report(uid,pct,stage):
    with LOCK,closing(_connect()) as c:
        c.execute("UPDATE walkforward_jobs SET progress=?,stage=?,updated_at=? "
                  "WHERE id=? AND status='running'",
                  (min(99,max(0,int(pct))),str(stage)[:120],_now(),uid))
        row=c.execute("SELECT status FROM walkforward_jobs WHERE id=?",(uid,)).fetchone()
        if row is None or row["status"]!="running":
            raise InterruptedError("Walk-forward evaluation cancelled")


def process_one():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        return None
    with LOCK,closing(_connect()) as c:
        c.execute("BEGIN IMMEDIATE")
        stale=(datetime.now(timezone.utc)-timedelta(minutes=45)).isoformat()
        c.execute("UPDATE walkforward_jobs SET status='queued',stage='Recovering interrupted study' "
                  "WHERE status='running' AND updated_at<?",(stale,))
        row=c.execute("SELECT * FROM walkforward_jobs WHERE status='queued' "
                      "ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            c.commit()
            return None
        uid=row["id"]
        c.execute("UPDATE walkforward_jobs SET status='running',progress=1,"
                  "stage='Reading historical research archive',updated_at=? WHERE id=?",(_now(),uid))
        c.commit()
    try:
        output=engine.analyze(json.loads(row["params"]),report=lambda a,b:_report(uid,a,b))
        with LOCK,closing(_connect()) as c:
            c.execute("UPDATE walkforward_jobs SET status='completed',progress=100,"
                      "stage='Walk-forward evaluation complete',result=?,updated_at=? "
                      "WHERE id=? AND status='running'",
                      (json.dumps(output,allow_nan=False),_now(),uid))
            c.commit()
    except InterruptedError:
        return get_job(uid)
    except Exception as exc:
        # Never log or publish private model selections or generated params.
        with LOCK,closing(_connect()) as c:
            c.execute("UPDATE walkforward_jobs SET status='failed',"
                      "stage='Walk-forward evaluation failed',error_code=?,updated_at=? "
                      "WHERE id=? AND status='running'",
                      (type(exc).__name__,_now(),uid))
            c.commit()
    return get_job(uid)
