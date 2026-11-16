"""Reproducible scenario and backward-replay regression tests."""
from datetime import datetime, timedelta, timezone
from math import exp, log
import pytest
from fastapi.testclient import TestClient

from backend import arcade, portfolio_arcade as pa
from backend.arcade_dsl import compile_rules, indicator
from backend.stochastic import simulate, probability_up, black_scholes
from backend.main import app

client=TestClient(app)
BASE=datetime(2024,1,2,tzinfo=timezone.utc)
def candles(symbol="spy"):
    return [{"time":int((BASE+timedelta(days=i)).timestamp()),
             "open":100+float(i)*.12+(4 if symbol=="qqq" else 0),
             "high":102+float(i)*.12+(4 if symbol=="qqq" else 0),
             "low":99+float(i)*.12+(4 if symbol=="qqq" else 0),
             "close":100+float(i)*.12+(4 if symbol=="qqq" else 0),
             "volume":10000} for i in range(170)]

@pytest.fixture
def seasons(monkeypatch,tmp_path):
    db=tmp_path/"replay.sqlite3"
    monkeypatch.setattr(arcade,"GAME_DB",db)
    monkeypatch.setattr(pa,"DB_PATH",db)
    monkeypatch.setattr(arcade,"history",lambda asset,period:{"source":"test","bars":candles(asset)})
    monkeypatch.setattr(pa,"history",lambda asset,period:{"source":"test","bars":candles(asset)})
    single=arcade.start_run("spy",starting_point=.3)
    multi=pa.create_season(["spy","qqq"],starting_point=.3)
    return single,multi

def test_reproducible_256_paths_and_quantiles():
    bars=candles()
    a=simulate(bars[:70],horizon=12,lookback=60,seed=500)
    b=simulate(bars[:70],horizon=12,lookback=60,seed=500)
    assert a==b
    assert len(a["paths"])==256
    assert len(a["paths"][0])==13
    assert len(a["quantiles"])==13
    assert a["quantiles"][0]["p05"]==a["spot"]
    for p in a["quantiles"]:
        assert p["p05"]<=p["p25"]<=p["median"]<=p["p75"]<=p["p95"]

def test_no_future_data_in_forecast():
    past=candles()[:75]
    a=simulate(past,seed=1)
    later=candles()
    for b in later[75:]:
        b["close"]=999999
    assert simulate(later[:75],seed=1)==a
    assert probability_up(past,20)==pytest.approx(probability_up(later[:75],20))

def test_price_up_indicator_and_dsl_boundaries():
    bars=candles()
    compiled=compile_rules("WHEN PROB_UP(20) ABOVE 60 BUY 25%")
    assert len(compiled)==1
    p=indicator("PROB_UP(20)",bars,80)
    assert p is not None and 0<=p<=100
    assert indicator("PROB_UP(20)",bars,10) is None
    with pytest.raises(Exception):
        compile_rules("WHEN PROB_UP(61) ABOVE 55 BUY 25%")

def test_black_scholes_put_call_parity_and_intrinsic():
    res=black_scholes(100,100,1,.2,.05)
    assert res["call"]-res["put"]==pytest.approx(100-100*exp(-.05),abs=1e-7)
    assert res["call"]==pytest.approx(10.4506,abs=.0002)
    assert black_scholes(150,100,1,0,0)=={"call":50,"put":0}
    with pytest.raises(Exception):black_scholes(100,0,1,.2)

def test_single_history_navigation_is_observational(seasons):
    single,_=seasons
    ident=single["id"]
    start=single["current_bar"]
    arcade.submit_order(ident,"buy","market","10","units")
    arcade.advance_run(ident,3)
    latest=arcade.get_run(ident)
    assert latest["checkpoint_count"]==4
    rewind=arcade.get_at(ident,start)
    assert rewind["viewing_past"] is True
    assert rewind["current_bar"]==start
    assert rewind["metrics"]["cash"]==100000
    assert len(rewind["fills"])==0
    assert len(rewind["bars"])==len(single["bars"])
    assert arcade.get_run(ident)==latest
    assert arcade.get_analysis(ident,at_index=start)["sessions"]==1
    with pytest.raises(Exception):arcade.get_at(ident,start+99)

def test_portfolio_history_navigation_exact_positions(seasons):
    _,multi=seasons
    ident=multi["id"]
    start=multi["current_step"]
    pa.order(ident,"spy","buy","market","5","units")
    pa.advance(ident,3)
    now=pa.get_season(ident)
    old=pa.get_at(ident,start)
    assert old["viewing_past"] and old["metrics"]["cash"]==100000
    assert all(p["quantity"]==0 for p in old["positions"])
    assert now["metrics"]["cash"]<100000
    assert pa.get_analysis(ident,at_index=start)["summary"]["fill_count"]==0
    assert pa.get_season(ident)==now
    response=client.get("/api/portfolio-seasons/"+ident+"/at/"+str(start))
    assert response.status_code==200
    assert response.json()["current_step"]==start
    assert client.get("/api/portfolio-seasons/"+ident+"/analytics?at="+str(start)).json()["sessions"]==1

def test_scenario_endpoint_never_reveals_unseen_bars(seasons):
    single,multi=seasons
    resp=client.post("/api/research/scenarios",json={
        "mode":"single","run_id":single["id"],"horizon":10,"lookback":35,
    })
    assert resp.status_code==200,resp.text
    body=resp.json()
    assert body["paths_count"]==256 and body["as_of"]==single["bars"][-1]["time"]
    assert body["resolution"]=="1d"
    invalid=client.post("/api/research/scenarios",json={
        "mode":"portfolio","run_id":multi["id"],"asset_id":"tsla",
    })
    assert invalid.status_code==422
    bs=client.post("/api/research/black-scholes",json={
        "spot":100,"strike":100,"maturity_years":1,"volatility_annual":.2,
    })
    assert bs.status_code==200
    assert bs.json()["not_a_price_forecast"] is True
