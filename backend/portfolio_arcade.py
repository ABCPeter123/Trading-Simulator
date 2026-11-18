"""Multi-asset Trading Arcade: frozen, aligned daily OHLCV and shared cash.

Standalone table ensures all existing single-asset Arcade saves remain intact.
Provider data are downloaded before session creation and stay immutable for the
entire game. Only revealed bars leave the server. Missing sessions are NOT
forward-filled into tradable candles.
"""
from __future__ import annotations

from contextlib import closing
from bisect import bisect_left
from datetime import datetime, timezone, date, timedelta
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
from .intraday import replay_history, validate_replay_window
from .portfolio_dsl import compile_portfolio_rules
from .time_navigation import checkpoint, snapshot_at, history_info
from . import portfolio_research as pr, advanced_portfolio_research as adv

LOCK = RLock()
DB_PATH = Path(os.environ.get(
    "TRADING_SIM_ARCADE_DB",
    Path(__file__).resolve().parent.parent / "data" / "arcade.sqlite3",
))
MAX_SYMBOLS = 10
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


def _date(bar, resolution="1d"):
    timestamp = datetime.fromtimestamp(int(bar["time"]), tz=timezone.utc)
    return timestamp.date().isoformat() if resolution == "1d" else timestamp.isoformat(timespec="seconds")


def _prepare(histories, resolution="1d"):
    """Align actual provider candle timestamps; never create a missing candle."""
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
            daily[_date(bar, resolution)] = bar
        if len(daily) < 80:
            raise HTTPException(422, detail=f"{asset_id} has fewer than 80 usable candles.")
        by_id[asset_id] = daily
        timeline.update(daily)
    days = sorted(timeline)
    # Intraday bars from stocks, cryptocurrencies and different exchanges
    # often have different timestamp offsets. Require actual overlapping
    # calendar dates, not identical candle start timestamps.
    if resolution == "1d":
        shared = set.intersection(*(set(daily) for daily in by_id.values()))
        shared_days = sorted(shared)
        if len(shared_days) < 75 or shared_days[-1] < days[max(0, len(days) - 21)]:
            raise HTTPException(422, detail="Basket needs at least 75 overlapping daily candles, including a recent shared session.")
        common_warmup = shared_days[34]
    else:
        shared_dates = set.intersection(*(set(k[:10] for k in daily) for daily in by_id.values()))
        common = sorted(shared_dates)
        if len(common) < 2:
            raise HTTPException(422, detail="Intraday basket requires at least two overlapping real trading dates.")
        # A symbol that stopped trading weeks ago cannot share a playable
        # recent timeline with a continuously traded cryptocurrency.
        from datetime import date, timedelta
        if date.fromisoformat(days[-1][:10]) - date.fromisoformat(common[-1]) > timedelta(days=7):
            raise HTTPException(422, detail="Basket intraday histories are not recent enough to align.")
        common_warmup = common[0]
    seen = {asset_id: 0 for asset_id in by_id}
    first = None
    for idx, day in enumerate(days):
        for asset_id, available in by_id.items():
            if day in available:
                seen[asset_id] += 1
        if day >= common_warmup and all(count >= 36 for count in seen.values()):
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
    checkpoint(state)
    db.execute("UPDATE portfolio_seasons SET state=?, updated_at=? WHERE id=?",
               (json.dumps(state), datetime.now(timezone.utc).isoformat(), run_id))


def create_season(symbols, period="5Y", starting_point=0.3, start_date=None, resolution="1d"):
    if not isinstance(symbols, list) or not 2 <= len(symbols) <= MAX_SYMBOLS:
        raise HTTPException(422, detail="Choose 2-10 assets for one shared-cash season.")
    if len(set(symbols)) != len(symbols):
        raise HTTPException(422, detail="Each instrument can appear only once.")
    validate_replay_window(period, resolution)
    if not 0.15 <= starting_point <= 0.75:
        raise HTTPException(422, detail="Invalid season starting point.")
    instruments = [get_instrument(asset_id) for asset_id in symbols]
    if any(i.currency not in ("USD","CAD") or i.kind not in ("Stocks","ETFs","Crypto")
           or (i.kind=="Crypto" and i.currency!="USD")
           or (not i.tradable and i.currency!="CAD") for i in instruments):
        raise HTTPException(422,detail="Portfolio simulation supports USD/CAD stocks and ETFs, plus USD cryptocurrency.")
    raw = {asset_id: (history(asset_id, period) if resolution == "1d"
                      else replay_history(asset_id, period, resolution)) for asset_id in symbols}
    if any(item.currency=="CAD" for item in instruments):
        fx_window=period if resolution=="1d" else "2Y"
        reference=history("usdcad",fx_window)
        if reference.get("is_demo") or reference.get("offline_cache"):
            raise HTTPException(422,detail="Real historical USD/CAD daily FX prices are required for CAD portfolio simulations.")
        fx_rows=reference.get("bars")
        if not isinstance(fx_rows,list) or len(fx_rows)<2:
            raise HTTPException(422,detail="Insufficient observed USD/CAD daily FX history.")
        fx_daily={}
        for bar in fx_rows:
            day=datetime.fromtimestamp(int(bar["time"]),timezone.utc).date().isoformat()
            value=float(bar["close"])
            if not 0<value<100:
                raise HTTPException(422,detail="Invalid historical USD/CAD FX close.")
            fx_daily[day]=value
        fx_days=sorted(fx_daily)
        for item in instruments:
            if item.currency!="CAD":continue
            payload=raw[item.id]
            converted=[]
            for candle in payload["bars"]:
                day=datetime.fromtimestamp(int(candle["time"]),timezone.utc).date().isoformat()
                previous=bisect_left(fx_days,day)-1
                if previous<0:continue
                fx_date=fx_days[previous]
                if (date.fromisoformat(day)-date.fromisoformat(fx_date)).days>5:
                    continue
                rate=fx_daily[fx_date]
                converted.append({**candle,**{k:float(candle[k])/rate
                    for k in ("open","high","low","close")}})
            raw[item.id]={**payload,"bars":converted,
                "source":str(payload.get("source","provider"))+
                    "; USD-equivalent from previous completed USD/CAD FX close"}
    days, daily, warmup = _prepare(raw, resolution)
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
    snapshot = {"days": days, "daily": daily, "sources": sources, "resolution": resolution}
    initial_positions = {asset_id: {"qty": "0", "avg": "0", "realized": "0"} for asset_id in symbols}
    state = {
        "index": index, "start_index": index, "resolution": resolution, "cash": str(INITIAL_CASH),
        "positions": initial_positions, "orders": [], "fills": [],
        "strategy": "", "model_strategy": None, "risk": {"stop_loss_pct": 0, "take_profit_pct": 0},
        "events": ["Multi-asset historical replay started. Future candles remain hidden."],
        "curve": [{"day": days[index], "value": float(INITIAL_CASH)}],
    }
    checkpoint(state)
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
        "period": row["period"], "resolution": state.get("resolution", "1d"), "sources": snap["sources"],
        "day": days[idx], "current_step": idx, "total_steps": len(days),
        **history_info(state), "view_index": idx, "viewing_past": False,
        "progress_pct": round(100*idx/(len(days)-1), 1),
        "finished": idx == len(days)-1, "bars": visible,
        "metrics": {
            "cash": float(cash), "exposure": float(exposure), "equity": float(equity),
            "return_pct": ret, "equal_weight_hold_pct": baseline,
            "max_drawdown_pct": drawdown, "xp": xp, "level": xp//125+1,
            "score": score, "badges": badges,
        }, "positions": positions,
        "orders": state["orders"], "fills": state["fills"][-60:][::-1],
        "events": state["events"], "strategy": state["strategy"],
        "model_strategy": state.get("model_strategy"), "risk": state["risk"],
        "curve": state["curve"], "updated_at": row["updated_at"],
        "execution_notice": "Shared USD cash and observed close marks. CAD asset OHLC is converted into USD equivalents with the previous completed USD/CAD close when applicable. This is research-only currency modeling, not an executable FX rate. Fills use OHLC approximations, and unrevealed candles remain hidden.",
    }


def get_analysis(run_id, at_index=None):
    """Read-only analytics from frozen bars and full untruncated fill ledger."""
    from .strategy_analytics import build_report
    with LOCK, closing(connection()) as db:
        row, snap, state = _load(db, run_id)
        if at_index is not None:
            if at_index > state["index"]:
                raise HTTPException(422, detail="Cannot analyze an unrevealed step.")
            state = snapshot_at(state, at_index)
        return build_report(
            snap["days"], snap["daily"], json.loads(row["basket"]),
            state["start_index"], state["index"], state["fills"],
            resolution=state.get("resolution", "1d"),
        )


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
        previous = state["strategy"]
        state["strategy"] = code
        state["model_strategy"] = None
        event(state, f"Cross-asset strategy activated with {len(rules)} rules.")
        _save(db, run_id, state)
        response = public(run_id, row, snap, state)
    try:
        from .strategy_library import capture
        for version in (previous, code):
            capture("portfolio", version, json.loads(row["basket"]), run_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not archive activated portfolio strategy")
    return response


def activate_tournament_model(run_id, strategy_id):
    """Activate an immutable, researched model in an existing daily replay."""
    from . import tournament_strategies as tournament
    version = tournament.get(strategy_id)
    spec = tournament.validate_spec(json.loads(version["code"]))
    if spec.get("research_only"):
        raise HTTPException(422, detail="Short-share and margin strategies need a signed-position replay engine; conventional cash portfolio simulation cannot execute them.")
    with LOCK, closing(connection()) as db, db:
        row, snap, state = _load(db, run_id)
        if snap.get("resolution") != "1d":
            raise HTTPException(422, detail="Tournament models require daily historical replay.")
        if json.loads(row["basket"]) != spec["symbols"]:
            raise HTTPException(422, detail="The simulator basket must match the tournament model exactly.")
        if state["index"] != state["start_index"] or state["fills"]:
            raise HTTPException(409, detail="Load a tournament model into a new, unplayed simulation.")
        state["strategy"] = ""
        state["model_strategy"] = {"id": version["id"], "name": version["name"], **spec,
                                   "elapsed_shared": 0, "next_rebalance": 1}
        event(state, "Tournament allocation model loaded. Trades are simulated on future "
              "common session opens using previously completed daily closes.")
        _save(db, run_id, state)
        return public(run_id, row, snap, state)


def create_tournament_season(strategy_id, period="MAX", starting_point=0.3, start_date=None):
    """Create a new private replay and attach a saved model; never mutate an old run."""
    from . import tournament_strategies as tournament
    version = tournament.get(strategy_id)
    model = tournament.validate_spec(json.loads(version["code"]))
    if model.get("research_only"):
        raise HTTPException(422, detail="This signed-exposure research strategy cannot be run in the current cash-only portfolio simulator.")
    run = create_season(model["symbols"], period, starting_point, start_date, "1d")
    return activate_tournament_model(run["id"], strategy_id)


def _rebalance_model(snapshot, state, ids, next_idx):
    """Same target-weight function as tournament; no observations from fill day.

    All symbols must share the actual session. Delay 2 uses one additional
    completed-session lag, matching the tournament model's stress semantics.
    """
    config=state.get("model_strategy")
    if not config:
        return False
    days=snapshot["days"]
    day=days[next_idx]
    if any(day not in snapshot["daily"][s] for s in ids):
        return False
    config["elapsed_shared"]+=1
    if config["elapsed_shared"] < config["next_rebalance"]:
        return False
    common=[d for d in days[:next_idx] if all(d in snapshot["daily"][s] for s in ids)]
    observed=common[:-(config["delay_sessions"]-1)] if config["delay_sessions"]>1 else common
    if len(observed)<pr.WARMUP:
        return False
    closes={s:[float(snapshot["daily"][s][d]["close"]) for d in observed] for s in ids}
    metadata={}
    for s in ids:
        item=get_instrument(s)
        metadata[s]={"group":pr._group(s,item.kind),"kind":item.kind,
                     "currency":item.currency,"spread_bps":float(item.spread_bps)}
    allocation=(adv.weights if config["model"] in adv.MODELS else pr._weights)
    weights=allocation(config["model"],ids,closes,len(observed),metadata,
                       config["max_position_pct"]/100)
    if any(weight<0 for weight in weights.values()):
        raise ValueError("Signed exposure cannot enter a cash-only replay")
    opening={s:dec(snapshot["daily"][s][day]["open"]) for s in ids}
    equity=dec(state["cash"])+sum(dec(state["positions"][s]["qty"])*opening[s] for s in ids)
    traded=False
    for side in ("sell","buy"):
        for s in ids:
            current=dec(state["positions"][s]["qty"])
            desired=dec(weights[s])*equity/opening[s]
            desired=desired.to_integral_value(rounding="ROUND_DOWN")
            delta=desired-current
            quantity=min(current,-delta) if side=="sell" else delta
            if quantity<=0:
                continue
            if side=="buy":
                # Keep a modest buffer for execution spread and the simulator fee.
                maximum=(dec(state["cash"])*dec(".98")/opening[s]).to_integral_value(rounding="ROUND_DOWN")
                quantity=min(quantity,maximum)
            if quantity<=0:
                continue
            queued={"id":str(uuid4()),"side":side,"kind":"market",
                    "size":str(quantity),"size_type":"units","price":None,
                    "source":"tournament"}
            outcome=_execute(state,s,queued,snapshot["daily"][s][day])
            if outcome.startswith("FILLED"):
                traded=True
            event(state,f"MODEL {s.upper()}: {outcome}")
    config["next_rebalance"]=config["elapsed_shared"]+config["rebalance_sessions"]
    event(state,"Tournament portfolio rebalance checked using prior completed sessions.")
    return traded


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
            if state.get("model_strategy"):
                traded = _rebalance_model(snap,state,ids,next_idx) or traded
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
            checkpoint(state)
            if until_action and (traded or signaled):
                break
        if state["index"] == len(days)-1:
            state["orders"] = []
            if not state.get("completed"):
                event(state, "Portfolio historical replay completed.")
                state["completed"] = True
        _save(db, run_id, state)
        return public(run_id, row, snap, state)

def get_at(run_id, index: int):
    """Non-destructive read of recorded historic positions/orders/strategy."""
    with LOCK, closing(connection()) as db:
        row, snap, state = _load(db, run_id)
        if not state.get("checkpoints"):
            checkpoint(state)
        if index < state["start_index"] or index > state["index"]:
            raise HTTPException(422, detail="Cannot navigate to an unrevealed step.")
        old = snapshot_at(state,index)
        result = public(run_id,row,snap,old)
        result.update(**history_info(state),view_index=index,
                      viewing_past=index < state["index"])
        return result
