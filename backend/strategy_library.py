"""Persist reusable, independently validated trading strategies across sessions.

Named saves and immutable auto-snapshots live in the local SQLite library,
separate from portfolio and single-asset replay state. Reading a strategy
never activates it; changing code in the editor is explicitly user-driven.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException

from .arcade_dsl import compile_rules
from .portfolio_dsl import compile_portfolio_rules

DB_PATH = Path(os.environ.get(
    "TRADING_SIM_STRATEGY_DB",
    Path(__file__).resolve().parent.parent / "data" / "strategy_library.sqlite3",
))
LOCK = RLock()
MAX_STRATEGIES = 500


def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS saved_strategies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('single','portfolio')),
        code TEXT NOT NULL,
        symbols TEXT NOT NULL,
        source_run_id TEXT,
        source TEXT NOT NULL CHECK(source IN ('manual','activated')),
        created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS saved_strategies_mode ON saved_strategies(mode,created_at)")
    return db


def validate(mode: str, code: str, symbols: list[str]):
    if mode not in ("single", "portfolio"):
        raise HTTPException(422, detail="Invalid strategy mode.")
    if not isinstance(code, str) or not code.strip():
        raise HTTPException(422, detail="Strategy code cannot be empty.")
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 16 or any(
        not isinstance(s, str) or len(s) > 50 or not s for s in symbols
    ):
        raise HTTPException(422, detail="Invalid strategy symbols.")
    if mode == "single":
        if len(symbols) != 1:
            raise HTTPException(422, detail="Single strategy requires one instrument.")
        rules = compile_rules(code)
    else:
        if len(symbols) < 2:
            raise HTTPException(422, detail="Portfolio strategy requires a basket.")
        rules = compile_portfolio_rules(code, set(symbols))
    if not rules:
        raise HTTPException(422, detail="Save at least one valid rule.")


def store(mode: str, name: str, code: str, symbols: list[str],
          source_run_id: str | None = None, source: str = "manual"):
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= 80:
        raise HTTPException(422, detail="Strategy name must be 1-80 characters.")
    if len(code) > 1800:
        raise HTTPException(422, detail="Strategy cannot exceed 1800 characters.")
    validate(mode, code, symbols)
    if source not in ("manual", "activated"):
        raise HTTPException(422, detail="Invalid strategy source.")
    now = datetime.now(timezone.utc).isoformat()
    identifier = str(uuid4())
    with LOCK, closing(connection()) as db, db:
        total = db.execute("SELECT COUNT(*) FROM saved_strategies").fetchone()[0]
        if total >= MAX_STRATEGIES:
            raise HTTPException(409, detail="Strategy library is full (500 versions). Delete unused entries.")
        db.execute(
            "INSERT INTO saved_strategies VALUES (?,?,?,?,?,?,?,?)",
            (identifier, cleaned, mode, code.strip(), ",".join(symbols),
             source_run_id, source, now),
        )
    return get(identifier)


def get(strategy_id: str):
    with LOCK, closing(connection()) as db:
        record = db.execute("SELECT * FROM saved_strategies WHERE id=?", (strategy_id,)).fetchone()
    if record is None:
        raise HTTPException(404, detail="Saved strategy does not exist.")
    result = dict(record)
    result["symbols"] = result["symbols"].split(",")
    return result


def list_saved(mode: str | None = None):
    if mode is not None and mode not in ("single", "portfolio"):
        raise HTTPException(422, detail="Invalid strategy mode.")
    with LOCK, closing(connection()) as db:
        rows = (db.execute("SELECT * FROM saved_strategies WHERE mode=? ORDER BY created_at DESC", (mode,))
                if mode else db.execute("SELECT * FROM saved_strategies ORDER BY created_at DESC")).fetchall()
    return [{**dict(row), "symbols":row["symbols"].split(",")} for row in rows]


def delete(strategy_id: str):
    with LOCK, closing(connection()) as db, db:
        result = db.execute("DELETE FROM saved_strategies WHERE id=?", (strategy_id,))
        if not result.rowcount:
            raise HTTPException(404, detail="Saved strategy does not exist.")
    return {"deleted": True, "id": strategy_id}


def capture(mode: str, code: str, symbols: list[str], run_id: str):
    """Noncritical archival when a strategy is explicitly activated.

    Avoid duplicates for an unchanged code version within the same session;
    never let a full/unavailable library prevent ordinary trading.
    """
    if not code.strip():
        return
    with LOCK, closing(connection()) as db:
        prior = db.execute(
            "SELECT code FROM saved_strategies WHERE mode=? AND source_run_id=? "
            "AND source='activated' ORDER BY created_at DESC LIMIT 1",
            (mode, run_id),
        ).fetchone()
        if prior and prior["code"] == code.strip():
            return
    short = ",".join(symbols)
    store(mode, "Activated " + short + " · " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
          code, symbols, run_id, "activated")
