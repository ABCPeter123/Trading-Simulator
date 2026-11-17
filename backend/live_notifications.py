"""Local-only notification dispatcher. No paid service or cloud database required.

Discord webhook or SMTP email configured through private environment variables.
Persistent delivery receipts and retries prevent duplicate ordinary alerts.
Critical alerts repeat after cooldown while unresolved/unacknowledged.
"""
from __future__ import annotations

import os
import smtplib
import sqlite3
import ssl
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from urllib.parse import urlparse

import httpx

from . import live_machine as m

def _channels():
    channels=[]
    if os.environ.get("TRADING_SIM_DISCORD_WEBHOOK", "").strip():
        channels.append("discord")
    if os.environ.get("TRADING_SIM_SMTP_HOST","") and os.environ.get("TRADING_SIM_EMAIL_TO",""):
        channels.append("email")
    return channels

def _send(channel: str, title: str, message: str):
    if channel=="discord":
        url=os.environ["TRADING_SIM_DISCORD_WEBHOOK"].strip()
        parsed=urlparse(url)
        if parsed.scheme!="https" or parsed.hostname not in ("discord.com","discordapp.com") or not parsed.path.startswith("/api/webhooks/"):
            raise ValueError("Invalid Discord webhook host")
        r=httpx.post(url,json={"content":title+"\n"+message},timeout=12)
        r.raise_for_status()
    elif channel=="email":
        host=os.environ["TRADING_SIM_SMTP_HOST"]
        port=int(os.environ.get("TRADING_SIM_SMTP_PORT","465"))
        sender=os.environ.get("TRADING_SIM_EMAIL_FROM") or os.environ.get("TRADING_SIM_SMTP_USER","")
        target=os.environ["TRADING_SIM_EMAIL_TO"]
        if not sender or not target:raise ValueError("Email sender and recipient required")
        letter=EmailMessage()
        letter["From"]=sender;letter["To"]=target
        letter["Subject"]="Trading Simulator: "+title
        letter.set_content(message)
        if port==465:
            with smtplib.SMTP_SSL(host,port,timeout=15,context=ssl.create_default_context()) as smtp:
                if os.environ.get("TRADING_SIM_SMTP_USER"):
                    smtp.login(os.environ["TRADING_SIM_SMTP_USER"],os.environ["TRADING_SIM_SMTP_PASSWORD"])
                smtp.send_message(letter)
        else:
            with smtplib.SMTP(host,port,timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if os.environ.get("TRADING_SIM_SMTP_USER"):
                    smtp.login(os.environ["TRADING_SIM_SMTP_USER"],os.environ["TRADING_SIM_SMTP_PASSWORD"])
                smtp.send_message(letter)
    else:
        raise ValueError("Unknown notification channel")

def _init(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS deliveries (
      key TEXT NOT NULL, channel TEXT NOT NULL, delivered_at TEXT,
      attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
      PRIMARY KEY(key,channel))""")

def _deliver_one(key, title, text, repeat_after_min=0):
    now=datetime.now(timezone.utc)
    for channel in _channels():
        # Claims are reserved with a transaction, preventing multiple worker
        # processes from sending the same regular message concurrently.
        with m.LOCK,m.db() as conn:
            _init(conn)
            conn.execute("BEGIN IMMEDIATE")
            old=m._one(conn,"SELECT * FROM deliveries WHERE key=? AND channel=?",(key,channel))
            last=datetime.fromisoformat(old["delivered_at"]) if old and old["delivered_at"] else None
            if last and (not repeat_after_min or now-last<timedelta(minutes=repeat_after_min)):
                conn.rollback()
                continue
            conn.execute("""INSERT INTO deliveries(key,channel,attempts)
              VALUES(?,?,1) ON CONFLICT(key,channel)
              DO UPDATE SET attempts=deliveries.attempts+1""",(key,channel))
            conn.commit()
        try:
            _send(channel,title,text)
            with m.LOCK,m.db() as conn:
                _init(conn)
                conn.execute("UPDATE deliveries SET delivered_at=?,last_error=NULL WHERE key=? AND channel=?",
                             (now.isoformat(),key,channel))
        except Exception as exc:
            # Never put private webhook URL, SMTP password, or strategy text in
            # exception details exposed by monitoring APIs.
            with m.LOCK,m.db() as conn:
                _init(conn)
                conn.execute("UPDATE deliveries SET last_error=? WHERE key=? AND channel=?",
                    (type(exc).__name__,key,channel))
            m.logger.warning("Notification delivery failed: %s",type(exc).__name__)

def deliver_pending():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("Never send owner notifications from a shared demo.")
    with m.LOCK,m.db() as conn:
        pending=m._rows(conn,"SELECT * FROM signals WHERE status='pending' ORDER BY created_at DESC LIMIT 20")
        alerts=m._rows(conn,"SELECT * FROM alerts WHERE status='open' ORDER BY created_at DESC LIMIT 30")
    for sig in pending:
        if datetime.fromisoformat(sig["expires_at"]) < datetime.now(timezone.utc):continue
        title=f"Review {sig['side'].upper()} signal for {sig['asset_id'].upper()}"
        text=(f"Signal: {sig['side'].upper()} {sig['asset_id'].upper()}, "
              f"allocation cap {sig['allocation_pct']:.2f}% of reference capital. "
              f"Reference price {sig['price_reference']:.4f}. "
              f"Valid until {sig['expires_at']}. Human broker execution required. "
              f"Open your private Trading Simulator to acknowledge and record execution.")
        _deliver_one("signal:"+sig["id"],title,text)
    for alert in alerts:
        interval=15 if alert["severity"]=="critical" else 0
        _deliver_one("alert:"+alert["id"],alert["severity"].upper()+": "+alert["title"],
                     alert["detail"],repeat_after_min=interval)

def delivery_status():
    with m.LOCK,m.db() as conn:
        _init(conn)
        rows=m._rows(conn,"SELECT key,channel,delivered_at,attempts,last_error FROM deliveries ORDER BY rowid DESC LIMIT 100")
    return {"channels":_channels(),"deliveries":rows}
