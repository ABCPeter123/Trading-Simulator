"""Synthetic offline verification for local market data upgrades.

Fixtures do not contain the owner's portfolio, downloaded prices or strategies.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import market_quality as quality
from backend import market_ingestion as ingest
from backend import portfolio_research as portfolio
from backend import live_machine as live
from backend import strategy_library as library
from backend import archive
from backend.main import app

NY=ZoneInfo("America/New_York")


def candles(start:date,days:int,base=100.,change=.001):
    bars=[]
    for i in range(days):
        day=start+timedelta(days=i)
        if day.weekday()>=5:continue
        price=base*(1+change)**i
        ts=int(datetime(day.year,day.month,day.day,tzinfo=timezone.utc).timestamp())
        bars.append({"time":ts,"open":price,"high":price*1.01,
                     "low":price*.99,"close":price*1.001,"volume":1500})
    return bars


@pytest.fixture
def local_data(tmp_path,monkeypatch):
    monkeypatch.setattr(ingest,"DB_PATH",tmp_path/"ingest.sqlite3")
    monkeypatch.setattr(archive,"archive_path",lambda asset,window:
                        tmp_path/"market"/asset/(window+".parquet"))
    monkeypatch.setattr(ingest,"archive_path",archive.archive_path)
    monkeypatch.setattr(quality,"archive_path",archive.archive_path)
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    return tmp_path


def test_bounded_local_subscription_and_private_api(local_data):
    c=TestClient(app)
    response=c.post("/api/market-data/subscriptions",json={"asset_id":"spy","resolution":"15m"})
    assert response.status_code==201,response.text
    assert response.json()["stored_locally"]
    assert len(c.get("/api/market-data/subscriptions").json())==1
    assert c.post("/api/market-data/subscriptions",json={
        "asset_id":"aapl-opt","resolution":"1m"}).status_code==422
    assert c.delete("/api/market-data/subscriptions/spy/15m").status_code==200
    assert c.get("/api/market-data/subscriptions").json()[0]["active"]==0


def test_incremental_fetch_uses_only_recent_overlap_and_deduplicates(local_data,monkeypatch):
    original=candles(date(2026,11,9),6)
    archive.record_history({"asset_id":"spy","range":"30D_15m","bars":original})
    end=original[-1]["time"]
    calls=[]
    next_bar={**original[-1],"time":end+900,"close":original[-1]["close"]*1.002,
              "high":original[-1]["high"]*1.004}
    def provider(asset,start,stop,resolution):
        calls.append((asset.id,start,stop,resolution))
        return [original[-1],next_bar]
    monkeypatch.setattr(ingest.intraday,"fetch_yahoo",provider)
    result=ingest.ingest_once("spy","15m",datetime(2026,11,18,tzinfo=timezone.utc))
    assert result["added"]==1
    assert calls[0][3]=="15m"
    assert abs(calls[0][1].timestamp()-(end-2700))<1
    report=quality.analyze("spy","30D","15m")
    assert report["bars"]==len(original)+1
    assert report["duplicate_timestamps"]==0


def test_quality_gap_reports_observed_missing_weekday_only(local_data):
    bars=candles(date(2026,11,9),8)
    # Remove one complete weekday, not a weekend.
    bars.pop(2)
    archive.record_history({"asset_id":"spy","range":"1Y","bars":bars})
    report=quality.analyze("spy","1Y")
    assert report["bars"]==5
    assert report["coverage_pct"]<100
    assert report["gaps"] and report["gaps"][0]["missing_estimate"]==1
    missing=quality.analyze("aapl","1Y")
    assert missing["status"]=="missing"
    assert missing["bars"]==0


def test_mixed_currency_uses_prior_completed_fx_and_rejects_missing(local_data):
    stocks=candles(date(2023,1,2),800)
    cad=candles(date(2023,1,2),800,base=80)
    fx=candles(date(2022,12,29),804,base=1.34,change=.00001)
    data={"spy":{"source":"synthetic USD","bars":stocks},
          "vfv":{"source":"synthetic CAD","bars":cad},
          "usdcad":{"source":"synthetic FX","bars":fx}}
    days,values,meta,sources=portfolio._prepare(["spy","vfv"],data)
    assert len(days)>=450
    assert meta["vfv"]["currency"]=="CAD"
    assert "prior completed" in sources["vfv"]
    ix=100
    day=days[ix]
    original=values["vfv"][ix]["close"]
    # The FX bar closing on a stock date must never affect the valuation
    # for that same date. Only a strictly earlier FX date can be used.
    for bar in data["usdcad"]["bars"]:
        if datetime.fromtimestamp(bar["time"],timezone.utc).date().isoformat()==day:
            bar["close"]*=3
            break
    _,new_values,_,_=portfolio._prepare(["spy","vfv"],data)
    assert new_values["vfv"][ix]["close"]==pytest.approx(original)
    assert portfolio._validate_basket(["spy","vfv"])==["spy","vfv"]
    with pytest.raises(HTTPException):
        portfolio._prepare(["spy","vfv"],{"spy":data["spy"],"vfv":data["vfv"]})


def test_completed_intraday_signal_is_evaluated_once_per_bar(tmp_path,monkeypatch):
    monkeypatch.setattr(live,"DB_PATH",tmp_path/"live.sqlite3")
    monkeypatch.setattr(library,"DB_PATH",tmp_path/"strategy.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    strategy=library.store("single","Synthetic intraday signal",
                           "WHEN SMA(2) CROSSES ABOVE SMA(3) BUY 20%",["spy"])
    dep=live.deploy(strategy["id"],resolution="15m")
    assert dep["resolution"]=="15m"
    now=datetime(2026,11,17,10,31,tzinfo=NY)
    observed=[]
    current=date(2026,11,10)
    while current<=date(2026,11,17):
        if current.weekday()<5:
            count=3 if current==date(2026,11,17) else 26
            for i in range(count):
                dt=datetime.combine(current,datetime.min.time(),NY)+timedelta(hours=9,minutes=30+15*i)
                price=120 if current==date(2026,11,17) and i==2 else 100
                observed.append({"time":int(dt.timestamp()),"open":price,
                                 "high":price+1,"low":price-1,"close":price,"volume":1000})
        current+=timedelta(days=1)
    def source(asset,period,resolution):
        assert (asset,period,resolution)==("spy","30D","15m")
        return {"bars":observed,"is_demo":False,"offline_cache":False}
    live.run_once(now=now,source=source)
    with live.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]==1
    assert len(live.signals())==1
    live.run_once(now=now+timedelta(seconds=90),source=source)
    with live.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]==1
    assert len(live.signals())==1


def test_crypto_daily_incremental_never_saves_five_minute_or_open_daily_candles(local_data,monkeypatch):
    previous=int(datetime(2026,11,15,tzinfo=timezone.utc).timestamp())
    seed={"time":previous,"open":100,"high":105,"low":95,"close":102,"volume":1000}
    archive.record_history({"asset_id":"btcusd","range":"1Y","bars":[seed]})
    seen=[]
    now=datetime(2026,11,17,12,tzinfo=timezone.utc)
    today=int(datetime(2026,11,17,tzinfo=timezone.utc).timestamp())
    class Response:
        def raise_for_status(self):pass
        def json(self):
            return [[previous,95,105,100,102,1000],
                    [today,100,110,103,108,1100]]
    class Client:
        def get(self,url,params):
            seen.append(params)
            return Response()
    monkeypatch.setattr(ingest.market,"_client",Client())
    result=ingest.ingest_once("btcusd","1d",now)
    assert seen[0]["granularity"]==86400
    assert result["added"]==0
    assert quality.analyze("btcusd","1Y")["bars"]==1


def test_optional_twil_provider_and_private_reasoning_strip(monkeypatch):
    from backend import ai_assistant as ai
    monkeypatch.setenv("TRADING_SIM_AI_PROVIDER","llama_cpp")
    monkeypatch.setenv("TRADING_SIM_AI_MODEL","TwIL-8B-Q4_K_M-balanced.gguf")
    config=ai.configuration()
    assert config["configured"] and not config["remote"]
    assert config["model"]=="TwIL-8B-Q4_K_M-balanced.gguf"
    answer,rule=ai.parse_answer(
        '<think>Synthetic hidden analysis</think> {"answer":"Synthetic result only","strategy":null}')
    assert answer=="Synthetic result only"
    assert rule is None
    with pytest.raises(HTTPException):
        ai.parse_answer("<think>unfinished synthetic reasoning")


def test_live_monitor_rejects_unconverted_cad_instrument(tmp_path,monkeypatch):
    monkeypatch.setattr(live,"DB_PATH",tmp_path/"live-usd.sqlite3")
    monkeypatch.setattr(library,"DB_PATH",tmp_path/"strategy-usd.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    saved=library.store("single","Synthetic CAD test only",
                        "WHEN SMA(2) CROSSES ABOVE SMA(3) BUY 20%",["vfv"])
    with pytest.raises(HTTPException) as denied:
        live.deploy(saved["id"],resolution="15m")
    assert denied.value.status_code==422
    assert live.deployments()==[]


def test_mutual_fund_cannot_request_intraday_ingestion(local_data,monkeypatch):
    from backend.assets import Instrument
    monkeypatch.setattr(ingest,"get_instrument",lambda _:Instrument(
        "example-fund","EXAMPLE","Funds","USD",tradable=False))
    with pytest.raises(HTTPException) as denied:
        ingest.subscribe("example-fund","5m")
    assert denied.value.status_code==422
    assert ingest.subscribe("example-fund","1d")["active"] is True


def test_incremental_daily_updates_max_archive_without_refetch(local_data,monkeypatch):
    original=candles(date(2026,11,9),5)
    archive.record_history({"asset_id":"spy","range":"MAX","bars":original})
    archive.record_history({"asset_id":"spy","range":"1Y","bars":original})
    last=original[-1]["time"]
    appended={**original[-1],"time":last+86400,"close":original[-1]["close"]*1.002}
    seen=[]
    def recent_fetch(asset,start,end,resolution):
        seen.append((asset.id,start,resolution))
        return [original[-1],appended]
    monkeypatch.setattr(ingest.intraday,"fetch_yahoo",recent_fetch)
    result=ingest.ingest_once("spy","1d",datetime(2026,11,18,tzinfo=timezone.utc))
    assert result["added"]==1 and seen[0][2]=="1d"
    response=TestClient(app).get("/api/market-data/archived/spy?window=MAX&resolution=1d")
    assert response.status_code==200,response.text
    assert len(response.json()["bars"])==len(original)+1
    assert response.json()["execution_eligible"] is False
    assert response.json()["offline_cache"] is True
    assert quality.analyze("spy","MAX")["last_bar"]==last+86400


def test_fresh_incremental_archive_is_not_a_quote_source(local_data):
    assert TestClient(app).get("/api/market-data/archived/spy?window=1Y").status_code==404
    assert quality.analyze("spy","1Y")["status"]=="missing"


def test_health_reports_active_errors_and_observed_age(local_data):
    client = TestClient(app)
    assert client.post("/api/market-data/subscriptions", json={
        "asset_id": "spy", "resolution": "5m"}).status_code == 201
    initial = client.get("/api/market-data/health").json()
    assert initial["active"] == 1
    row = initial["last_updates"][0]
    assert row["sync_state"] == "not_started"
    assert row["age_seconds"] is None
    assert row["interval_seconds"] == 300
    with ingest._db() as conn:
        conn.execute("UPDATE subscriptions SET failure_code=?,last_bar=? WHERE asset_id=?",
                     ("ProviderTimeout", 1600000000, "spy"))
        conn.commit()
    failed = client.get("/api/market-data/health").json()
    assert failed["errors"] == 1
    assert failed["last_updates"][0]["sync_state"] == "error"
    assert failed["last_updates"][0]["age_seconds"] > 0
    assert client.delete("/api/market-data/subscriptions/spy/5m").status_code == 200
    stopped = client.get("/api/market-data/health").json()
    assert stopped["active"] == 0 and stopped["errors"] == 0
    assert stopped["last_updates"][0]["sync_state"] == "disabled"
