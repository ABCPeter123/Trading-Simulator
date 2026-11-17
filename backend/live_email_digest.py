"""Private local weekday email briefing for Trading Simulator.

Only the owner-configured SMTP transport sends. No browser, Vercel storage,
public repository artifact, broker orders, or external AI call is involved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
import os
from zoneinfo import ZoneInfo

from . import live_machine as machine
from . import live_notifications as notices
from . import research_optimizer
from . import strategy_library

LOCAL_TZ = ZoneInfo("America/Toronto")
MAX_ITEMS = 60


def _txt(value, missing="Not available"):
    if value is None or value == "":
        return missing
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _num(value, decimals=2):
    if value is None:
        return "Not available"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError, OverflowError):
        return "Not available"


def _date(value):
    if not value:
        return "Not available"
    try:
        parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if parsed.tzinfo is None:
            parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(LOCAL_TZ).strftime("%b %d, %Y %I:%M %p %Z")
    except ValueError:
        return "Not available"


def _lines(title, values, limit=MAX_ITEMS):
    result=list(values)
    visible=result[:limit]
    if len(result)>limit:
        visible.append(f"... plus {len(result)-limit} additional records in the private database")
    return (title, visible or ["None recorded"])


def build_report(now: datetime | None = None):
    """Return (subject, plain text, HTML); never dump private strategy code."""
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("Report clock must include a timezone")
    local=clock.astimezone(LOCAL_TZ)
    cutoff=(clock-timedelta(hours=24)).isoformat()
    status=machine.status()
    deployments=machine.deployments()
    journal=machine.journal()
    with machine.LOCK, machine.db() as conn:
        signals=machine._rows(conn,"SELECT * FROM signals ORDER BY created_at DESC LIMIT 501")
        alerts=machine._rows(conn,"SELECT * FROM alerts WHERE status='open' ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,last_seen_at DESC LIMIT 501")
        evals=machine._rows(conn,"SELECT * FROM evaluations ORDER BY evaluated_at DESC LIMIT 501")
        counts={
            "signals":machine._one(conn,"SELECT COUNT(*) n FROM signals WHERE created_at>=?",(cutoff,))["n"],
            "fills":machine._one(conn,"SELECT COUNT(*) n FROM fills WHERE executed_at>=?",(cutoff,))["n"],
            "evaluations":machine._one(conn,"SELECT COUNT(*) n FROM evaluations WHERE evaluated_at>=?",(cutoff,))["n"],
        }
    recent_signals=[s for s in signals if s["created_at"]>=cutoff]
    active_signals=[s for s in signals if s["status"] in ("pending","acknowledged") and s["expires_at"]>=clock.isoformat()]
    recent_fills=[f for f in journal["fills"] if f["executed_at"]>=cutoff]
    recent_evals=[e for e in evals if e["evaluated_at"]>=cutoff]
    positions=[p for p in journal["positions"] if p["quantity"]>0]
    critical=[a for a in alerts if a["severity"]=="critical"]
    attention=[f"CRITICAL: {a['title']}: {_txt(a['detail'])}" for a in critical[:20]]
    attention.extend([f"{s['side'].upper()} {s['asset_id'].upper()} - { _num(s['allocation_pct']) }% allocation cap; expires {_date(s['expires_at'])}"
                      for s in active_signals[:25]])
    if not status["worker_online"]:
        attention.insert(0,"Live strategy worker has no recent heartbeat. Scheduled evaluations may be delayed.")
    if not attention:
        attention=["No open critical alerts or unexpired pending trading signals."]

    sections=[]
    sections.append(_lines("ACTION REQUIRED",attention,50))
    sections.append(_lines("SYSTEM AND MARKET-DATA HEALTH",[
        f"Generated: {local.strftime('%b %d, %Y %I:%M %p %Z')}",
        f"Worker: {'ONLINE' if status['worker_online'] else 'OFFLINE / STALE'}; last heartbeat {_date(status['heartbeat_at'])}",
        f"Active deployments: {status['active_deployments']}; open critical alerts: {status['critical_alerts']}; pending/acknowledged signals: {status['pending_signals']}",
        f"Last 24h: {counts['evaluations']} evaluations, {counts['signals']} new signals, {counts['fills']} manually recorded fills",
        "Market inputs can be delayed. Freshness failures are recorded as alerts; these are not guaranteed live quotes.",
        "Broker connection: NONE. Orders require manual execution and confirmed records.",
    ]))
    sections.append(_lines("ACTIVE STRATEGIES AND RISK SETTINGS",[
        f"{d['name']} | {d['state']} | {', '.join(d['symbols'])} | reference capital {_num(d['capital'])} | max allocation {_num(d['max_allocation_pct'])}% | loss fuse {_num(d.get('max_realized_loss_pct'))}% | daily signal cap {d['max_daily_signals']} | last evaluation {_date(d['last_evaluated_at'])} | issue {_txt(d.get('last_error'),'none')}"
        for d in deployments if d["state"]!="retired"
    ]))
    sections.append(_lines("PENDING AND RECENT TRADING SIGNALS",[
        f"{s['side'].upper()} {s['asset_id'].upper()} | {s['status']} | reference {_num(s['price_reference'],4)} | allocation cap {_num(s['allocation_pct'])}% | suggested notional {_num(s.get('suggested_notional'))} | issued {_date(s['created_at'])} | expires {_date(s['expires_at'])} | forecast P(up) {_num(s.get('forecast_prob_up_pct'))}% | rationale {_txt(s.get('rationale'))}"
        for s in signals if s in active_signals or s in recent_signals
    ]))
    sections.append(_lines("OPEN SYSTEM AND RISK ALERTS",[
        f"{a['severity'].upper()} | {a['title']} | {_txt(a['detail'])} | last seen {_date(a['last_seen_at'])} | status {a['status']}"
        for a in alerts
    ]))
    sections.append(_lines("CONFIRMED POSITIONS (MANUAL JOURNAL ONLY)",[
        f"{p['asset_id'].upper()} | {p['currency']} | quantity {_num(p['quantity'],6)} | avg cost {_num(p['average_cost'],4)} | realized P/L {_num(p['realized_pnl'])}"
        for p in positions
    ]))
    pnl=journal["realized_by_currency"]
    sections.append(_lines("REALIZED PERFORMANCE AND VALUATION LIMITATIONS",
        [f"Confirmed realized P/L in {currency}: {_num(amount)}" for currency,amount in sorted(pnl.items())]+[
        "Unrealized P/L, current market value, time-weighted return, live portfolio NAV and broker cash balances are NOT computed by this worker.",
        "The confirmed trade journal is not automatically synchronized with a brokerage account.",
        "Currencies are never combined without verified FX rates.",
    ]))
    sections.append(_lines("MANUALLY RECORDED TRADES (LAST 24 HOURS)",[
        f"{f['side'].upper()} {f['asset_id'].upper()} | {_num(f['quantity'],6)} @ {_num(f['price'],4)} {f['currency']} | notional {_num(float(f['quantity'])*float(f['price']))} | fee {_num(f['fee'])} | executed {_date(f['executed_at'])} | linked signal {'yes' if f['signal_id'] else 'no'}"
        for f in recent_fills
    ]))
    sections.append(_lines("EXECUTION QUALITY REVIEWS",[
        f"{x['side'].upper()} {x['asset_id'].upper()} | execution price deviation {_num(x['price_deviation_pct'])}% | delay {_num(x['execution_delay_hours'])}h | expired {'YES' if x['after_signal_expiry'] else 'no'} | different symbol/side {'YES' if x['different_asset_or_side'] else 'no'}"
        for x in journal["execution_reviews"] if any(f["id"]==x["fill_id"] for f in recent_fills)
    ]))
    sections.append(_lines("LATEST STRATEGY EVALUATIONS",[
        f"{e['symbol'].upper()} | result {_txt(e['result'])} | input candle {e['bar_time']} (Unix seconds UTC) | evaluated {_date(e['evaluated_at'])}"
        for e in recent_evals
    ]))

    # Saved strategy source code and broker identifiers are deliberately omitted.
    # Owners still receive names, progress, risk settings and trading decisions.
    try:
        saved=strategy_library.list_saved()
        sections.append(_lines("SAVED RESEARCH STRATEGIES",[
            f"{r['name']} | {r['mode']} | {', '.join(r['symbols'])} | saved {_date(r['created_at'])}"
            for r in saved
        ]))
    except Exception:
        sections.append(("SAVED RESEARCH STRATEGIES",["Unavailable; check the local library database."]))
    try:
        runs=research_optimizer.list_runs(limit=20)
        sections.append(_lines("RECENT STRATEGY OPTIMIZATION RUNS",[
            f"{r['asset_id'].upper()} | {_date(r['created_at'])} | {r['candidate_count']} candidates, {r['eligible_count']} eligible | selected {('fast '+str(r['selected']['fast'])+', slow '+str(r['selected']['slow'])) if r['selected'] else 'none'}"
            for r in runs
        ]))
    except Exception:
        sections.append(("RECENT STRATEGY OPTIMIZATION RUNS",["Unavailable; check the local research database."]))
    sections.append(_lines("INTERPRETATION",[
        "Signals are recommendations only, not broker executions.",
        "Performance figures include only manually recorded confirmed fills. Simulated backtests are not actual returns.",
        "Times are in Toronto local time unless a Unix timestamp is explicitly shown.",
        "This report was created from the private Windows trading database, not the hosted website.",
    ]))

    subject=f"Daily trading briefing | {local.strftime('%Y-%m-%d')} | {len(critical)} critical | {len(active_signals)} active signals"
    lines=[f"TRADING SIMULATOR | PRIVATE DAILY BRIEFING | {local.strftime('%Y-%m-%d %I:%M %p %Z')}",""]
    for title,items in sections:
        lines.extend([title,"="*len(title)])
        lines.extend("  "+item for item in items)
        lines.append("")
    plain="\n".join(lines)
    cards=[]
    for title,items in sections:
        lis="".join("<li style='padding:6px 0;border-bottom:1px solid #e5e7eb;overflow-wrap:anywhere;'>"+
                    escape(item)+"</li>" for item in items)
        cards.append("<section style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:18px;margin:16px 0'>"+
                     "<h2 style='font:600 16px Arial,sans-serif;color:#111827'>"+escape(title)+"</h2>"+
                     "<ul style='list-style:none;padding:0;margin:0'>"+lis+"</ul></section>")
    html=("<!DOCTYPE html><html><body style='background:#f5f7fb;color:#1f2937;margin:0;padding:20px;"
          "font:14px/1.5 Arial,sans-serif'><main style='max-width:800px;margin:auto'>"
          "<h1 style='font-size:24px'>Trading Simulator: private daily briefing</h1>"
          "<p>"+escape(local.strftime('%b %d, %Y %I:%M %p %Z'))+"</p>"+
          "".join(cards)+"</main></body></html>")
    return subject,plain,html


def maybe_send_daily(now: datetime | None=None):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("No private email reports may be sent from a shared demo")
    if os.environ.get("TRADING_SIM_EMAIL_DIGEST_ENABLED","1").lower() in ("0","false","no"):
        return False
    if "email" not in notices._channels():
        return False
    clock=now or datetime.now(timezone.utc)
    local=clock.astimezone(LOCAL_TZ)
    if local.weekday()>4:
        return False
    schedule=os.environ.get("TRADING_SIM_EMAIL_DIGEST_TIME","17:15")
    try:
        hour,minute=[int(x) for x in schedule.split(":")]
        if not 0<=hour<=23 or not 0<=minute<=59:raise ValueError()
    except ValueError:
        raise ValueError("Digest time must be 24-hour HH:MM in Toronto local time") from None
    if (local.hour,local.minute)<(hour,minute):
        return False
    subject,plain,html=build_report(clock)
    key="digest:"+local.date().isoformat()
    notices._deliver_one(key,subject,plain,only_channel="email",html=html)
    return True


def send_now():
    """One owner-confirmed report to all private email recipients."""
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("Cannot send in demo mode")
    if "email" not in notices._channels():
        raise ValueError("Configure private SMTP and email recipients")
    subject,plain,html=build_report()
    notices._send_email(subject,plain,html)
