"""Private daily strategy engine regression tests with synthetic market data only.

No production trading strategy, symbol basket, or portfolio is included.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import live_machine as m, live_notifications as notify, strategy_library as library
from backend.main import app

client=TestClient(app)
NY=ZoneInfo("America/New_York")
SYNTHETIC="WHEN SMA(2) CROSSES ABOVE SMA(3) BUY 20%"

@pytest.fixture
def private_workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(m,"DB_PATH",tmp_path/"private_live.sqlite3")
    monkeypatch.setattr(library,"DB_PATH",tmp_path/"private_strategy.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    monkeypatch.delenv("TRADING_SIM_DISCORD_WEBHOOK",raising=False)
    monkeypatch.delenv("TRADING_SIM_SMTP_HOST",raising=False)
    monkeypatch.delenv("TRADING_SIM_EMAIL_TO",raising=False)
    return tmp_path

def daily_bars(ending=datetime(2026,11,16,tzinfo=NY)):
    # End at the most recent *completed* previous-day candle. Times are
    # 00:00 America/New_York to match Yahoo Finance daily data convention.
    dates=[]
    current=ending.date()-timedelta(days=175)
    while current<=ending.date():
        if current.weekday()<5:dates.append(current)
        current+=timedelta(days=1)
    bars=[]
    for i,d in enumerate(dates):
        close=100 if i<len(dates)-1 else 120
        stamp=datetime.combine(d,datetime.min.time(),NY)
        bars.append({"time":int(stamp.timestamp()),"open":close,
          "high":close+1,"low":close-1,"close":close,"volume":100000+i})
    return bars

def source(asset,range):
    assert asset=="spy"
    assert range=="1Y"
    return {"asset_id":asset,"range":range,"bars":daily_bars(),
            "is_demo":False,"offline_cache":False,"source":"synthetic test fixture"}

def morning():
    return datetime(2026,11,17,10,0,tzinfo=NY)

def deploy_fixture():
    s=library.store("single","Synthetic test only",SYNTHETIC,["spy"])
    return m.deploy(s["id"],state="paper",capital=100000,max_allocation_pct=10)

def test_deploy_run_once_idempotence_and_risk_cap(private_workspace):
    dep=deploy_fixture()
    assert dep["state"]=="paper"
    assert "code" not in dep
    m.run_once(now=morning(),source=source)
    s=m.signals()
    assert len(s)==1
    assert s[0]["asset_id"]=="spy"
    assert s[0]["side"]=="buy"
    assert s[0]["allocation_pct"]==10
    assert s[0]["suggested_notional"]==10000
    assert "WHEN " not in s[0]["rationale"]
    assert m.status()["worker_online"] is True
    m.run_once(now=morning(),source=source)
    assert len(m.signals())==1
    assert m.deployments()[0]["last_evaluated_at"] is not None

def test_no_signals_before_window_paused_or_retired(private_workspace):
    dep=deploy_fixture()
    m.run_once(now=datetime(2026,11,17,8,0,tzinfo=NY),source=source)
    assert m.signals()==[]
    m.change_state(dep["id"],"paused")
    m.run_once(now=morning(),source=source)
    assert m.signals()==[]
    m.change_state(dep["id"],"paper")
    m.change_state(dep["id"],"retired")
    with pytest.raises(HTTPException):
        m.change_state(dep["id"],"paper")

def test_fail_closed_on_stale_feed_and_offline_cache(private_workspace):
    dep=deploy_fixture()
    stale=lambda a,r:{**source(a,r),"offline_cache":True}
    m.run_once(now=morning(),source=stale)
    assert m.signals()==[]
    assert any(a["severity"]=="critical" for a in m.alerts())
    assert m.deployments()[0]["last_error"] is not None
    m.run_once(now=morning(),source=source)
    assert len(m.signals())==1
    assert not any(a["status"]=="open" for a in m.alerts())

def test_manual_trade_journal_audit_and_positions(private_workspace):
    deploy_fixture()
    m.run_once(now=morning(),source=source)
    signal=m.signals()[0]
    m.update_signal(signal["id"],"acknowledged")
    new=m.record_fill({
      "signal_id":signal["id"],"asset_id":"spy","side":"buy","quantity":5.,
      "price":101.,"fee":1.,"currency":"USD",
      "executed_at":morning().isoformat(),"broker_ref":"synthetic-test","notes":"example"})
    assert m.signals()[0]["status"]=="filled"
    assert m.journal()["positions"][0]["quantity"]==5
    changed=m.edit_fill(new["id"],{"quantity":4.,"price":99.,"notes":"corrected"})
    assert changed["quantity"]==4
    assert len(m.fill_history(new["id"]))==1
    assert m.journal()["positions"][0]["quantity"]==4
    with pytest.raises(HTTPException):
        m.record_fill({"signal_id":None,"asset_id":"spy","side":"sell",
                       "quantity":9.,"price":95.,"fee":0.,"currency":"USD",
                       "executed_at":morning().isoformat()})
    assert len(m.journal()["fills"])==1

def test_notification_deduplication_and_critical_repeat(private_workspace,monkeypatch):
    sent=[]
    monkeypatch.setenv("TRADING_SIM_DISCORD_WEBHOOK",
                       "https://discord.com/api/webhooks/123/"+("x"*30))
    monkeypatch.setattr(notify,"_send",lambda channel,title,body:sent.append((channel,title,body)))
    m.record_alert("machine:alert","critical","synthetic incident","synthetic only")
    notify.deliver_pending()
    notify.deliver_pending()
    assert len(sent)==1
    rows=notify.delivery_status()["deliveries"]
    assert len(rows)==1 and rows[0]["attempts"]==1
    m.acknowledge_alert(m.alerts()[0]["id"])
    notify.deliver_pending()
    assert len(sent)==1

def test_private_api_rejects_public_demo_without_creating_live_db(private_workspace,monkeypatch):
    from backend import main
    monkeypatch.setattr(main,"PUBLIC_DEMO",True)
    r=client.get("/api/live/status")
    assert r.status_code==403
    assert not m.DB_PATH.exists()

def test_api_validation_and_persistence(private_workspace):
    response=client.post("/api/live/deployments",json={"strategy_id":"missing"})
    assert response.status_code==404
    item=library.store("single","Synthetic test",SYNTHETIC,["spy"])
    response=client.post("/api/live/deployments",json={"strategy_id":item["id"]})
    assert response.status_code==200,response.text
    assert client.get("/api/live/deployments").json()[0]["id"]==response.json()["id"]
    assert client.post("/api/live/journal",json={
      "asset_id":"spy","side":"sell","quantity":10,"price":100,"fee":0,
      "currency":"USD","executed_at":morning().isoformat(),
    }).status_code==409
