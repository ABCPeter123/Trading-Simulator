"""Private persistent low-frequency strategy signal and trade-confirmation ledger.

No broker integration or real order submission. All stored strategy source, generated
signals, portfolio fills and alert destinations remain in Git-ignored local SQLite.
The worker is a separate process, independent of the web browser/API lifetime.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from threading import RLock
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .arcade_dsl import compile_rules, matches, indicator
from .portfolio_dsl import compile_portfolio_rules
from .strategy_library import get as get_saved_strategy
from .stochastic import probability_up

logger = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
DB_PATH = Path(os.environ.get("TRADING_SIM_LIVE_DB", Path(__file__).resolve().parents[1] / "data/live_machine.sqlite3"))
LOCK = RLock()

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _json(v):
    return json.dumps(v, separators=(",", ":"), allow_nan=False)

@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS deployments(
          id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, name TEXT NOT NULL,
          mode TEXT NOT NULL, code TEXT NOT NULL, symbols TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('paper','live-monitor','paused','retired')),
          capital REAL NOT NULL, max_allocation_pct REAL NOT NULL,
          max_realized_loss_pct REAL NOT NULL DEFAULT 5,
          max_daily_signals INTEGER NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, last_evaluated_at TEXT, last_error TEXT,
          resolution TEXT NOT NULL DEFAULT '1d'
        );
        CREATE TABLE IF NOT EXISTS evaluations(
          id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL,
          symbol TEXT NOT NULL, bar_time INTEGER NOT NULL, evaluated_at TEXT NOT NULL,
          result TEXT NOT NULL, details TEXT NOT NULL,
          UNIQUE(deployment_id,symbol,bar_time),
          FOREIGN KEY(deployment_id) REFERENCES deployments(id)
        );
        CREATE TABLE IF NOT EXISTS signals(
          id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, evaluation_id TEXT NOT NULL,
          source_symbol TEXT NOT NULL, asset_id TEXT NOT NULL,
          side TEXT NOT NULL, allocation_pct REAL NOT NULL,
          suggested_notional REAL, price_reference REAL NOT NULL,
          data_time INTEGER NOT NULL, created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL, status TEXT NOT NULL,
          rationale TEXT NOT NULL, forecast_prob_up_pct REAL,
          FOREIGN KEY(deployment_id) REFERENCES deployments(id),
          FOREIGN KEY(evaluation_id) REFERENCES evaluations(id)
        );
        CREATE TABLE IF NOT EXISTS fills(
          id TEXT PRIMARY KEY, signal_id TEXT, asset_id TEXT NOT NULL,
          side TEXT NOT NULL CHECK(side IN ('buy','sell')), quantity REAL NOT NULL,
          price REAL NOT NULL, fee REAL NOT NULL DEFAULT 0,
          currency TEXT NOT NULL, executed_at TEXT NOT NULL, broker_ref TEXT,
          notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, FOREIGN KEY(signal_id) REFERENCES signals(id)
        );
        CREATE TABLE IF NOT EXISTS fill_revisions(
          id TEXT PRIMARY KEY, fill_id TEXT NOT NULL, previous TEXT NOT NULL,
          changed_at TEXT NOT NULL, FOREIGN KEY(fill_id) REFERENCES fills(id)
        );
        CREATE TABLE IF NOT EXISTS alerts(
          id TEXT PRIMARY KEY, key TEXT NOT NULL UNIQUE, severity TEXT NOT NULL,
          title TEXT NOT NULL, detail TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          last_sent_at TEXT, send_attempts INTEGER NOT NULL DEFAULT 0,
          last_delivery_error TEXT
        );
        CREATE TABLE IF NOT EXISTS runtime(
          name TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS signal_status ON signals(status, created_at);
        CREATE INDEX IF NOT EXISTS fill_timestamp ON fills(executed_at);
        CREATE INDEX IF NOT EXISTS alert_status ON alerts(status,severity);
        """)
        columns={row["name"] for row in conn.execute("PRAGMA table_info(deployments)")}
        if "max_realized_loss_pct" not in columns:
            conn.execute("ALTER TABLE deployments ADD COLUMN max_realized_loss_pct REAL NOT NULL DEFAULT 5")
        if "resolution" not in columns:
            conn.execute("ALTER TABLE deployments ADD COLUMN resolution TEXT NOT NULL DEFAULT '1d'")
        yield conn
    finally:
        conn.close()

def _rows(conn, sql, args=()):
    return [dict(x) for x in conn.execute(sql, args).fetchall()]

def _one(conn, sql, args=()):
    row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None

def _public_deploy(d):
    if not d: return None
    x = dict(d)
    x["symbols"] = json.loads(x["symbols"])
    # API may show strategy code to authenticated owner, but not include it in
    # ordinary dashboard/status payloads or notification content.
    x.pop("code", None)
    return x

def _public_signal(s):
    return dict(s) if s else None

def deploy(strategy_id: str, state: str = "paper", capital: float = 100000.,
           max_allocation_pct: float = 10., max_daily_signals: int = 4,
           max_realized_loss_pct: float = 5.,resolution: str = "1d"):
    if state not in ("paper","live-monitor"):
        raise HTTPException(422, detail="Start in paper or live-monitor mode only.")
    if not (math.isfinite(capital) and 100 <= capital <= 1e10):
        raise HTTPException(422, detail="Reference capital must be between 100 and 10 billion.")
    if not (math.isfinite(max_allocation_pct) and 0 < max_allocation_pct <= 25):
        raise HTTPException(422, detail="Allocation cap must be between 0 and 25%.")
    if not 1 <= max_daily_signals <= 20:
        raise HTTPException(422, detail="Daily signal cap must be 1-20.")
    if not math.isfinite(max_realized_loss_pct) or not 0.5<=max_realized_loss_pct<=25:
        raise HTTPException(422,detail="Realized-loss stop must be between 0.5% and 25%.")
    if resolution not in ("1d","1h","15m"):
        raise HTTPException(422,detail="Monitoring interval must be 1d, 1h or 15m.")
    item = get_saved_strategy(strategy_id)
    if item["mode"] == "single":
        rules = compile_rules(item["code"])
    else:
        rules = compile_portfolio_rules(item["code"], set(item["symbols"]))
    if not rules:
        raise HTTPException(422, detail="Strategy must include at least one rule.")
    identifier, now = str(uuid4()), _utc()
    with LOCK, db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO deployments (id,strategy_id,name,mode,code,symbols,state,
               capital,max_allocation_pct,max_realized_loss_pct,max_daily_signals,
               created_at,updated_at,last_evaluated_at,last_error,resolution)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (identifier, strategy_id, item["name"], item["mode"], item["code"],
             _json(item["symbols"]), state, capital, max_allocation_pct,
             max_realized_loss_pct, max_daily_signals, now, now, None, None,resolution),
        )
        conn.commit()
        return _public_deploy(_one(conn, "SELECT * FROM deployments WHERE id=?", (identifier,)))

def deployments():
    with LOCK, db() as conn:
        return [_public_deploy(x) for x in _rows(conn,"SELECT * FROM deployments ORDER BY created_at DESC")]

def change_state(deployment_id, state):
    if state not in ("paper","live-monitor","paused","retired"):
        raise HTTPException(422, detail="Invalid deployment state.")
    with LOCK, db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = _one(conn, "SELECT * FROM deployments WHERE id=?", (deployment_id,))
        if not existing: raise HTTPException(404, detail="Deployment not found.")
        if existing["state"] == "retired":
            raise HTTPException(409, detail="Retired deployments are immutable. Create a new version.")
        if state == "live-monitor" and existing["state"] == "paused":
            # Requires a deliberate explicit resume, not a worker transition.
            pass
        conn.execute("UPDATE deployments SET state=?,updated_at=? WHERE id=?",(state,_utc(),deployment_id))
        conn.commit()
        return _public_deploy(_one(conn,"SELECT * FROM deployments WHERE id=?",(deployment_id,)))

def _next_expiry(now: datetime) -> str:
    # Daily signals use the next weekday's 16:00 ET close as validity end.
    # This is a calendar approximation. Holidays/early closes require a
    # proper exchange calendar before treating a suggestion as actionable.
    d = now.astimezone(NY).date()
    if now.astimezone(NY).time() >= time(16):
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return datetime.combine(d,time(16),NY).astimezone(timezone.utc).isoformat()

def _last_complete(bars, now):
    today = now.astimezone(NY).date()
    # Daily Yahoo candles are timestamped at the exchange midnight.
    # Reject today's incomplete daily candle during the trading session.
    valid = [b for b in bars if datetime.fromtimestamp(b["time"],NY).date() < today]
    return valid

def record_alert(key: str, severity: str, title: str, detail: str):
    if severity not in ("info","warning","critical"): raise ValueError("Unsupported severity")
    now = _utc()
    with LOCK, db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO alerts(id,key,severity,title,detail,status,created_at,last_seen_at)
               VALUES(?,?,?,?,?,'open',?,?)
               ON CONFLICT(key) DO UPDATE SET
                 last_seen_at=excluded.last_seen_at,
                 title=excluded.title,
                 detail=excluded.detail,
                 status=CASE WHEN alerts.status='resolved' THEN 'open' ELSE alerts.status END""",
            (str(uuid4()),key,severity,title,detail,now,now),
        )
        conn.commit()

def resolve_alert(key: str):
    with LOCK,db() as conn:
        conn.execute("UPDATE alerts SET status='resolved',last_seen_at=? WHERE key=?",(_utc(),key))

def alerts(limit=100):
    with LOCK,db() as conn:
        return _rows(conn,"SELECT * FROM alerts ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, last_seen_at DESC LIMIT ?",(limit,))

def acknowledge_alert(alert_id, status="acknowledged"):
    if status not in ("acknowledged","resolved"): raise HTTPException(422,detail="Invalid alert action.")
    with LOCK,db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row=_one(conn,"SELECT * FROM alerts WHERE id=?",(alert_id,))
        if not row:raise HTTPException(404,detail="Alert not found.")
        conn.execute("UPDATE alerts SET status=?,last_seen_at=? WHERE id=?",(status,_utc(),alert_id))
        conn.commit()
        return _one(conn,"SELECT * FROM alerts WHERE id=?",(alert_id,))

def _positions(rows):
    """Long positions and realized cost basis, NEVER summing unrelated currencies."""
    holdings,by_currency={},{}
    for f in rows:
        asset,currency=f["asset_id"],f["currency"]
        key=(currency,asset)
        pos=holdings.setdefault(key,{"asset_id":asset,"currency":currency,
            "quantity":0.,"average_cost":0.,"realized_pnl":0.})
        by_currency.setdefault(currency,0.)
        qty=float(f["quantity"])
        px=float(f["price"])
        fee=float(f["fee"])
        if f["side"]=="buy":
            total=pos["quantity"]*pos["average_cost"]+qty*px+fee
            pos["quantity"]+=qty
            pos["average_cost"]=total/pos["quantity"]
        else:
            if qty>pos["quantity"]+1e-8:
                raise HTTPException(409,detail="Sell exceeds confirmed long holdings. Shorting is not enabled.")
            gain=qty*(px-pos["average_cost"])-fee
            pos["realized_pnl"]+=gain
            by_currency[currency]+=gain
            pos["quantity"]=max(0.,pos["quantity"]-qty)
            if pos["quantity"]==0:pos["average_cost"]=0.
    realized=sum(by_currency.values()) if len(by_currency)<=1 else None
    return list(holdings.values()),realized,by_currency

def journal():
    with LOCK,db() as conn:
        rows=_rows(conn,"SELECT * FROM fills ORDER BY executed_at ASC, created_at ASC")
        positions,realized,by_currency=_positions(rows)
        linked=_rows(conn,"SELECT id,asset_id,side,price_reference,suggested_notional,"
                          "created_at,expires_at,status FROM signals WHERE id IN "
                          "(SELECT DISTINCT signal_id FROM fills WHERE signal_id IS NOT NULL)")
    by_id={s["id"]:s for s in linked}
    reviews=[]
    for f in rows:
        source=by_id.get(f["signal_id"])
        if not source:continue
        executed=datetime.fromisoformat(f["executed_at"])
        reviews.append({
            "fill_id":f["id"],"signal_id":source["id"],"asset_id":f["asset_id"],
            "side":f["side"],"reference_price":source["price_reference"],
            "actual_price":f["price"],"price_deviation_pct":
                (f["price"]/source["price_reference"]-1)*100,
            "execution_delay_hours":
                (executed-datetime.fromisoformat(source["created_at"])).total_seconds()/3600,
            "after_signal_expiry":executed>datetime.fromisoformat(source["expires_at"]),
            "different_asset_or_side":f["asset_id"]!=source["asset_id"] or f["side"]!=source["side"],
            "suggested_notional":source["suggested_notional"],
            "actual_notional":f["quantity"]*f["price"],
        })
    return {"fills":list(reversed(rows)),"positions":positions,
            "realized_pnl":realized,"realized_by_currency":by_currency,
            "execution_reviews":list(reversed(reviews)),
            "note":"Confirmed manual executions only; separate currencies, no price marks or broker reconciliation."}

def record_fill(data):
    qty,price,fee=data["quantity"],data["price"],data["fee"]
    if not (all(math.isfinite(float(x)) for x in (qty,price,fee)) and qty>0 and price>0 and fee>=0):
        raise HTTPException(422,detail="Fill quantity/price must be positive and fee nonnegative.")
    if data["side"] not in ("buy","sell"):raise HTTPException(422,detail="Invalid fill side.")
    # Validate explicit ISO UTC timezone so retrospective edits don't depend
    # on the server's local time zone.
    try:
        dt=datetime.fromisoformat(data["executed_at"].replace("Z","+00:00"))
        if dt.tzinfo is None:raise ValueError("Timezone required")
        stamp=dt.astimezone(timezone.utc).isoformat()
    except (ValueError,TypeError):
        raise HTTPException(422,detail="Execution time must be ISO 8601 with timezone.")
    with LOCK,db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        signal=None
        if data.get("signal_id"):
            signal=_one(conn,"SELECT * FROM signals WHERE id=?",(data["signal_id"],))
            if not signal:raise HTTPException(404,detail="Referenced signal not found.")
        existing=_rows(conn,"SELECT * FROM fills ORDER BY executed_at ASC, created_at ASC")
        candidate={**data,"executed_at":stamp,"created_at":_utc()}
        _positions(sorted(existing+[candidate],key=lambda x:(x["executed_at"],x["created_at"])))
        identifier,now=str(uuid4()),_utc()
        conn.execute("""INSERT INTO fills(
          id,signal_id,asset_id,side,quantity,price,fee,currency,
          executed_at,broker_ref,notes,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (identifier,data.get("signal_id"),data["asset_id"],data["side"],qty,price,fee,
           data["currency"],stamp,data.get("broker_ref"),data.get("notes",""),now,now))
        if signal:
            conn.execute("UPDATE signals SET status='filled' WHERE id=?",(signal["id"],))
        conn.commit()
        result=_one(conn,"SELECT * FROM fills WHERE id=?",(identifier,))
    if signal:
        deviation=abs((float(price)/float(signal["price_reference"])-1)*100)
        late=datetime.fromisoformat(stamp)>datetime.fromisoformat(signal["expires_at"])
        mismatch=data["asset_id"]!=signal["asset_id"] or data["side"]!=signal["side"]
        if deviation>3 or late or mismatch:
            try:
                record_alert("fill:variance:"+identifier,"warning",
                             "Confirmed execution differs from original recommendation",
                             "Review the broker fill and signal: price moved more than 3%, "
                             "the action was recorded after expiry, or the instrument/side changed.")
            except Exception as exc:
                # The confirmed trade has already committed; an alert delivery
                # failure must never cause the operator to retry and duplicate it.
                logger.warning("Could not record trade variance alert: %s",type(exc).__name__)
    return result

def edit_fill(fill_id,data):
    with LOCK,db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing=_one(conn,"SELECT * FROM fills WHERE id=?",(fill_id,))
        if not existing:raise HTTPException(404,detail="Trade not found.")
        merged={**existing,**data}
        if not all(math.isfinite(float(merged[k])) for k in ("quantity","price","fee")):
            raise HTTPException(422,detail="Invalid trade values.")
        if merged["quantity"]<=0 or merged["price"]<=0 or merged["fee"]<0:
            raise HTTPException(422,detail="Invalid trade quantity, price or fee.")
        rows=_rows(conn,"SELECT * FROM fills WHERE id<>? ORDER BY executed_at ASC,created_at ASC",(fill_id,))
        _positions(sorted(rows+[merged],key=lambda x:(x["executed_at"],x["created_at"])))
        conn.execute("INSERT INTO fill_revisions VALUES(?,?,?,?)",(str(uuid4()),fill_id,_json(existing),_utc()))
        conn.execute("""UPDATE fills SET asset_id=?,side=?,quantity=?,price=?,fee=?,currency=?,
         executed_at=?,broker_ref=?,notes=?,updated_at=? WHERE id=?""",
         (merged["asset_id"],merged["side"],merged["quantity"],merged["price"],merged["fee"],
          merged["currency"],merged["executed_at"],merged.get("broker_ref"),merged["notes"],_utc(),fill_id))
        conn.commit()
        return _one(conn,"SELECT * FROM fills WHERE id=?",(fill_id,))

def fill_history(fill_id):
    with LOCK,db() as conn:
        return _rows(conn,"SELECT * FROM fill_revisions WHERE fill_id=? ORDER BY changed_at DESC",(fill_id,))

def signals(status: str | None=None,limit=100):
    with LOCK,db() as conn:
        if status:
            return _rows(conn,"SELECT * FROM signals WHERE status=? ORDER BY created_at DESC LIMIT ?",(status,limit))
        return _rows(conn,"SELECT * FROM signals ORDER BY created_at DESC LIMIT ?",(limit,))

def update_signal(signal_id,status):
    if status not in ("acknowledged","skipped","expired"):
        raise HTTPException(422,detail="Use acknowledged, skipped, or expired.")
    with LOCK,db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        x=_one(conn,"SELECT * FROM signals WHERE id=?",(signal_id,))
        if not x:raise HTTPException(404,detail="Signal not found.")
        if x["status"] in ("filled","skipped","expired"):
            raise HTTPException(409,detail="Signal is already finalized.")
        if status=="acknowledged" and datetime.fromisoformat(x["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(409,detail="Signal has expired.")
        conn.execute("UPDATE signals SET status=? WHERE id=?",(status,signal_id))
        conn.commit()
        return _one(conn,"SELECT * FROM signals WHERE id=?",(signal_id,))

def heartbeat():
    with LOCK,db() as conn:
        return _one(conn,"SELECT * FROM runtime WHERE name='worker_heartbeat'")

def status():
    now=datetime.now(timezone.utc)
    h=heartbeat()
    age=(now-datetime.fromisoformat(h["value"])).total_seconds() if h else None
    with LOCK,db() as conn:
        deployments_count=_one(conn,"SELECT COUNT(*) AS n FROM deployments WHERE state IN ('paper','live-monitor')")
        pending=_one(conn,"SELECT COUNT(*) AS n FROM signals WHERE status IN ('pending','acknowledged')")
        alert_count=_one(conn,"SELECT COUNT(*) AS n FROM alerts WHERE status='open' AND severity='critical'")
        evaluations=_rows(conn,"SELECT deployment_id,symbol,bar_time,result,evaluated_at FROM evaluations ORDER BY evaluated_at DESC LIMIT 20")
    return {"worker_online":age is not None and 0<=age<300,"heartbeat_age_seconds":age,
            "heartbeat_at":h["value"] if h else None,
            "active_deployments":deployments_count["n"],"pending_signals":pending["n"],
            "critical_alerts":alert_count["n"],"recent_evaluations":evaluations,
            "execution_mode":"human_confirmation_only","broker_connected":False}

def _set_heartbeat():
    now=_utc()
    with LOCK,db() as conn:
        conn.execute("INSERT INTO runtime(name,value) VALUES('worker_heartbeat',?) "
          "ON CONFLICT(name) DO UPDATE SET value=excluded.value",(now,))

def _evaluate_deployment(dep,now,source):
    from .market import history
    from .assets import get_instrument
    allowed=set(json.loads(dep["symbols"]))
    if dep["mode"]=="single":
        symbol=json.loads(dep["symbols"])[0]
        rules=[(symbol,symbol,r) for r in compile_rules(dep["code"])]
    else:
        rules=[(r.signal_id,r.target_id,r.rule) for r in compile_portfolio_rules(dep["code"],allowed)]
    resolution=dep.get("resolution","1d")
    step_seconds={"1d":86400,"1h":3600,"15m":900}[resolution]
    for source_symbol in sorted({a for a,_,_ in rules}):
        with LOCK,db() as conn:
            recent=_one(conn, "SELECT evaluated_at FROM evaluations WHERE deployment_id=? AND symbol=? ORDER BY evaluated_at DESC LIMIT 1",
                        (dep["id"],source_symbol))
            previous_issue=_one(conn, "SELECT last_seen_at FROM alerts WHERE key=? AND status='open'",
                                ("feed:"+dep["id"]+":"+source_symbol,))
        # Already evaluated this signal source today. Avoid needlessly hitting
        # Yahoo/Coinbase feeds every 90 seconds or emitting duplicate alerts.
        if (resolution=="1d" and recent and
            datetime.fromisoformat(recent["evaluated_at"]).astimezone(NY).date()==now.astimezone(NY).date()):
            continue
        # Persist error backoff across worker restarts.
        if previous_issue and now-datetime.fromisoformat(previous_issue["last_seen_at"])<timedelta(minutes=10):
            continue
        instrument=get_instrument(source_symbol)
        if instrument.kind not in ("Stocks","ETFs"):
            record_alert("unsupported:"+dep["id"]+":"+source_symbol,"warning",
                         "Unsupported live signal instrument",source_symbol+" is not a stock/ETF.")
            continue
        try:
            if resolution=="1d":
                response=source(source_symbol,"1Y")
            else:
                window="30D" if resolution=="15m" else "6M"
                if source is None:
                    from .intraday import replay_history
                    response=replay_history(source_symbol,window,resolution)
                else:
                    # Synthetic tests may provide an injectable OHLC provider
                    # matching the intraday replay_history call signature.
                    response=source(source_symbol,window,resolution)
            if response.get("is_demo") or response.get("offline_cache"):
                raise ValueError("Demo or offline cached candles are not acceptable for live signals")
            if resolution=="1d":
                bars=_last_complete(response["bars"],now)
            else:
                cutoff=now.timestamp()
                # A candle is final only after its full interval has elapsed.
                bars=[bar for bar in response["bars"]
                      if int(bar["time"])+step_seconds<=cutoff]
            if len(bars)<102:raise ValueError("Insufficient completed historical candles")
            latest=bars[-1]
            latest_date=datetime.fromtimestamp(latest["time"],NY).date()
            if resolution=="1d":
                age=(now.astimezone(NY).date()-latest_date).days
                if age>5 or age<1:raise ValueError("Last completed daily candle is stale")
            elif not 0<=now.timestamp()-int(latest["time"])<=max(3600,step_seconds*4):
                raise ValueError("The most recent completed intraday candle is stale")
            if latest["close"]<=0 or any(not math.isfinite(float(latest[k])) for k in ("open","high","low","close")):
                raise ValueError("Invalid candle OHLC")
            valid_rules=[(target,rule) for signal_id,target,rule in rules if signal_id==source_symbol]
            evaluations=[]
            for target,rule in valid_rules:
                hit=matches(rule,bars,len(bars)-1)
                lhs=indicator(rule.left,bars,len(bars)-1)
                rhs=indicator(rule.right,bars,len(bars)-1)
                evaluations.append((target,rule,hit,lhs,rhs))
            detail=[{"target":target,"line":rule.line,"match":hit,
                     "left":rule.left,"left_value":lhs,"right":rule.right,"right_value":rhs}
                    for target,rule,hit,lhs,rhs in evaluations]
            now_iso=now.isoformat()
            eval_id=str(uuid4())
            with LOCK,db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                # Never duplicate a decision on a service restart.
                existing=_one(conn,"SELECT id FROM evaluations WHERE deployment_id=? AND symbol=? AND bar_time=?",
                              (dep["id"],source_symbol,int(latest["time"])))
                if existing:
                    conn.rollback()
                    continue
                conn.execute("""INSERT INTO evaluations VALUES(?,?,?,?,?,?,?)""",
                             (eval_id,dep["id"],source_symbol,int(latest["time"]),now_iso,
                              "signal" if any(x[2] for x in evaluations) else "no-action",_json(detail)))
                day_start=now.astimezone(NY).date().isoformat()
                count=_one(conn,"SELECT COUNT(*) AS n FROM signals WHERE deployment_id=? AND substr(created_at,1,10)=?",
                           (dep["id"],now.date().isoformat()))["n"]
                for target,rule,hit,lhs,rhs in evaluations:
                    if not hit:continue
                    if count>=dep["max_daily_signals"]:
                        record_key="cap:"+dep["id"]+":"+day_start
                        # Store limit warning after transaction.
                        logger.warning("Daily signal cap reached: %s",record_key)
                        continue
                    allocation=min(float(rule.percent),float(dep["max_allocation_pct"]))
                    try:
                        forecast=probability_up(bars,20) if resolution=="1d" else None
                    except Exception:
                        forecast=None
                    conn.execute("""INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (str(uuid4()),dep["id"],eval_id,source_symbol,target,
                       rule.side,allocation,float(dep["capital"])*allocation/100,
                       float(latest["close"]),int(latest["time"]),now_iso,_next_expiry(now),
                       "pending",f"Rule {rule.line}: {rule.left} {rule.operator} {rule.right}; "
                       f"observed {lhs:.3f} vs {rhs:.3f} on completed {resolution} candle at "
                       f"{datetime.fromtimestamp(latest['time'],NY).isoformat()}. "
                       f"Indicative only; confirm live price and risk before executing.",
                       forecast))
                    count+=1
                conn.execute("UPDATE deployments SET last_evaluated_at=?,last_error=NULL WHERE id=?",(now_iso,dep["id"]))
                conn.commit()
            resolve_alert("feed:"+dep["id"]+":"+source_symbol)
        except Exception as exc:
            # Error details should never include private strategy text or credentials.
            detail=type(exc).__name__ + ": market data unavailable, stale or unsupported"
            with LOCK,db() as conn:
                conn.execute("UPDATE deployments SET last_error=? WHERE id=?",(detail,dep["id"]))
            record_alert("feed:"+dep["id"]+":"+source_symbol,"critical",
                         "Live market evaluation unavailable",
                         "No fresh signal will be created for "+source_symbol+". Verify data source and timestamps.")
            logger.warning("Private live evaluation failed for %s: %s",source_symbol,type(exc).__name__)

def run_once(now: datetime | None=None, source=None, worker_heartbeat: bool=False):
    """Check eligible signals, independently of browser or actual worker presence.

    The background worker alone updates its heartbeat. Manual API evaluation
    must never make a stopped worker appear healthy.
    """
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("Live strategy machine is prohibited in the public shared demo.")
    from .market import history
    now=now or datetime.now(timezone.utc)
    if worker_heartbeat:
        _set_heartbeat()
    with LOCK,db() as conn:
        dep_rows=_rows(conn,"SELECT * FROM deployments WHERE state IN ('paper','live-monitor')")
        conn.execute("UPDATE signals SET status='expired' WHERE status IN ('pending','acknowledged') AND expires_at < ?",(now.isoformat(),))
        expiring=_rows(conn,"SELECT id,asset_id,side,expires_at,status FROM signals WHERE status IN ('pending','acknowledged')")
    for sig in expiring:
        remaining=(datetime.fromisoformat(sig["expires_at"])-now).total_seconds()
        alert_key="unacknowledged:"+sig["id"]
        if sig["status"]=="pending" and 0<remaining<=3600:
            record_alert(alert_key,"critical","Time-sensitive trade recommendation unacknowledged",
                sig["side"].upper()+" "+sig["asset_id"].upper()+
                " expires within one hour. Review the signal and market before placing any trade.")
        else:
            resolve_alert(alert_key)
    # Conservative portfolio-level realized-loss fuse. Actual journal data is
    # entered by the user; unrealized positions and external broker balances are
    # not verified here. Pausing recommendations never sends broker orders.
    try:
        recorded=journal()
        usd_loss=recorded["realized_by_currency"].get("USD",0.)
        candidates=[]
        for dep in dep_rows:
            if usd_loss<=-dep["capital"]*dep["max_realized_loss_pct"]/100:
                change_state(dep["id"],"paused")
                record_alert("risk:loss:"+dep["id"],"critical",
                    "Realized-loss safety stop activated",
                    "Confirmed USD realized loss exceeded the configured threshold. "
                    "Strategy monitoring is paused; inspect the broker account and risk exposure.")
            else:
                candidates.append(dep)
        dep_rows=candidates
    except Exception as exc:
        record_alert("risk:journal","critical","Trade journal risk assessment failed",
                     "No new live recommendations until confirmed trade records can be assessed.")
        logger.warning("Risk fuse unavailable: %s",type(exc).__name__)
        dep_rows=[]
    # Run at a well-defined daily decision window, not continuously generating
    # new suggestions from unfinished intraday bars.
    local=now.astimezone(NY)
    if local.weekday()<5 and local.time()>=time(9,15) and local.time()<time(16):
        for dep in dep_rows:
            # A completed intraday candle can exist only after the 9:30
            # exchange open. Avoid stale-price alerts before first close.
            resolution=dep.get("resolution","1d")
            if resolution!="1d" and local.time()<time(10,0):
                continue
            _evaluate_deployment(dep,now,source if source is not None else
                                  (history if resolution=="1d" else None))
    return status()
