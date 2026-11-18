"""Only independent synthetic OHLCV. No private signals or market records."""
from __future__ import annotations

from datetime import datetime,timedelta,time,timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import execution_windows as obs, live_machine as machine, main

NY=ZoneInfo("America/New_York")


def ts(day,hour,minute):
    return datetime.fromisoformat(day).replace(hour=hour,minute=minute,
        tzinfo=NY).astimezone(timezone.utc)


def signal(now=None,notional=10000,side="buy"):
    start=now or ts("2026-11-18",10,0)
    return {
        "id":"independent-synthetic-id","deployment_id":"dummy","asset_id":"spy",
        "side":side,"price_reference":100.,"suggested_notional":notional,
        "created_at":start.isoformat(),
        "expires_at":(start+timedelta(hours=14)).isoformat(),
        "status":"pending"}


def bars(start=ts("2026-11-18",9,30),n=22,volume=150000,base=100):
    result=[]
    for i in range(n):
        t=start+timedelta(minutes=5*i)
        price=base+i*.05
        result.append({
            "time":int(t.timestamp()),"open":price,"high":price+.5,
            "low":price-.5,"close":price+.1,"volume":volume})
    return {"bars":result,"is_demo":False,"offline_cache":False,
            "delayed_or_indicative":True}


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(obs,"DB_PATH",tmp_path/"private-execution-observer.sqlite3")
    monkeypatch.setattr(machine,"DB_PATH",tmp_path/"private-live-confirmations.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    monkeypatch.setattr(main,"PUBLIC_DEMO",False)
    return tmp_path


def test_only_completed_bars_after_signal_and_5_30_60_minute_scenarios(isolated):
    as_of=ts("2026-11-18",10,48)
    result=obs.evaluate(signal(),bars(),now=as_of)
    assert result["executed"] is False
    assert result["status"]=="window_active"
    five,thirty,sixty=result["scenarios"]
    assert five["delay_minutes"]==5
    assert five["first_bar"]==ts("2026-11-18",10,5).isoformat()
    assert five["hours_since_signal"]==pytest.approx(5/60,abs=1e-4)
    assert thirty["first_bar"]==ts("2026-11-18",10,30).isoformat()
    assert sixty["status"]=="awaiting_completed_bar"
    assert sixty["estimated_price_usd"] is None
    assert five["retrospective"] is True
    assert five["observed_at"]==ts("2026-11-18",10,10).isoformat()


def test_intraday_ongoing_bar_rejected_and_later_recovers(isolated):
    as_of=ts("2026-11-18",10,9)
    first=obs.evaluate(signal(),bars(),now=as_of)["scenarios"][0]
    assert first["status"]=="awaiting_completed_bar"
    assert first["estimated_price_usd"] is None
    next_one=obs.evaluate(signal(),bars(),now=ts("2026-11-18",10,10))["scenarios"][0]
    assert next_one["status"]=="capacity_observed"


def test_liquidity_limit_is_not_claimed_as_actual_fill(isolated):
    a=obs.evaluate(signal(notional=30000),bars(volume=1000),
                   now=ts("2026-11-18",10,50))["scenarios"][0]
    assert a["status"]=="partial_capacity_observed"
    assert a["capacity_shares"]==10
    assert a["estimated_fillable_shares"]==10
    assert a["requested_shares"]>10
    assert 0<a["capacity_pct"]<100
    sell=obs.evaluate(signal(side="sell"),bars(),
                   now=ts("2026-11-18",10,50))["scenarios"][0]
    buy=obs.evaluate(signal(),bars(),now=ts("2026-11-18",10,50))["scenarios"][0]
    assert sell["estimated_price_usd"]<buy["estimated_price_usd"]


def test_after_close_signal_cannot_fabricate_12_hour_fill(isolated):
    late=signal(now=ts("2026-11-18",16,0))
    next_morning=bars(start=ts("2026-11-19",9,30),n=30)
    output=obs.evaluate(late,next_morning,now=ts("2026-11-19",12,0))
    assert output["status"]=="window_elapsed"
    assert all(x["status"]=="no_completed_bar_observed" for x in output["scenarios"])
    assert all(x["estimated_fillable_shares"] is None for x in output["scenarios"])
    assert output["window_end"]==ts("2026-11-19",4,0).isoformat()


def test_missing_provisional_and_out_of_order_bars_fail_closed(isolated):
    response=bars()
    response["offline_cache"]=True
    with pytest.raises(ValueError,match="source"):
        obs.evaluate(signal(),response,now=ts("2026-11-18",10,50))
    response=bars();response["bars"][3]["high"]=20.
    with pytest.raises(ValueError,match="inconsistent"):
        obs.evaluate(signal(),response,now=ts("2026-11-18",10,50))
    response=bars();response["bars"][4]["time"]=response["bars"][2]["time"]
    with pytest.raises(ValueError,match="Unsorted"):
        obs.evaluate(signal(),response,now=ts("2026-11-18",10,50))


def test_observation_store_idempotent_and_never_writes_broker_fills(isolated):
    observed_at=ts("2026-11-18",10,50)
    report=obs.process_all(now=observed_at,loader=lambda asset,window:bars(),
                           signal_rows=[signal()])
    assert len(report)==1
    assert report[0]["scenarios"][0]["status"]=="capacity_observed"
    assert len(obs.observations())==1
    again=obs.process_all(now=observed_at,loader=lambda asset,window:bars(),
                           signal_rows=[signal()])
    assert len(again)==1 and len(obs.observations())==1
    assert not machine.DB_PATH.exists()
    assert not (isolated/"paper_forward.sqlite3").exists()
    bad=obs.process_all(now=observed_at,
                        loader=lambda asset,window:{"is_demo":True,"bars":[]},
                        signal_rows=[signal()])
    assert bad[0]["status"]=="data_unavailable"
    assert len(obs.observations())==1
    assert obs.observations()[0]["scenarios"][0]["status"]=="capacity_observed"


def test_public_demo_never_creates_observation_db(isolated,monkeypatch):
    client=TestClient(main.app)
    monkeypatch.setattr(main,"PUBLIC_DEMO",True)
    assert client.get("/api/live/execution-windows").status_code==403
    assert client.post("/api/live/execution-windows/check").status_code==403
    monkeypatch.setenv("TRADING_SIM_PUBLIC_DEMO","1")
    with pytest.raises(HTTPException) as exc:
        obs.process_all(now=ts("2026-11-18",10,50),signal_rows=[])
    assert exc.value.status_code==403
    assert not obs.DB_PATH.exists()


def test_http_owner_endpoint_and_manual_review_separation(isolated,monkeypatch):
    client=TestClient(main.app)
    obs.process_all(now=ts("2026-11-18",10,50),
                    loader=lambda asset,window:bars(),
                    signal_rows=[signal()])
    rows=client.get("/api/live/execution-windows")
    assert rows.status_code==200
    assert rows.json()[0]["executed"] is False
    assert not machine.DB_PATH.exists()
    monkeypatch.setattr(obs,"process_all",lambda:[])
    checked=client.post("/api/live/execution-windows/check")
    assert checked.status_code==200
    assert checked.json()=={"evaluated_signals":0,"data_unavailable":0}
