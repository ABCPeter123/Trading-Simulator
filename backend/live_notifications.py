"""Local-only notification dispatcher. No paid service or cloud database required.

Discord, SMTP email, or opt-in BlueBubbles iMessage through private variables.
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
from email.utils import getaddresses
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from . import live_machine as m

def _channels():
    channels=[]
    selected={x.strip().lower() for x in os.environ.get('TRADING_SIM_NOTIFICATION_CHANNELS','').split(',') if x.strip()}
    if os.environ.get("TRADING_SIM_DISCORD_WEBHOOK", "").strip():
        channels.append("discord")
    if os.environ.get("TRADING_SIM_SMTP_HOST","") and os.environ.get("TRADING_SIM_EMAIL_TO",""):
        channels.append("email")
    if all(os.environ.get(k, "").strip() for k in (
        "TRADING_SIM_IMESSAGE_SERVER_URL",
        "TRADING_SIM_IMESSAGE_PASSWORD",
        "TRADING_SIM_IMESSAGE_CHAT_GUID",
    )):
        channels.append("imessage")
    return [c for c in channels if not selected or c in selected]

def _email_targets():
    raw=os.environ.get("TRADING_SIM_EMAIL_TO","")
    if "\r" in raw or "\n" in raw:
        raise ValueError("Invalid private notification recipient")
    recipients=getaddresses([raw.replace(";",",")])
    result=[]
    for _,addr in recipients:
        if not addr or addr.count("@")!=1 or any(c.isspace() for c in addr):
            raise ValueError("Invalid private notification recipient")
        if addr not in result:result.append(addr)
    if not result:raise ValueError("At least one email recipient is required")
    return result

class SMTPDeliveryFailure(RuntimeError):
    """Credential-free, recipient-free failure classification for the owner."""
    def __init__(self, stage: str, port: int, cause: str):
        self.stage = stage
        self.port = port
        self.cause = cause
        super().__init__(f"{stage} on port {port} ({cause})")


def _smtp_connect_and_auth(host: str, port: int, user: str, password: str):
    """Both supported paths require authenticated server TLS certificates.

    Never catch and print raw server replies, which may contain sensitive
    recipient or account information. Close sockets without using QUIT, which
    can fail after a successful send and falsely imply nondelivery.
    """
    smtp = None
    stage = "connect"
    try:
        context = ssl.create_default_context()
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        elif port == 587:
            smtp = smtplib.SMTP(host, port, timeout=30)
            stage = "starttls"
            smtp.starttls(context=context)
        else:
            raise ValueError("SMTP requires TLS on port 465 or 587")
        # Separate SMTP greeting/capability negotiation from authentication:
        # previously, a dropped EHLO was incorrectly reported as login failure.
        stage = "ehlo"
        code, _ = smtp.ehlo()
        if code != 250:
            raise SMTPDeliveryFailure("ehlo", port, "UnexpectedReply")
        if user:
            stage = "authenticate"
            smtp.login(user, password)
        return smtp
    except (smtplib.SMTPException, OSError) as exc:
        if smtp is not None:
            try:
                smtp.close()
            except Exception:
                pass
        raise SMTPDeliveryFailure(stage, port, type(exc).__name__) from None


def _send_email(title: str, body: str, html_body: str | None = None):
    host = os.environ["TRADING_SIM_SMTP_HOST"].strip()
    port = int(os.environ.get("TRADING_SIM_SMTP_PORT", "465"))
    sender = (os.environ.get("TRADING_SIM_EMAIL_FROM")
              or os.environ.get("TRADING_SIM_SMTP_USER", "")).strip()
    if not host or not sender or any(c.isspace() for c in sender) or port not in (465, 587):
        raise ValueError("Invalid SMTP sender or port")
    targets = _email_targets()
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(targets)
    msg["Subject"] = "Trading Simulator: " + title.replace(chr(13), " ").replace(chr(10), " ")[:160]
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    user = os.environ.get("TRADING_SIM_SMTP_USER", "").strip()
    password = os.environ.get("TRADING_SIM_SMTP_PASSWORD", "")
    if host.lower() == "smtp.gmail.com":
        if not user or not password:
            raise ValueError("Gmail requires an authenticated SMTP sender and app password")
        # Google sometimes visually groups its 16-character app password.
        compact = "".join(password.split())
        if len(compact) != 16:
            raise ValueError("Gmail app password must contain 16 characters")
        password = compact

    try_ports = [port]
    # Port 587 with STARTTLS is an encrypted fallback if Gmail's implicit TLS
    # connection fails BEFORE authentication and BEFORE submitting a message.
    if host.lower() == "smtp.gmail.com" and port == 465:
        try_ports.append(587)
    for number, trial_port in enumerate(try_ports):
        try:
            smtp = _smtp_connect_and_auth(host, trial_port, user, password)
        except SMTPDeliveryFailure as exc:
            if number + 1 < len(try_ports) and exc.stage in ("connect", "starttls"):
                continue
            raise
        try:
            # Do not retry on failures during or after DATA. The remote server
            # might have accepted the message even if its reply was lost.
            refused = smtp.send_message(msg, to_addrs=targets)
            if refused:
                raise SMTPDeliveryFailure("deliver", trial_port, "RecipientRefused")
            return
        except SMTPDeliveryFailure:
            raise
        except (smtplib.SMTPException, OSError) as exc:
            raise SMTPDeliveryFailure("deliver", trial_port, type(exc).__name__) from None
        finally:
            # No QUIT call on exit: QUIT failures after sending must not
            # turn a successful delivery into an apparent failed attempt.
            try:
                smtp.close()
            except Exception:
                pass


def _send(channel: str, title: str, message: str):
    if channel=="discord":
        url=os.environ["TRADING_SIM_DISCORD_WEBHOOK"].strip()
        parsed=urlparse(url)
        if parsed.scheme!="https" or parsed.hostname not in ("discord.com","discordapp.com") or not parsed.path.startswith("/api/webhooks/"):
            raise ValueError("Invalid Discord webhook host")
        r=httpx.post(url,json={"content":title+"\n"+message},timeout=12)
        r.raise_for_status()
    elif channel=="email":
        _send_email(title,message)
    elif channel=="imessage":
        _send_imessage(title,message)
    else:
        raise ValueError("Unknown notification channel")

def _send_imessage(title: str, message: str):
    """Send an owner-approved notification through a Mac BlueBubbles server.

    BlueBubbles' documented API requires the Mac server password as a URL query
    parameter. Only HTTPS and a user-configured host are allowed; no redirects,
    URL fragments, embedded credentials, or arbitrary paths are accepted.
    Vercel never sees this password or the message.
    """
    base=os.environ["TRADING_SIM_IMESSAGE_SERVER_URL"].strip().rstrip("/")
    password=os.environ["TRADING_SIM_IMESSAGE_PASSWORD"].strip()
    chat=os.environ["TRADING_SIM_IMESSAGE_CHAT_GUID"].strip()
    parsed=urlparse(base)
    if (parsed.scheme!="https" or not parsed.hostname or parsed.username or
        parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("iMessage relay must be an HTTPS origin without credentials")
    # Explicitly prohibit automatic SMS fallback. The owner must choose an
    # existing iMessage chat on the paired Mac, not an arbitrary contact.
    if (not chat.startswith(("iMessage;-;", "iMessage;+;")) or
        len(chat)>256 or len(chat)<12 or not password):
        raise ValueError("An existing iMessage chat GUID and relay password are required")
    if os.environ.get("TRADING_SIM_IMESSAGE_INCLUDE_DETAILS")=="1":
        # Explicit opt-in: messaging providers will process these details.
        content=("Trading Simulator: "+title+"\n"+message)[:1500]
    elif title.upper().startswith("CRITICAL:"):
        content="Trading Simulator: Critical alert. Open your private workspace to review and acknowledge."
    else:
        content="Trading Simulator: A trading action or system alert needs review in your private workspace."
    # BlueBubbles' REST API accepts chatGuid, tempGuid, and message in JSON.
    # Its password query param may be visible to the owner's Mac proxy logs;
    # never include it in our own errors, delivery receipts, or application logs.
    response=httpx.post(base+"/api/v1/message/text",
        params={"password":password},
        json={"chatGuid":chat,"tempGuid":"ts-"+uuid4().hex,"message":content},
        timeout=15,follow_redirects=False,trust_env=False)
    if not 200<=response.status_code<300:
        raise RuntimeError("iMessage relay returned a non-success HTTP status")
    try:
        result=response.json()
    except ValueError:
        raise RuntimeError("iMessage relay returned an invalid response") from None
    if (not isinstance(result,dict) or
        not isinstance(result.get("status"),int) or
        result["status"]<200 or result["status"]>=300 or result.get("error")):
        raise RuntimeError("iMessage relay did not confirm the send")

def _init(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS deliveries (
      key TEXT NOT NULL, channel TEXT NOT NULL, delivered_at TEXT,
      attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
      PRIMARY KEY(key,channel))""")

def _deliver_one(key, title, text, repeat_after_min=0, only_channel=None, html=None):
    now=datetime.now(timezone.utc)
    for channel in _channels():
        if only_channel and channel!=only_channel:continue
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
            if html is not None and channel=='email':
                _send_email(title,text,html)
            else:
                _send(channel,title,text)
            with m.LOCK,m.db() as conn:
                _init(conn)
                conn.execute("UPDATE deliveries SET delivered_at=?,last_error=NULL WHERE key=? AND channel=?",
                             (now.isoformat(),key,channel))
        except Exception as exc:
            # Only report fixed stage/port/class names, never raw server
            # replies, recipient addresses, passwords or strategy content.
            safe_error=(f"SMTP:{exc.stage}:{exc.port}:{exc.cause}"
                        if isinstance(exc, SMTPDeliveryFailure)
                        else type(exc).__name__)
            with m.LOCK,m.db() as conn:
                _init(conn)
                conn.execute("UPDATE deliveries SET last_error=? WHERE key=? AND channel=?",
                    (safe_error,key,channel))
            m.logger.warning("Notification delivery failed: %s",safe_error)

def deliver_pending():
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("Never send owner notifications from a shared demo.")
    with m.LOCK,m.db() as conn:
        pending=m._rows(conn,"SELECT * FROM signals WHERE status='pending' ORDER BY created_at DESC LIMIT 20")
        alerts=m._rows(conn,"SELECT * FROM alerts WHERE status='open' ORDER BY created_at DESC LIMIT 30")
    for sig in pending:
        if datetime.fromisoformat(sig["expires_at"]) < datetime.now(timezone.utc):continue
        title=f"Review {sig['side'].upper()} signal for {sig['asset_id'].upper()}"
        text=(f"TRADING ACTION: {sig['side'].upper()} {sig['asset_id'].upper()}\n"
              f"Status: {sig['status']}\n"
              f"Suggested allocation limit: {sig['allocation_pct']:.2f}% of reference capital\n"
              f"Reference price: {sig['price_reference']:.4f}\n"
              f"Suggested notional: {sig['suggested_notional'] if sig['suggested_notional'] is not None else 'Unavailable'}\n"
              f"Forecast probability of price increase: {sig['forecast_prob_up_pct'] if sig['forecast_prob_up_pct'] is not None else 'Unavailable'}%\n"
              f"Signal created: {sig['created_at']}\n"
              f"Valid until: {sig['expires_at']}\n"
              f"Strategy rationale: {sig['rationale']}\n"
              "This is a strategy recommendation, not a broker order. "
              "Review and execute manually if appropriate. Record any actual fill separately.")
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
