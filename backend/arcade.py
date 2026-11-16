"""Server-authoritative, persistent historical game. Never return unrevealed bars."""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_DOWN
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4
import zlib

from fastapi import HTTPException

from .arcade_dsl import EXAMPLES, compile_rules, matches
from .assets import get_instrument
from .ledger import dec, fee_for, positive_quantity
from .market import history
from .intraday import replay_history, validate_replay_window
from .time_navigation import checkpoint, snapshot_at, history_info

GAME_DB = Path(os.environ.get("TRADING_SIM_ARCADE_DB", Path(__file__).resolve().parent.parent / "data" / "arcade.sqlite3"))
LOCK = RLock()
INITIAL_CASH = Decimal("100000")
MAX_SKIP = 100


def connection():
    GAME_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(GAME_DB), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
        id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, source TEXT NOT NULL,
        history_blob BLOB NOT NULL, state TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    return db


def read(db, run_id):
    row = db.execute("SELECT * FROM game_sessions WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, detail="Arcade run not found.")
    return row, json.loads(zlib.decompress(row["history_blob"])), json.loads(row["state"])


def save(db, run_id, state):
    checkpoint(state)
    db.execute("UPDATE game_sessions SET state=?, updated_at=? WHERE id=?",
               (json.dumps(state), datetime.now(timezone.utc).isoformat(), run_id))


def event(state, message):
    state["events"] = ([message] + state["events"])[:12]


def start_run(asset_id, starting_point=0.3, period="5Y", start_date=None, resolution="1d"):
    instrument = get_instrument(asset_id)
    if not instrument.tradable or instrument.currency != "USD":
        raise HTTPException(422, detail="This contract/currency is not supported in the USD cash arcade.")
    if not 0.15 <= starting_point <= 0.75:
        raise HTTPException(422, detail="Starting point must be 15% to 75%.")
    validate_replay_window(period, resolution)
    data = history(asset_id, period) if resolution == "1d" else replay_history(asset_id, period, resolution)
    bars = data["bars"]
    if len(bars) < 65:
        raise HTTPException(422, detail="Need at least 65 real historical candles.")
    if any(float(b["open"]) <= 0 or float(b["close"]) <= 0 or
           float(b["high"]) < max(float(b["open"]), float(b["close"]), float(b["low"])) or
           float(b["low"]) > min(float(b["open"]), float(b["close"]), float(b["high"]))
           for b in bars):
        raise HTTPException(503, detail="Invalid provider candles.")
    index = min(len(bars)-2, max(35, int(len(bars) * starting_point)))
    if start_date:
        try:
            requested_day = date.fromisoformat(start_date)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, detail="Start date must be YYYY-MM-DD.") from exc
        timestamp = datetime(requested_day.year, requested_day.month, requested_day.day,
                             tzinfo=timezone.utc).timestamp()
        index = next((i for i, candle in enumerate(bars)
                      if candle["time"] >= timestamp), len(bars)-1)
        if index >= len(bars)-1:
            raise HTTPException(422, detail="Start date is after available historical prices.")
        index = max(35, index)  # warmup for moving averages and RSI
    now = datetime.now(timezone.utc).isoformat()
    run_id = str(uuid4())
    state = dict(index=index, start_index=index, period=period, resolution=resolution, requested_start_date=start_date, risk={"stop_loss_pct": 0, "take_profit_pct": 0}, cash=str(INITIAL_CASH), qty="0",
                 avg="0", realized="0", orders=[], fills=[], strategy="",
                 curve=[{"time": bars[index]["time"], "value": float(INITIAL_CASH)}],
                 events=["Season started. Future candles are hidden."])
    checkpoint(state)
    compressed = zlib.compress(json.dumps(bars, separators=(",", ":")).encode(), level=6)
    with LOCK, closing(connection()) as db, db:
        db.execute("INSERT INTO game_sessions VALUES (?,?,?,?,?,?,?)",
                   (run_id, asset_id, data["source"], compressed, json.dumps(state), now, now))
    return get_run(run_id)


def public(run_id, row, bars, state):
    i = state["index"]
    cash, qty, avg = dec(state["cash"]), dec(state["qty"]), dec(state["avg"])
    mark = dec(bars[i]["close"])
    equity = cash + qty * mark
    pnl_pct = float((equity / INITIAL_CASH - 1) * 100)
    baseline = float((mark / dec(bars[state["start_index"]]["close"]) - 1) * 100)
    peak = float(INITIAL_CASH)
    worst = 0.0
    for sample in state["curve"]:
        peak = max(peak, sample["value"])
        worst = min(worst, 100 * (sample["value"] / peak - 1))
    excess = pnl_pct - baseline
    score = max(0, round(500 + excess * 12 + worst * 6))
    xp = len(state["fills"]) * 25 + i - state["start_index"] + (50 if state["strategy"].strip() else 0)
    badges = []
    if state["fills"]: badges.append("First fill")
    if state["strategy"].strip(): badges.append("Bot programmed")
    if equity > INITIAL_CASH: badges.append("In the green")
    if excess > 0 and state["fills"]: badges.append("Beat buy & hold")
    if i == len(bars)-1: badges.append("Season complete")
    return {
        "id": run_id, "asset_id": row["asset_id"], "source": row["source"],
        "period": state.get("period", "1Y"), "resolution": state.get("resolution", "1d"), "requested_start_date": state.get("requested_start_date"), "risk": state.get("risk", {"stop_loss_pct": 0, "take_profit_pct": 0}),
        "current_bar": i, "total_bars": len(bars),
        **history_info(state), "view_index": i, "viewing_past": False, "finished": i == len(bars)-1,
        "progress_pct": round(100*i/(len(bars)-1), 1),
        "bars": bars[:i+1],  # no future data leaves this API
        "orders": state["orders"], "fills": state["fills"][-30:][::-1],
        "events": state["events"], "strategy": state["strategy"], "equity_curve": state["curve"],
        "metrics": {
            "cash": float(cash), "quantity": float(qty), "average_cost": float(avg),
            "equity": float(equity), "position_value": float(qty*mark),
            "unrealized_pnl": float(qty*(mark-avg)), "realized_pnl": float(dec(state["realized"])),
            "return_pct": pnl_pct, "buy_hold_pct": baseline, "max_drawdown_pct": worst,
            "score": score, "xp": xp, "level": xp//125+1, "badges": badges,
        },
        "examples": EXAMPLES, "updated_at": row["updated_at"],
        "execution_notice": "Bar-based fills with assumed bid/ask spread, 2bp slippage and fees. Intrabar sequencing, queue position and market impact are not available.",
    }


def get_analysis(run_id, at_index=None):
    """Compute analytics using only the portion of the season already revealed."""
    from .strategy_analytics import build_report
    from datetime import datetime, timezone
    with LOCK, closing(connection()) as db:
        row, bars, state = read(db, run_id)
        if at_index is not None:
            if at_index > state["index"]:
                raise HTTPException(422, detail="Cannot analyze an unrevealed step.")
            state = snapshot_at(state, at_index)
        precision = state.get("resolution", "1d")
        days = [(datetime.fromtimestamp(int(b["time"]), timezone.utc).date().isoformat() if precision == "1d"
                 else datetime.fromtimestamp(int(b["time"]), timezone.utc).isoformat(timespec="seconds")) for b in bars]
        asset_id = row["asset_id"]
        by_date = {day: bar for day, bar in zip(days, bars)}
        report = build_report(
            days, {asset_id: by_date}, [asset_id],
            state["start_index"], state["index"],
            [{**fill, "asset_id": asset_id} for fill in state["fills"]],
            resolution=precision,
        )
        return report


def get_run(run_id):
    with LOCK, closing(connection()) as db:
        row, bars, state = read(db, run_id)
        return public(run_id, row, bars, state)


def list_runs():
    with LOCK, closing(connection()) as db:
        rows = db.execute("SELECT id, asset_id, updated_at FROM game_sessions ORDER BY updated_at DESC LIMIT 25").fetchall()
        return [dict(row) for row in rows]


def submit_order(run_id, side, kind, size, size_type, price=None, source="manual"):
    if side not in ("buy", "sell") or kind not in ("market", "limit", "stop") or size_type not in ("percent", "units"):
        raise HTTPException(422, detail="Unsupported order settings.")
    amount = positive_quantity(size)
    if size_type == "percent" and amount > 100:
        raise HTTPException(422, detail="Percentage must not exceed 100.")
    trigger = None if kind == "market" else dec(price)
    if trigger is not None and not Decimal(0) < trigger < Decimal("1000000000"):
        raise HTTPException(422, detail="Trigger price must be positive.")
    with LOCK, closing(connection()) as db, db:
        row, bars, state = read(db, run_id)
        if state["index"] >= len(bars)-1:
            raise HTTPException(409, detail="Season is finished.")
        if len(state["orders"]) >= 20:
            raise HTTPException(409, detail="Pending order limit reached.")
        if side == "sell" and dec(state["qty"]) <= 0 and not any(o["side"] == "buy" for o in state["orders"]):
            raise HTTPException(409, detail="You need holdings to queue a sell.")
        if size_type == "units" and get_instrument(row["asset_id"]).kind in ("Stocks", "ETFs"):
            positive_quantity(size, whole=True)
        order = dict(id=str(uuid4()), side=side, kind=kind, size=str(amount),
                     size_type=size_type, price=str(trigger) if trigger is not None else None,
                     source=source, placed_bar=state["index"])
        state["orders"].append(order)
        event(state, f"{side.upper()} order queued; only future candles can fill it.")
        save(db, run_id, state)
        return public(run_id, row, bars, state)


def cancel_order(run_id, order_id):
    with LOCK, closing(connection()) as db, db:
        row, bars, state = read(db, run_id)
        remaining = [o for o in state["orders"] if o["id"] != order_id]
        if len(remaining) == len(state["orders"]):
            raise HTTPException(404, detail="Pending order not found.")
        state["orders"] = remaining
        event(state, "Order cancelled.")
        save(db, run_id, state)
        return public(run_id, row, bars, state)


def set_strategy(run_id, code):
    rules = compile_rules(code)
    with LOCK, closing(connection()) as db, db:
        row, bars, state = read(db, run_id)
        previous = state["strategy"]
        state["strategy"] = code
        event(state, f"Bot saved: {len(rules)} rule(s). Signals check each revealed close.")
        save(db, run_id, state)
        response = public(run_id, row, bars, state)
    try:
        from .strategy_library import capture
        for version in (previous, code):
            capture("single", version, [row["asset_id"]], run_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not archive activated single strategy")
    return response


def set_risk(run_id, stop_loss_pct=0, take_profit_pct=0):
    if any(not (0 <= v <= 75) for v in (stop_loss_pct, take_profit_pct)):
        raise HTTPException(422, detail="Protective percentages must be from 0 to 75.")
    with LOCK, closing(connection()) as db, db:
        row, bars, state = read(db, run_id)
        state["risk"] = {"stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct}
        event(state, "Risk controls updated. Protections apply from the next candle.")
        save(db, run_id, state)
        return public(run_id, row, bars, state)


def execute(state, order, bar, instrument):
    opening = dec(bar["open"])
    high, low = dec(bar["high"]), dec(bar["low"])
    side, kind = order["side"], order["kind"]
    impact = dec(instrument.spread_bps) / 20000 + Decimal(".0002")
    trigger = dec(order["price"]) if order["price"] is not None else None
    if kind == "market":
        price = opening * (1+impact if side == "buy" else 1-impact)
    elif kind == "limit":
        if (side == "buy" and low > trigger) or (side == "sell" and high < trigger):
            return "pending"
        # Favorable opening gaps can improve a limit fill, never worse.
        if side == "buy":
            price = min(trigger, opening*(1+impact)) if opening <= trigger else trigger
        else:
            price = max(trigger, opening*(1-impact)) if opening >= trigger else trigger
    else:
        if (side == "buy" and high < trigger) or (side == "sell" and low > trigger):
            return "pending"
        raw = max(opening, trigger) if side == "buy" else min(opening, trigger)
        price = raw*(1+impact if side == "buy" else 1-impact)
    cash, held, avg = dec(state["cash"]), dec(state["qty"]), dec(state["avg"])
    amount = dec(order["size"])
    if order["size_type"] == "percent":
        if side == "buy":
            amount = cash*amount/100/(price*Decimal("1.02"))  # room for commission
        else:
            amount = held*amount/100
    whole = instrument.kind in ("Stocks", "ETFs")
    qty = (amount.to_integral_value(rounding=ROUND_DOWN) if whole
           else amount.quantize(Decimal(".00000001"), rounding=ROUND_DOWN))
    if qty <= 0: return "rejected: quantity rounds to zero"
    if side == "sell" and qty > held: return "rejected: insufficient holdings"
    fee = fee_for(instrument.kind, qty, price)
    if side == "buy" and qty*price+fee > cash: return "rejected: insufficient cash with fee"
    if side == "buy":
        new_qty = held + qty
        avg = (held*avg+qty*price+fee)/new_qty
        held = new_qty
        cash -= qty*price+fee
    else:
        cash += qty*price-fee
        state["realized"] = str(dec(state["realized"])+qty*(price-avg)-fee)
        held -= qty
        if held == 0: avg = Decimal(0)
    state.update(cash=str(cash), qty=str(held), avg=str(avg))
    state["fills"].append(dict(order_id=order["id"], time=bar["time"], side=side,
                               quantity=float(qty), price=float(price), fee=float(fee),
                               source=order["source"], kind=kind))
    return f"FILLED: {side.upper()} {float(qty):g} at {float(price):.6g}; fee {float(fee):.2f} USD"


def advance_run(run_id, count=1, until_action=False):
    if type(count) is not int or not 1 <= count <= MAX_SKIP:
        raise HTTPException(422, detail="Skip must be 1 to 100 candles.")
    with LOCK, closing(connection()) as db, db:
        row, bars, state = read(db, run_id)
        rules = compile_rules(state["strategy"])
        instrument = get_instrument(row["asset_id"])
        for _ in range(min(count, len(bars)-1-state["index"])):
            nxt = state["index"]+1
            bar = bars[nxt]
            # Risk checks are for holdings entering the bar, never a position
            # acquired within this same OHLC candle. At most one protective
            # exit is selected. If both levels touch, stop-loss takes priority.
            risk = state.get("risk", {})
            held_before = dec(state["qty"])
            if held_before > 0:
                avg = dec(state["avg"])
                stop_pct = dec(risk.get("stop_loss_pct", 0))
                take_pct = dec(risk.get("take_profit_pct", 0))
                stop_level = avg * (1 - stop_pct/100) if stop_pct else None
                take_level = avg * (1 + take_pct/100) if take_pct else None
                kind, target = (("stop", stop_level) if stop_level is not None and dec(bar["low"]) <= stop_level
                                else ("limit", take_level) if take_level is not None and dec(bar["high"]) >= take_level
                                else (None, None))
                if kind is not None:
                    risk_order = {
                        "id": str(uuid4()), "side": "sell", "kind": kind,
                        "size": "100", "size_type": "percent",
                        "price": str(target), "source": "risk", "placed_bar": nxt-1,
                    }
                    result = execute(state, risk_order, bar, instrument)
                    event(state, "PROTECTIVE EXIT: " + result)
            pending = []
            traded = False
            for order in state["orders"]:
                if order["placed_bar"] >= nxt:
                    pending.append(order)
                    continue
                outcome = execute(state, order, bar, instrument)
                if outcome == "pending":
                    pending.append(order)
                else:
                    event(state, outcome)
                    traded = True
            state["orders"] = pending
            state["index"] = nxt
            signal = False
            if rules and nxt < len(bars)-1 and len(pending) < 20:
                for rule in rules:
                    if not matches(rule, bars, nxt):
                        continue
                    if any(o["side"] == rule.side and o["source"] == "bot" for o in pending):
                        continue
                    if rule.side == "sell" and dec(state["qty"]) <= 0:
                        continue
                    pending.append(dict(id=str(uuid4()), side=rule.side, kind="market",
                                        size=str(rule.percent), size_type="percent",
                                        price=None, source="bot", placed_bar=nxt))
                    event(state, f"BOT SIGNAL: {rule.side.upper()} {rule.percent:g}%; order queues for the next open.")
                    signal = True
                    break
            state["curve"].append({"time": bar["time"], "value": float(dec(state["cash"])+dec(state["qty"])*dec(bar["close"]))})
            checkpoint(state)
            if until_action and (signal or traded):
                break
        if state["index"] == len(bars)-1:
            if state["orders"]:
                event(state, "End of historical data: unfilled orders expired.")
                state["orders"] = []
            if not state.get("completed"):
                event(state, "Season completed. Your final score is locked.")
                state["completed"] = True
        save(db, run_id, state)
        return public(run_id, row, bars, state)

def get_at(run_id, index: int):
    """View a previous exact checkpoint. Never mutate or replay orders."""
    with LOCK, closing(connection()) as db:
        row, bars, state = read(db, run_id)
        if not state.get("checkpoints"):
            # Old saves have a current snapshot only; older exact state was
            # not recorded before this release.
            checkpoint(state)
        if index < state["start_index"] or index > state["index"]:
            raise HTTPException(422, detail="Cannot navigate to an unrevealed step.")
        observed = snapshot_at(state,index)
        result = public(run_id,row,bars,observed)
        result.update(**history_info(state),view_index=index,
                      viewing_past=index < state["index"])
        return result
