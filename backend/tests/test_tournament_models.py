"""Offline synthetic regression for tournament-to-simulator-to-paper strategy workflow."""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import portfolio_arcade as sim, universe_research as tour
from backend import tournament_strategies as saved, live_machine as live
from backend.main import app


@pytest.fixture
def model_fixture(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO", raising=False)
    for module, name in ((tour, "universe.sqlite3"), (saved,"versions.sqlite3"),
                         (sim,"replay.sqlite3"), (live,"live.sqlite3")):
        monkeypatch.setattr(module, "DB_PATH", tmp_path/name)
    example={"rank":1,"basket_type":"synthetic_balanced",
             "symbols":["spy","qqq"],"model":"equal_weight",
             "restricted_research":False,"short_proxy_research":False}
    with closing(tour._connection()) as conn:
        conn.execute("INSERT INTO universe_jobs (id,status,created_at,updated_at,stage,params,result) "
                     "VALUES (?,?,?,?,?,?,?)",
                     ("fixture-job","completed","2026-01-01","2026-01-01","Research complete",
                      json.dumps({"scope":"all","delay_sessions":1,
                                  "max_drawdown_pct":30,"max_position_pct":35}),
                      json.dumps({"top10":[example]})))
    # Independently synthetic daily OHLCV with enough prior closes for 180-day warmup.
    end=date(2026,11,16)
    business_days=[]
    d=end
    while len(business_days)<850:
        if d.weekday()<5: business_days.append(d)
        d-=timedelta(days=1)
    business_days.reverse()
    def fake_history(symbol, period):
        base=80 if symbol=="spy" else 150
        return {"is_demo":False,"source":"Synthetic offline fixture",
                "bars":[{"time":int(datetime.combine(day,time(16),timezone.utc).timestamp()),
                         "open":(base+i*.035)*1.001,
                         "close":base+i*.035,
                         "high":(base+i*.035)*1.015,
                         "low":(base+i*.035)*.985,"volume":100000}
                        for i,day in enumerate(business_days)]}
    monkeypatch.setattr(sim,"history",fake_history)
    return fake_history


def test_import_rank_is_immutable_idempotent_and_private(model_fixture):
    client=TestClient(app)
    url="/api/live/research/universe/jobs/fixture-job/strategies/1"
    first=client.post(url)
    assert first.status_code==201,first.text
    second=client.post(url)
    assert second.json()["id"]==first.json()["id"]
    row=first.json()
    assert row["mode"]=="portfolio_model"
    assert row["symbols"]==["spy","qqq"]
    assert row["model"]=="equal_weight"
    assert row["max_position_pct"]==35
    assert row["rebalance_sessions"]==21
    assert len(saved.list_saved())==1
    with pytest.raises(HTTPException) as error:
        saved.import_rank("fixture-job",2)
    assert error.value.status_code==404


def test_tournament_model_runs_in_future_hidden_shared_cash_replay(model_fixture):
    version=saved.import_rank("fixture-job",1)
    client=TestClient(app)
    response=client.post("/api/portfolio-seasons/from-tournament",
                         json={"strategy_id":version["id"],"period":"MAX"})
    assert response.status_code==200,response.text
    replay=response.json()
    assert replay["model_strategy"]["model"]=="equal_weight"
    assert replay["strategy"]==""
    assert len(replay["bars"]["spy"])<850
    stepped=client.post(f"/api/portfolio-seasons/{replay['id']}/advance",
                        json={"count":1}).json()
    assert stepped["model_strategy"]["elapsed_shared"]==1
    assert any(fill["source"]=="tournament" for fill in stepped["fills"])
    assert stepped["metrics"]["cash"]>=0
    previous_fills=len(stepped["fills"])
    stepped=client.post(f"/api/portfolio-seasons/{replay['id']}/advance",
                        json={"count":5}).json()
    assert len(stepped["fills"])==previous_fills
    with pytest.raises(HTTPException) as error:
        sim.activate_tournament_model(replay["id"],version["id"])
    assert error.value.status_code==409


def test_model_deploys_to_paper_and_generates_deduplicated_signals(model_fixture):
    version=saved.import_rank("fixture-job",1)
    result=TestClient(app).post("/api/live/deployments",json={
        "strategy_id":version["id"],"state":"paper","capital":100000,
        "max_allocation_pct":35,"max_daily_signals":20,"resolution":"1d",
        "max_realized_loss_pct":5,
    })
    assert result.status_code==200,result.text
    assert result.json()["mode"]=="portfolio_model"
    now=datetime(2026,11,17,11,tzinfo=ZoneInfo("America/New_York"))
    live.run_once(now=now,source=model_fixture)
    signals=live.signals()
    assert len(signals)==2
    assert all(signal["source_symbol"]=="portfolio" for signal in signals)
    assert all(signal["suggested_notional"]>0 for signal in signals)
    assert live.journal()["fills"]==[]
    live.run_once(now=now,source=model_fixture)
    assert len(live.signals())==2


def test_live_rejects_undercapped_model_instead_of_changing_its_rules(model_fixture):
    version=saved.import_rank("fixture-job",1)
    with pytest.raises(HTTPException) as err:
        live.deploy(version["id"],max_allocation_pct=10,max_daily_signals=20)
    assert err.value.status_code==422
    assert "position cap" in err.value.detail
