"""Multi-asset Trading Arcade: frozen, aligned daily OHLCV and shared cash.

Standalone table ensures all existing single-asset Arcade saves remain intact.
Provider data are downloaded before session creation and stay immutable for the
entire game. Only revealed bars leave the server. Missing sessions are NOT
forward-filled into tradable candles.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import RLock
from uuid import uuid4
import json
import os
import sqlite3
import zlib

from fastapi import HTTPException

from .arcade import execute, event, INITIAL_CASH
from .arcade_dsl import matches
from .assets import get_instrument
from .ledger import dec, positive_quantity
from .market import history
from .portfolio_dsl import compile_portfolio_rules

LOCK = RLock()
DB_PATH = Path(os.environ.get(
    "TRADING_SIM_ARCADE_DB",
    Path(__file__).resolve().parent.parent / "data" / "arcade.sqlite3",
))
MAX_SYMBOLS = 5
MAX_SKIP = 100


def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS portfolio_seasons (
        id TEXT PRIMARY KEY, basket TEXT NOT NULL, period TEXT NOT NULL,
        source TEXT NOT NULL, snapshot BLOB NOT NULL,
        state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    return db


def _date(bar):
    return datetime.fromtimestamp(int(bar["time"]), tz=timezone.utc).date().isoformat()


def _prepare(histories):
    """Normalize daily UTC dates; no missing-day bars are invented."""
    by_id = {}
    timeline = set()
    for asset_id, payload in histories.items():
        daily = {}
        previous = -1
        for original in payload["bars"]:
            bar = {k: original[k] for k in ("time", "open", "high", "low", "close", "volume")}
            t = int(bar["time"])
            if t <= previous or min(float(bar[k]) for k in ("open", "high", "low", "close")) <= 0:
                raise HTTPException(503, detail=f"Invalid or unsorted candles for {asset_id}.")
            if float(bar["high"]) < max(float(bar["open"]), float(bar["close"]), float(bar["low"])):
                raise HTTPException(503, detail=f"Invalid high in {asset_id}.")
            if float(bar["low"]) > min(float(bar["open"]), float(bar["close"]), float(bar["high"])):
                raise HTTPException(503, detail=f"Invalid low in {asset_id}.")
            previous = t
            daily[_date(bar)] = bar
        if len(daily) < 80:
            raise HTTPException(422, detail=f"{asset_id} has fewer than 80 usable daily candles.")
        by_id[asset_id] = daily
        timeline.update(daily)
    days = sorted(timeline)
    # No playable day until every symbol has 35 previous candles.
    seen = {asset_id: 0 for asset_id in by_id}
    first = None
    for idx, day in enumerate(days):
        for asset_id, available in by_id.items():
            if day in available:
                seen[asset_id] += 1
        if all(count >= 36 for count in seen.values()):
            first = idx
            break
    if first is None or len(days) - first < 45:
        raise HTTPException(422, detail="Insufficient overlapping market history for a multi-asset season.")
    return days, by_id, first


def _load(db, run_id):
    row = db.execute("SELECT * FROM portfolio_seasons WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, detail="Portfolio season does not exist.")
    snapshot = json.loads(zlib.decompress(row["snapshot"]).decode("utf-8"))
    state = json.loads(row["state"])
    return row, snapshot, state


def _save(db, run_id, state):
    db.execute("UPDATE portfolio_seasons SET state=?, updated_at=? WHERE id=?",
               (json.dumps(state), datetime.now(timezone.utc).isoformat(), run_id))


def create_season(symbols, period="5Y", starting_point=0.3, start_date=None):
    if not isinstance(symbols, list) or not 2 <= len(symbols) <= MAX_SYMBOLS:
        raise HTTPException(422, detail="Choose 2-5 assets for one shared-cash season.")
    if len(set(symbols)) != len(symbols):
        raise HTTPException(422, detail="Each instrument can appear only once.")
    if period not in {"1Y", "2Y", "5Y", "10Y", "MAX"} or not 0.15 <= starting_point <= 0.75:
        raise HTTPException(422, detail="Invalid season range or starting point.")
    instruments = [get_instrument(asset_id) for asset_id in symbols]
    if any(not i.tradable or i.currency != "USD" or i.kind not in ("Stocks", "ETFs", "Crypto") for i in instruments):
        raise HTTPException(422, detail="Multi-asset seasons currently support USD equities, ETFs and crypto only.")
    raw = {asset_id: history(asset_id, period) for asset_id in symbols}
    days, daily, warmup = _prepare(raw)
    index = min(len(days) - 2, max(warmup, int(len(days) * starting_point)))
    if start_date:
        try:
            day = datetime.strptime(start_date, "%Y-%m-%d").date().isoformat()
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail="Start date must be YYYY-MM-DD.") from exc
        index = max(warmup, next((idx for idx, d in enumerate(days) if d >= day), len(days)))
        if index >= len(days) - 1:
            raise HTTPException(422, detail="Selected start date has no remaining historical candles.")
    sources = {asset_id: raw[asset_id]["source"] for asset_id in symbols}
    snapshot = {"days": days, "daily": daily, "sources": sources}
    initial_positions = {asset_id: {"qty": "0", "avg": "0", "realized": "0"} for asset_id in symbols}
    state = {
        "index": index, "start_index": index, "cash": str(INITIAL_CASH),
        "positions": initial_positions, "orders": [], "fills": [],
        "strategy": "", "risk": {"stop_loss_pct": 0, "take_profit_pct": 0},
        "events": ["Multi-asset season started. No future candles are visible."],
        "curve": [{"day": days[index], "value": float(INITIAL_CASH)}],
    }
    compressed = zlib.compress(json.dumps(snapshot, separators=(",", ":")).encode("utf-8"), level=6)
    run_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with LOCK, closing(connection()) as db, db:
        db.execute("INSERT INTO portfolio_seasons VALUES (?,?,?,?,?,?,?,?)", (
            run_id, json.dumps(symbols), period, json.dumps(sources), compressed,
            json.dumps(state), now, now,
        ))
    return get_season(run_id)


def _mark(snapshot, state, asset_id, until_index):
    """Last revealed close only; never peek into upcoming sessions."""
    days, daily = snapshot["days"], snapshot["daily"][asset_id]
    for i in range(until_index, -1, -1):
        bar = daily.get(days[i])
        if bar is not None:
            return dec(bar["close"]), days[i]
    return None, None


def _equity(snapshot, state, index):
    cash = dec(state["cash"])
    positions = []
    exposure = Decimal(0)
    for asset_id, p in state["positions"].items():
        mark, mark_day = _mark(snapshot, state, asset_id, index)
        quantity, avg = dec(p["qty"]), dec(p["avg"])
        value = quantity * mark if mark is not None else Decimal(0)
        exposure += value
        positions.append({
            "asset_id": asset_id, "quantity": float(quantity), "average_cost": float(avg),
            "last_price": float(mark) if mark is not None else None,
            "mark_day": mark_day, "market_value": float(value),
            "unrealized_pnl": float(quantity * (mark - avg)) if mark is not None else None,
            "realized_pnl": float(dec(p["realized"])),
            "has_bar_today": snapshot["days"][index] in snapshot["daily"][asset_id],
        })
    return cash, exposure, positions


def public(run_id, row, snap, state):
    idx = state["index"]
    days = snap["days"]
    cash, exposure, positions = _equity(snap, state, idx)
    equity = cash + exposure
    ret = float((equity / INITIAL_CASH - 1) * 100)
    peak = float(INITIAL_CASH)
    drawdown = 0.0
    for sample in state["curve"]:
        peak = max(peak, sample["value"])
        drawdown = min(drawdown, (sample["value"] / peak - 1) * 100)
    xp = (idx-state["start_index"]) + 25*len(state["fills"]) + (50 if state["strategy"].strip() else 0)
    # Equal-weight buy-and-hold from session start, only marked using revealed
    # prices. No claim of exact replication with corporate actions/FX funding.
    hold = []
    for asset_id in json.loads(row["basket"]):
        start, _ = _mark(snap, state, asset_id, state["start_index"])
        current, _ = _mark(snap, state, asset_id, idx)
        if start is not None and current is not None:
            hold.append(float((current/start-1)*100))
    baseline = sum(hold)/len(hold) if hold else 0
    score = max(0, round(500 + (ret-baseline)*12 + drawdown*6))
    badges = []
    if state["fills"]:
        badges.append("First trade")
    if len({fill["asset_id"] for fill in state["fills"]}) >= 2:
        badges.append("Diversified trader")
    if state["strategy"].strip():
        badges.append("Cross-asset bot")
    if ret > baseline and state["fills"]:
        badges.append("Beat the benchmark")
    if idx == len(days)-1:
        badges.append("Season complete")
    visible = {}
    for asset_id in json.loads(row["basket"]):
        visible[asset_id] = [snap["daily"][asset_id][day] for day in days[:idx+1]
                             if day in snap["daily"][asset_id]]
    return {
        "id": run_id, "asset_ids": json.loads(row["basket"]),
        "period": row["period"], "sources": snap["sources"],
        "day": days[idx], "current_step": idx, "total_steps": len(days),
        "progress_pct": round(100*idx/(len(days)-1), 1),
        "finished": idx == len(days)-1, "bars": visible,
        "metrics": {
            "cash": float(cash), "exposure": float(exposure), "equity": float(equity),
            "return_pct": ret, "equal_weight_hold_pct": baseline,
            "max_drawdown_pct": drawdown, "xp": xp, "level": xp//125+1,
            "score": score, "badges": badges,
        }, "positions": positions,
        "orders": state["orders"], "fills": state["fills"][-60:][::-1],
        "events": state["events"], "strategy": state["strategy"], "risk": state["risk"],
        "curve": state["curve"], "updated_at": row["updated_at"],
        "execution_notice": "Shared USD cash and daily close marks. Trading is allowed only on a symbol's actual historical candle. Stale holdings use the last revealed close; no prices are synthesized. Fills use OHLC approximations.",
    }


def get_season(run_id):
    with LOCK, closing(connection()) as db:
        row, snap, state = _load(db, run_id)
        return public(run_id, row, snap, state)


def list_seasons():
    with LOCK, closing(connection()) as db:
        rows = db.execute(
            "SELECT id, basket, period, updated_at FROM portfolio_seasons ORDER BY updated_at DESC LIMIT 30"
        ).fetchall()
    return [
        {"id": r["id"], "asset_ids": json.loads(r["basket"]), "period": r["period"],
         "updated_at": r["updated_at"]} for r in rows
    ]


def order(run_id, asset_id, side, kind, size, size_type, price=None):
    if side not in ("buy", "sell") or kind not in ("market", "limit", "stop") or size_type not in ("percent", "units"):
        raise HTTPException(422, detail="Invalid order parameters.")
    amount = positive_quantity(size)
    if size_type == "percent" and amount > 100:
        raise HTTPException(422, detail="Percent sizing cannot exceed 100.")
    trigger = None if kind == "market" else dec(price)
    if trigger is not None and not 0 < trigger < 1_000_000_000:
        raise HTTPException(422, detail="Trigger must be positive.")
    with LOCK, closing(connection()) as db, db:
        row, snap, state = _load(db, run_id)
        if asset_id not in json.loads(row["basket"]):
            raise HTTPException(422, detail="Asset is not in this basket.")
        if state["index"] == len(snap["days"])-1:
            raise HTTPException(409, detail="Season has finished.")
        if len(state["orders"]) >= 40:
            raise HTTPException(409, detail="Maximum 40 pending orders.")
        asset = get_instrument(asset_id)
        if size_type == "units" and asset.kind in ("Stocks", "ETFs"):
            positive_quantity(size, whole=True)
        pos = state["positions"][asset_id]
        if side == "sell" and dec(pos["qty"]) <= 0 and not any(
            o["asset_id"] == asset_id and o["side"] == "buy" for o in state["orders"]
        ):
            raise HTTPException(409, detail="No holdings or queued buys for this symbol.")
        state["orders"].append({
            "id": str(uuid4()), "asset_id": asset_id, "side": side, "kind": kind,
            "size": str(amount), "size_type": size_type,
            "price": str(trigger) if trigger is not None else None,
            "source": "manual", "placed_step": state["index"],
        })
        event(state, f"Queued {side.upper()} on {asset_id}. Wait for this symbol's next candle.")
        _save(db, run_id, state)
        return public(run_id, row, snap, state)


def cancel(run_id, order_id):
    with LOCK, closing(connection()) as db, db:
        row, snap, state = _load(db, run_id)
        fresh = [o for o in state["orders"] if o["id"] != order_id]
        if len(fresh) == len(state["orders"]):
            raise HTTPException(404, detail="Pending order not found.")
        state["orders"] = fresh
        _save(db, run_id, state)
        return public(run_id, row, snap, state)


def strategy(run_id, code):
    with LOCK, closing(connection()) as db, db:
        row, snap, state = _load(db, run_id)
        rules = compile_portfolio_rules(code, set(json.loads(row["basket"])))
        state["strategy"] = code
        event(state, f"Cross-asset bot armed with {len(rules)} rules.")
        _save(db, run_id, state)
        return public(run_id, row, snap, state)


def risk(run_id, stop_loss_pct, take_profit_pct):
    if not 0 <= stop_loss_pct <= 75 or not 0 <= take_profit_pct <= 75:
        raise HTTPException(422, detail="Risk percentages must be 0-75.")
    with LOCK, closing(connection()) as db, db:
        row, snap, state = _load(db, run_id)
        state["risk"] = {"stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct}
        _save(db, run_id, state)
        return public(run_id, row, snap, state)


def _execute(state, asset_id, order_data, candle):
    pos = state["positions"][asset_id]
    instrument = get_instrument(asset_id)
    mini = {
        "cash": state["cash"], "qty": pos["qty"], "avg": pos["avg"],
        "realized": pos["realized"], "fills": [],
    }
    result = execute(mini, order_data, candle, instrument)
    if result.startswith("FILLED"):
        state["cash"] = mini["cash"]
        pos.update(qty=mini["qty"], avg=mini["avg"], realized=mini["realized"])
        state["fills"].extend({**fill, "asset_id": asset_id} for fill in mini["fills"])
    return result


def advance(run_id, count=1, until_action=False):
    if type(count) is not int or not 1 <= count <= MAX_SKIP:
        raise HTTPException(422, detail="Advance 1-100 calendar sessions.")
    with LOCK, closing(connection()) as db, db:
        row, snap, state = _load(db, run_id)
        ids = json.loads(row["basket"])
        days = snap["days"]
        bot_rules = compile_portfolio_rules(state["strategy"], set(ids))
        for _ in range(min(count, len(days)-1-state["index"])):
            next_idx = state["index"]+1
            day = days[next_idx]
            traded, signaled = False, False
            # Risk first, using only positions already held at previous close.
            for asset_id in ids:
                candle = snap["daily"][asset_id].get(day)
                if candle is None:
                    continue
                pos = state["positions"][asset_id]
                if dec(pos["qty"]) <= 0:
                    continue
                stop_pct = dec(state["risk"].get("stop_loss_pct", 0))
                take_pct = dec(state["risk"].get("take_profit_pct", 0))
                avg = dec(pos["avg"])
                stop = avg*(1-stop_pct/100) if stop_pct else None
                take = avg*(1+take_pct/100) if take_pct else None
                kind, target = (
                    ("stop", stop) if stop is not None and dec(candle["low"]) <= stop else
                    ("limit", take) if take is not None and dec(candle["high"]) >= take else (None, None)
                )
                if kind:
                    exit_order = {
                        "id": str(uuid4()), "side": "sell", "kind": kind,
                        "size": "100", "size_type": "percent", "price": str(target),
                        "source": "risk",
                    }
                    outcome = _execute(state, asset_id, exit_order, candle)
                    event(state, f"{asset_id} protective exit: {outcome}")
                    traded = outcome.startswith("FILLED")
            pending = []
            for queued in state["orders"]:
                asset_id = queued["asset_id"]
                candle = snap["daily"][asset_id].get(day)
                if candle is None or queued["placed_step"] >= next_idx:
                    pending.append(queued)
                    continue
                outcome = _execute(state, asset_id, queued, candle)
                if outcome == "pending":
                    pending.append(queued)
                else:
                    event(state, f"{asset_id}: {outcome}")
                    traded = traded or outcome.startswith("FILLED")
            state["orders"] = pending
            state["index"] = next_idx
            # Each rule reads only its *signal* symbol's candles through this
            # day's close. Its order for another symbol waits for a future bar.
            for rule in bot_rules:
                signal_day = snap["daily"][rule.signal_id]
                if day not in signal_day or len(pending) >= 40 or next_idx >= len(days)-1:
                    continue
                observed = [signal_day[d] for d in days[:next_idx+1] if d in signal_day]
                if not matches(rule.rule, observed, len(observed)-1):
                    continue
                pos = state["positions"][rule.target_id]
                if rule.rule.side == "sell" and dec(pos["qty"]) <= 0:
                    continue
                if any(o["source"] == "bot" and o["asset_id"] == rule.target_id and
                       o["side"] == rule.rule.side for o in pending):
                    continue
                queued = {
                    "id": str(uuid4()), "asset_id": rule.target_id,
                    "side": rule.rule.side, "kind": "market",
                    "size": str(rule.rule.percent), "size_type": "percent",
                    "price": None, "source": "bot", "placed_step": next_idx,
                }
                pending.append(queued)
                event(state, f"BOT: {rule.signal_id} signal queued {rule.rule.side.upper()} for {rule.target_id}.")
                signaled = True
                break
            cash, exposure, _ = _equity(snap, state, next_idx)
            state["curve"].append({"day": day, "value": float(cash+exposure)})
            if until_action and (traded or signaled):
                break
        if state["index"] == len(days)-1:
            state["orders"] = []
            if not state.get("completed"):
                event(state, "Portfolio season complete.")
                state["completed"] = True
        _save(db, run_id, state)
        return public(run_id, row, snap, state)
