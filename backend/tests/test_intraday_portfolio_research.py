"""Synthetic-only checks for actual-timestamp intraday portfolio research.

No owner rules, fills, personal strategies, or live provider credentials.
"""
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from math import sin

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import intraday_portfolio_research as ipr
from backend import strategy_period_queue as queue
from backend.main import app

NY = ZoneInfo("America/New_York")
SYMS = ("spy", "qqq")
SIZES = {"1m":60, "5m":300, "15m":900, "1h":3600}


def fixture_spec(model="relative_momentum"):
    return {"version":1,"model":model,"symbols":list(SYMS),
            "max_position_pct":50,"delay_sessions":1,"rebalance_sessions":5,
            "research_only":False,"base_currency":"USD"}


def dataset(resolution="5m",days=12):
    result={}
    start=datetime(2026,9,7,9,30,tzinfo=NY)
    sessions=[(start+timedelta(days=k)).date() for k in range(30)
              if (start+timedelta(days=k)).weekday()<5][:days]
    size=SIZES[resolution]
    per_session=390*60//size
    for symbol_idx,s in enumerate(SYMS):
        bars=[]
        for day_idx,day in enumerate(sessions):
            for j in range(per_session):
                local=datetime.combine(day,time(9,30),NY)+timedelta(seconds=j*size)
                index=day_idx*per_session+j
                base=90 + 30*symbol_idx
                price=base*(1.00006+symbol_idx*.00001)**index*(1+.003*sin(index/33+symbol_idx))
                closing=price*(1+.0002*sin(index/9))
                bars.append({"time":int(local.timestamp()),"open":price,
                             "high":max(price,closing)*1.002,
                             "low":min(price,closing)*.998,
                             "close":closing,"volume":40000})
        result[s]={"bars":bars,"source":"Independent synthetic minute history",
                   "is_demo":False}
    return result


def request(resolution="5m", period="60D", checks=2, model="relative_momentum"):
    return {"mode":"intraday","spec":fixture_spec(model),
            "resolution":resolution,"period":period,
            "checks_per_day":checks,"slippage_bps":8,"commission_usd":0}


def test_intraday_real_shared_minutes_and_bounded_daily_checks():
    data=dataset()
    result=ipr.analyze(request(),loader=lambda s,period,resolution:data[s],
                       now=datetime(2026,10,30,tzinfo=timezone.utc))
    assert result["mode"]=="intraday"
    assert result["resolution"]=="5m"
    assert result["common_bars"]==12*78
    assert 0<result["metrics"]["checks"]<=12*2
    assert result["metrics"]["trades"]>0
    assert result["equity_curve"]
    assert result["fills_total"]==len(result["fills"])
    assert result["metrics"]["average_invested_pct"]<=100.001
    assert all(f["symbol"] in SYMS and f["quantity"]>0 for f in result["fills"])
    assert result["metrics"]["fees"]==0
    assert result["benchmark"]["checks"]==result["metrics"]["checks"]
    assert "Sharpe" in " ".join(result["limitations"])


def test_one_minute_is_real_and_more_checks_are_not_forced_trades():
    data=dataset("1m",days=5)
    now=datetime(2026,10,30,tzinfo=timezone.utc)
    one=ipr.analyze(request("1m","7D",1,model="equal_weight"),
                    loader=lambda s,period,res:data[s],now=now)
    four=ipr.analyze(request("1m","7D",4,model="equal_weight"),
                     loader=lambda s,period,res:data[s],now=now)
    assert one["common_bars"]==5*390
    assert four["metrics"]["checks"]>one["metrics"]["checks"]
    assert four["metrics"]["trades"]>=one["metrics"]["trades"]


def test_missing_synchronized_minute_bars_are_not_fabricated():
    data=dataset("15m",days=12)
    data["qqq"]["bars"]=data["qqq"]["bars"][:10]
    with pytest.raises(ValueError,match="provider intraday"):
        ipr.analyze(request("15m","60D"),loader=lambda s,p,r:data[s],
                    now=datetime(2026,10,30,tzinfo=timezone.utc))
    data=dataset("15m",days=12)
    data["qqq"]["bars"]=[{**b,"time":b["time"]+60} for b in data["qqq"]["bars"]]
    with pytest.raises(ValueError,match="synchronized"):
        ipr.analyze(request("15m","60D"),loader=lambda s,p,r:data[s],
                    now=datetime(2026,10,30,tzinfo=timezone.utc))


def test_first_signal_never_uses_current_or_future_close():
    data=dataset("5m",days=10)
    now=datetime(2026,10,30,tzinfo=timezone.utc)
    params=ipr.validate_request(request(model="trend_filter"))
    shared,market,meta,_=ipr._prepare(params,lambda s,p,r:data[s],now)
    check=min(ipr._schedule(shared,2))
    original=ipr._simulate(params["spec"],shared,market,meta,2,8,0,
                           {"name":"trend_filter","resolution":"5m"})
    changed={s:[dict(bar) for bar in market[s]] for s in SYMS}
    for s in SYMS:
        for i in range(check,len(shared)):
            changed[s][i]["close"]*=1.5
    revised=ipr._simulate(params["spec"],shared,changed,meta,2,8,0,
                          {"name":"trend_filter","resolution":"5m"})
    first_original=[f for f in original[2] if f["time"]==shared[check]]
    first_revised=[f for f in revised[2] if f["time"]==shared[check]]
    assert first_original==first_revised


def test_research_limits_and_public_demo_guard(monkeypatch,tmp_path):
    for req in (request("1m","60D"),request(checks=3),request(checks=True),
                request(model="volatility_target")|{"spec":fixture_spec("leveraged_trend")}):
        with pytest.raises(HTTPException) as exc:
            ipr.validate_request(req)
        assert exc.value.status_code==422
    monkeypatch.setattr(queue,"DB_PATH",tmp_path/"private_intraday.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    client=TestClient(app)
    response=client.post("/api/live/research/strategy-period/jobs",json=request())
    assert response.status_code==202,response.text
    monkeypatch.setenv("TRADING_SIM_PUBLIC_DEMO","1")
    denied=client.post("/api/live/research/strategy-period/jobs",json=request())
    assert denied.status_code==403


def test_private_queue_replays_intraday_and_persists_verified_fills(monkeypatch,tmp_path):
    data=dataset()
    monkeypatch.setattr(queue,"DB_PATH",tmp_path/"intraday_private.sqlite3")
    monkeypatch.setattr(ipr.intraday,"replay_history",lambda s,p,r:data[s])
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    client=TestClient(app)
    resp=client.post("/api/live/research/strategy-period/jobs",json=request())
    assert resp.status_code==202,resp.text
    done=queue.process_one()
    assert done["status"]=="completed",done
    saved=client.get("/api/live/research/strategy-period/jobs/"+done["id"]).json()
    assert saved["result"]["mode"]=="intraday"
    assert saved["result"]["metrics"]["checks"]>0
