"""Persistent named strategies, immutable history, validation and safe reload."""
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient

from backend import arcade, portfolio_arcade as portfolio, strategy_library
from backend.main import app

client=TestClient(app)
SINGLE_A="WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%"
SINGLE_B="WHEN RSI(14) BELOW 30 BUY 50%"
PORT_A="WHEN spy SMA(10) CROSSES ABOVE SMA(30) BUY 25% qqq"
PORT_B="WHEN qqq SMA(20) CROSSES BELOW SMA(40) SELL 50% spy"


@pytest.fixture(autouse=True)
def isolated_library(tmp_path,monkeypatch):
    monkeypatch.setattr(strategy_library,"DB_PATH",tmp_path/"strategies.sqlite3")


def test_named_versions_persist_and_restore_without_activation():
    a=client.post("/api/strategies",json={"name":"SMA Version 1","mode":"single",
        "code":SINGLE_A,"symbols":["spy"],"source_run_id":"s1"})
    assert a.status_code==200,a.text
    b=client.post("/api/strategies",json={"name":"SMA Version 2","mode":"single",
        "code":SINGLE_B,"symbols":["spy"],"source_run_id":"s1"})
    assert b.status_code==200
    assert a.json()["id"]!=b.json()["id"]
    result=client.get("/api/strategies?mode=single")
    assert result.status_code==200
    rows=result.json()
    assert len(rows)==2 and rows[0]["code"]==SINGLE_B
    assert rows[1]["code"]==SINGLE_A
    assert client.get("/api/strategies/"+a.json()["id"]).json()["source"]=="manual"
    assert client.delete("/api/strategies/"+a.json()["id"]).json()["deleted"] is True
    assert len(client.get("/api/strategies?mode=single").json())==1
    assert client.get("/api/strategies/"+a.json()["id"]).status_code==404


def test_mode_isolation_and_rule_validation():
    assert client.post("/api/strategies",json={"name":"two assets","mode":"portfolio",
        "code":PORT_A,"symbols":["spy","qqq"]}).status_code==200
    assert client.get("/api/strategies?mode=single").json()==[]
    assert len(client.get("/api/strategies?mode=portfolio").json())==1
    cases=[
        ("single","__import__('os').system('echo bad')",["spy"]),
        ("single","",["spy"]),
        ("single",PORT_A,["spy"]),
        ("portfolio",PORT_A,["spy","tsla"]),
        ("portfolio",SINGLE_A,["spy","qqq"]),
    ]
    for mode,code,symbols in cases:
        response=client.post("/api/strategies",json={
            "name":"Invalid","mode":mode,"code":code,"symbols":symbols})
        assert response.status_code==422,response.text
    assert client.get("/api/strategies?mode=single").json()==[]


def test_capture_keeps_old_versions_and_prevents_duplicate_autosave():
    strategy_library.capture("single",SINGLE_A,["spy"],"run-a")
    strategy_library.capture("single",SINGLE_A,["spy"],"run-a")
    strategy_library.capture("single",SINGLE_B,["spy"],"run-a")
    rows=strategy_library.list_saved("single")
    assert len(rows)==2 and rows[0]["code"]==SINGLE_B and rows[1]["code"]==SINGLE_A
    assert all(r["source"]=="activated" for r in rows)
    assert all(r["source_run_id"]=="run-a" for r in rows)


def make_bars(asset):
    base=datetime(2025,1,1,tzinfo=timezone.utc)
    return [{"time":int((base+timedelta(days=i)).timestamp()),
             "open":100+i*.1,"high":102+i*.1,"low":99+i*.1,
             "close":100+i*.1,"volume":100} for i in range(150)]


def test_single_activation_archives_outgoing_strategy(tmp_path,monkeypatch):
    monkeypatch.setattr(arcade,"GAME_DB",tmp_path/"runs.sqlite3")
    monkeypatch.setattr(arcade,"history",lambda asset,period:{
        "source":"test","bars":make_bars(asset)})
    run=arcade.start_run("spy")
    arcade.set_strategy(run["id"],SINGLE_A)
    arcade.set_strategy(run["id"],SINGLE_B)
    saved=strategy_library.list_saved("single")
    assert len(saved)==2
    assert saved[0]["code"]==SINGLE_B
    assert saved[1]["code"]==SINGLE_A
    assert arcade.get_run(run["id"])["strategy"]==SINGLE_B


def test_portfolio_activation_archives_prior_strategy(tmp_path,monkeypatch):
    monkeypatch.setattr(portfolio,"DB_PATH",tmp_path/"multi.sqlite3")
    monkeypatch.setattr(portfolio,"history",lambda asset,period:{
        "source":"test","bars":make_bars(asset)})
    run=portfolio.create_season(["spy","qqq"])
    portfolio.strategy(run["id"],PORT_A)
    portfolio.strategy(run["id"],PORT_B)
    saved=strategy_library.list_saved("portfolio")
    assert len(saved)==2
    assert saved[0]["code"]==PORT_B
    assert saved[1]["code"]==PORT_A
    assert portfolio.get_season(run["id"])["strategy"]==PORT_B


def test_saving_library_entry_cannot_place_orders():
    entry=strategy_library.store("single","Simple test",SINGLE_A,["spy"])
    assert entry["id"]
    # Separate table stores only strategy text and provenance, no orders.
    with strategy_library.connection() as db:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables=={"saved_strategies"}
