"""Synthetic-only email briefing tests. No actual email, owner addresses or strategy data."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from backend import live_machine as machine
from backend import live_notifications as notices
from backend import live_email_digest as digest
from backend import research_optimizer
from backend import strategy_library


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(machine,"DB_PATH",tmp_path/"live.sqlite3")
    monkeypatch.setattr(research_optimizer,"DB_PATH",tmp_path/"research.sqlite3")
    monkeypatch.setattr(strategy_library,"DB_PATH",tmp_path/"strategies.sqlite3")
    for key in (
        "TRADING_SIM_IMESSAGE_SERVER_URL","TRADING_SIM_IMESSAGE_PASSWORD",
        "TRADING_SIM_IMESSAGE_CHAT_GUID","TRADING_SIM_DISCORD_WEBHOOK",
        "TRADING_SIM_PUBLIC_DEMO",
    ):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv("TRADING_SIM_NOTIFICATION_CHANNELS","email")
    monkeypatch.setenv("TRADING_SIM_SMTP_HOST","smtp.gmail.com")
    monkeypatch.setenv("TRADING_SIM_SMTP_PORT","465")
    monkeypatch.setenv("TRADING_SIM_SMTP_USER","sender@example.invalid")
    monkeypatch.setenv("TRADING_SIM_SMTP_PASSWORD","fictional-app-password")
    monkeypatch.setenv("TRADING_SIM_EMAIL_FROM","sender@example.invalid")
    monkeypatch.setenv("TRADING_SIM_EMAIL_TO","first@example.invalid, second@example.invalid")
    monkeypatch.setenv("TRADING_SIM_EMAIL_DIGEST_ENABLED","1")
    monkeypatch.setenv("TRADING_SIM_EMAIL_DIGEST_TIME","17:15")
    return tmp_path


def test_email_recipients_and_html_are_sent_together(workspace,monkeypatch):
    messages=[]
    class FakeSMTP:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def login(self,user,password):
            assert user=="sender@example.invalid"
            assert password=="fictional-app-password"
        def send_message(self,msg,to_addrs=None):
            messages.append((msg,to_addrs))
    monkeypatch.setattr(notices.smtplib,"SMTP_SSL",FakeSMTP)
    notices._send_email("Test subject","Text version","<h1>HTML version</h1>")
    assert len(messages)==1
    msg,targets=messages[0]
    assert targets==["first@example.invalid","second@example.invalid"]
    assert msg.get_body(preferencelist=("plain",)).get_content().strip()=="Text version"
    assert "HTML version" in msg.get_body(preferencelist=("html",)).get_content()
    assert msg["To"]=="first@example.invalid, second@example.invalid"


def test_email_only_prevents_discord_and_imessage(workspace,monkeypatch):
    monkeypatch.setenv("TRADING_SIM_DISCORD_WEBHOOK","https://discord.com/api/webhooks/fiction/fiction")
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_SERVER_URL","https://relay.invalid")
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_PASSWORD","fictional")
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_CHAT_GUID","iMessage;-;fixture@example.invalid")
    assert notices._channels()==["email"]


def test_report_includes_risk_actions_confirmed_trades_but_no_source_code(workspace):
    machine.record_alert("fixture:critical","critical","Review <unsafe>","Synthetic risk <script>")
    now=datetime.now(timezone.utc)
    machine.record_fill({
        "asset_id":"spy","side":"buy","quantity":3,"price":100.0,
        "fee":1.25,"currency":"USD","executed_at":now.isoformat(),
    })
    # The saved algorithm remains in the private database, not a portable email.
    strategy_library.store("single","Synthetic Alpha",
        "WHEN SMA(2) CROSSES ABOVE SMA(3) BUY 20%",["spy"])
    title,plain,html=digest.build_report(now)
    assert "ACTION REQUIRED" in plain
    assert "Synthetic risk <script>" in plain
    assert "SPY | USD" in plain
    assert "3.000000" in plain
    assert "Confirmed realized P/L in USD" in plain
    assert "Unrealized P/L" in plain
    assert "Synthetic Alpha" in plain
    assert "WHEN SMA(2) CROSSES ABOVE" not in plain
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "Daily trading briefing" in title


def test_daily_digest_runs_after_cutoff_once_and_not_weekends(workspace,monkeypatch):
    sent=[]
    monkeypatch.setattr(notices,"_send_email",lambda subject,text,html:sent.append((subject,text,html)))
    before=datetime(2026,11,17,21,00,tzinfo=timezone.utc) # 16:00 Toronto
    after=datetime(2026,11,17,23,00,tzinfo=timezone.utc) # 18:00 Toronto
    saturday=datetime(2026,11,21,23,00,tzinfo=timezone.utc)
    assert digest.maybe_send_daily(before) is False
    assert len(sent)==0
    assert digest.maybe_send_daily(after) is True
    assert digest.maybe_send_daily(after+timedelta(minutes=1)) is True
    assert len(sent)==1
    assert "2026-11-17" in sent[0][0]
    assert digest.maybe_send_daily(saturday) is False
    rows=notices.delivery_status()["deliveries"]
    assert any(x["key"]=="digest:2026-11-17" and x["channel"]=="email" and x["attempts"]==1 for x in rows)


def test_email_digest_disabled_and_demo_mode_fail_closed(workspace,monkeypatch):
    clock=datetime(2026,11,17,23,00,tzinfo=timezone.utc)
    monkeypatch.setenv("TRADING_SIM_EMAIL_DIGEST_ENABLED","0")
    assert digest.maybe_send_daily(clock) is False
    monkeypatch.setenv("TRADING_SIM_PUBLIC_DEMO","1")
    with pytest.raises(RuntimeError):
        digest.maybe_send_daily(clock)
    with pytest.raises(RuntimeError):
        digest.send_now()


@pytest.mark.parametrize("bad",["a@example.invalid\nb@example.invalid","nobody",""])
def test_invalid_targets_rejected(workspace,monkeypatch,bad):
    monkeypatch.setenv("TRADING_SIM_EMAIL_TO",bad)
    with pytest.raises(ValueError):
        notices._email_targets()


def test_gmail_falls_back_from_disconnected_ssl_to_starttls_before_login(workspace,monkeypatch):
    calls=[]
    class FailedSSL:
        def __init__(self,*args,**kwargs):
            calls.append(("ssl_connect",args[1]))
            raise __import__("smtplib").SMTPServerDisconnected("fake server drop")
    class FakeSTARTTLS:
        def __init__(self,*args,**kwargs):
            calls.append(("starttls_connect",args[1]))
        def starttls(self,context):
            calls.append(("tls",True))
        def login(self,username,password):
            calls.append(("login",password))
        def send_message(self,msg,to_addrs):
            calls.append(("send",tuple(to_addrs)))
            return {}
        def close(self):
            calls.append(("close",True))
    monkeypatch.setattr(notices.smtplib,"SMTP_SSL",FailedSSL)
    monkeypatch.setattr(notices.smtplib,"SMTP",FakeSTARTTLS)
    notices._send_email("Synthetic","Data")
    assert calls[0]==("ssl_connect",465)
    assert ("starttls_connect",587) in calls
    assert ("tls",True) in calls
    assert ("send",("first@example.invalid","second@example.invalid")) in calls


def test_smtp_authentication_failure_does_not_try_other_port(workspace,monkeypatch):
    calls=[]
    class Rejected:
        def __init__(self,*args,**kwargs):
            calls.append("connect")
        def login(self,username,password):
            calls.append("login")
            raise __import__("smtplib").SMTPAuthenticationError(535,b"mocked-secret-never-log")
        def close(self):
            calls.append("close")
    monkeypatch.setattr(notices.smtplib,"SMTP_SSL",Rejected)
    monkeypatch.setattr(notices.smtplib,"SMTP",lambda *args,**kwargs:
                        pytest.fail("Must not retry authentication failure"))
    with pytest.raises(notices.SMTPDeliveryFailure) as error:
        notices._send_email("Synthetic","Data")
    assert error.value.stage=="authenticate"
    assert error.value.port==465
    assert "mocked-secret" not in str(error.value)
    assert calls==["connect","login","close"]


def test_no_resend_or_false_failure_after_successful_send(workspace,monkeypatch):
    sends=[]
    class SuccessThenQuitWouldFail:
        def __init__(self,*args,**kwargs):pass
        def login(self,username,password):pass
        def send_message(self,msg,to_addrs):
            sends.append(True)
            return {}
        def close(self):
            raise __import__("smtplib").SMTPServerDisconnected("fake QUIT failure")
    monkeypatch.setattr(notices.smtplib,"SMTP_SSL",SuccessThenQuitWouldFail)
    monkeypatch.setattr(notices.smtplib,"SMTP",lambda *a,**k:
                        pytest.fail("Must not send again"))
    notices._send_email("Synthetic","Data")
    assert len(sends)==1


def test_no_fallback_after_delivery_stage_disconnection(workspace,monkeypatch):
    sends=[]
    class LostDeliveryReply:
        def __init__(self,*args,**kwargs):pass
        def login(self,username,password):pass
        def send_message(self,msg,to_addrs):
            sends.append(True)
            raise __import__("smtplib").SMTPServerDisconnected("could have been accepted")
        def close(self):pass
    monkeypatch.setattr(notices.smtplib,"SMTP_SSL",LostDeliveryReply)
    monkeypatch.setattr(notices.smtplib,"SMTP",lambda *a,**k:
                        pytest.fail("Never retry after DATA could be accepted"))
    with pytest.raises(notices.SMTPDeliveryFailure) as error:
        notices._send_email("Synthetic","Data")
    assert error.value.stage=="deliver"
    assert sends==[True]


def test_gmail_app_password_with_visual_spaces_is_normalized_only_for_sixteen_characters(workspace,monkeypatch):
    captured=[]
    class Fake:
        def __init__(self,*args,**kwargs):pass
        def login(self,user,password):
            captured.append(password)
        def send_message(self,msg,to_addrs):return {}
        def close(self):pass
    monkeypatch.setattr(notices.smtplib,"SMTP_SSL",Fake)
    monkeypatch.setenv("TRADING_SIM_SMTP_PASSWORD","abcd efgh ijkl mnop")
    notices._send_email("Synthetic","Data")
    assert captured==["abcdefghijklmnop"]
