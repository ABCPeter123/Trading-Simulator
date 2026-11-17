"""Offline regression tests. Never send an actual iMessage or use real recipients."""
from types import SimpleNamespace
import pytest

from backend import live_notifications as notify
from backend import live_machine as machine


def configure(monkeypatch):
    monkeypatch.delenv("TRADING_SIM_DISCORD_WEBHOOK", raising=False)
    monkeypatch.delenv("TRADING_SIM_SMTP_HOST", raising=False)
    monkeypatch.delenv("TRADING_SIM_EMAIL_TO", raising=False)
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_SERVER_URL", "https://mac-relay.invalid")
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_PASSWORD", "synthetic-test-secret")
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_CHAT_GUID", "iMessage;-;fixture@example.invalid")
    monkeypatch.delenv("TRADING_SIM_IMESSAGE_INCLUDE_DETAILS", raising=False)


def test_imessage_requires_all_configuration(monkeypatch):
    configure(monkeypatch)
    assert notify._channels()==["imessage"]
    monkeypatch.delenv("TRADING_SIM_IMESSAGE_PASSWORD")
    assert notify._channels()==[]


def test_imessage_uses_authenticated_https_without_private_details(monkeypatch):
    configure(monkeypatch)
    captured=[]
    def send(url,**kwargs):
        captured.append((url,kwargs))
        return SimpleNamespace(status_code=200,json=lambda:{"status":200,"data":{}})
    monkeypatch.setattr(notify.httpx,"post",send)
    notify._send("imessage","Review BUY for confidential-symbol","Synthetic $123 allocation")
    assert len(captured)==1
    url,arguments=captured[0]
    assert url=="https://mac-relay.invalid/api/v1/message/text"
    assert arguments["params"]=={"password":"synthetic-test-secret"}
    assert arguments["json"]["chatGuid"]=="iMessage;-;fixture@example.invalid"
    assert arguments["json"]["tempGuid"].startswith("ts-")
    assert "confidential-symbol" not in arguments["json"]["message"]
    assert "$123" not in arguments["json"]["message"]
    assert "private workspace" in arguments["json"]["message"]
    assert arguments["follow_redirects"] is False
    assert arguments["trust_env"] is False


def test_detailed_imessage_is_explicit_opt_in(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_INCLUDE_DETAILS","1")
    messages=[]
    def send(url,**kwargs):
        messages.append(kwargs["json"]["message"])
        return SimpleNamespace(status_code=200,json=lambda:{"status":200})
    monkeypatch.setattr(notify.httpx,"post",send)
    notify._send_imessage("Synthetic BUY","Synthetic ticker information")
    assert messages==["Trading Simulator: Synthetic BUY\nSynthetic ticker information"]


@pytest.mark.parametrize("server,chat",[
    ("http://mac-relay.invalid","iMessage;-;fixture@example.invalid"),
    ("https://username:password@mac-relay.invalid","iMessage;-;fixture@example.invalid"),
    ("https://mac-relay.invalid/other","iMessage;-;fixture@example.invalid"),
    ("https://mac-relay.invalid?redirect=1","iMessage;-;fixture@example.invalid"),
    ("https://mac-relay.invalid","any;-;fixture@example.invalid"),
])
def test_rejects_insecure_relays_and_implicit_sms(monkeypatch,server,chat):
    configure(monkeypatch)
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_SERVER_URL",server)
    monkeypatch.setenv("TRADING_SIM_IMESSAGE_CHAT_GUID",chat)
    monkeypatch.setattr(notify.httpx,"post",lambda *a,**kw:pytest.fail("Must not call external endpoint"))
    with pytest.raises(ValueError):
        notify._send_imessage("Synthetic","message")


@pytest.mark.parametrize("code,payload",[
    (302,{"status":200}),(200,{"status":500}),(200,{"status":200,"error":"fake"}),
    (200,{"wrong":"shape"}),(503,{"status":503}),
])
def test_relay_failure_never_returns_raw_provider_errors(monkeypatch,code,payload):
    configure(monkeypatch)
    monkeypatch.setattr(notify.httpx,"post",lambda *a,**kw:SimpleNamespace(
        status_code=code,json=lambda:payload))
    with pytest.raises(RuntimeError) as raised:
        notify._send_imessage("Synthetic","message")
    assert "synthetic-test-secret" not in str(raised.value)
    assert "fixture@example.invalid" not in str(raised.value)


def test_imessage_uses_existing_persistent_deduplication(monkeypatch,tmp_path):
    configure(monkeypatch)
    monkeypatch.setattr(machine,"DB_PATH",tmp_path/"synthetic-live.sqlite3")
    sent=[]
    monkeypatch.setattr(notify,"_send",lambda *args:sent.append(args))
    machine.record_alert("fixture:incident","critical","synthetic incident","synthetic only")
    notify.deliver_pending()
    notify.deliver_pending()
    assert len(sent)==1
    assert sent[0][0]=="imessage"
    assert notify.delivery_status()["deliveries"][0]["channel"]=="imessage"
