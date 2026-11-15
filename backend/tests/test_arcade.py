"""Historical game correctness, persistence and no-lookahead tests. No network."""
import math

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import arcade
from backend.arcade_dsl import compile_rules, matches, indicator
from backend.main import app

client = TestClient(app)

def bars():
    values = [100.0]*79 + [105.0]*15 + [95.0]*15 + [112.0]*60
    return [
        {"time": 1700000000+i*86400, "open": p, "high": p+1,
         "low": p-1, "close": p, "volume": 10_000}
        for i,p in enumerate(values)
    ]

@pytest.fixture(autouse=True)
def local_game(tmp_path, monkeypatch):
    monkeypatch.setattr(arcade, "GAME_DB", tmp_path / "game.sqlite3")
    monkeypatch.setattr(arcade, "history", lambda asset_id, period: {
        "bars": bars(), "source": "fixture-real-provider", "asset_id": asset_id})
    yield


def start():
    return arcade.start_run("aapl")


def test_safe_strategy_language_and_errors():
    rules = compile_rules("WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%\nWHEN RSI(14) BELOW 30 BUY 10%")
    assert len(rules) == 2
    assert rules[0].percent == 25
    assert compile_rules("# comment\n") == []
    with pytest.raises(HTTPException):
        compile_rules("import os\nos.system('bad')")
    with pytest.raises(HTTPException):
        compile_rules("WHEN SMA(0) ABOVE PRICE BUY 30%")
    with pytest.raises(HTTPException):
        compile_rules("WHEN SMA(10) ABOVE PRICE BUY 110%")
    with pytest.raises(HTTPException):
        compile_rules("\n".join(["WHEN SMA(10) ABOVE PRICE SELL 5%"]*13))
    assert indicator("RSI(14)", bars(), 10) is None
    assert indicator("RSI(14)", bars(), 30) == 50


def test_no_future_candles_or_state_leak():
    game = start()
    assert len(game["bars"]) == game["current_bar"]+1
    assert game["current_bar"] < game["total_bars"]-1
    assert "history_blob" not in game
    assert game["bars"][-1]["time"] < bars()[-1]["time"]
    assert arcade.get_run(game["id"])["bars"] == game["bars"]
    next_game = arcade.advance_run(game["id"], 5)
    assert len(next_game["bars"]) == len(game["bars"])+5
    assert next_game["metrics"]["equity"] == 100000


def test_market_order_next_open_and_persistent_state():
    game = start()
    run = game["id"]
    placed = arcade.submit_order(run, "buy", "market", "10", "units")
    assert placed["metrics"]["quantity"] == 0
    assert placed["orders"][0]["placed_bar"] == game["current_bar"]
    after = arcade.advance_run(run, 1)
    assert after["metrics"]["quantity"] == 10
    assert after["metrics"]["cash"] < 99_000
    assert after["fills"][0]["time"] == bars()[game["current_bar"]+1]["time"]
    assert after["fills"][0]["price"] > 100
    assert arcade.get_run(run)["metrics"]["quantity"] == 10
    sell = arcade.submit_order(run, "sell", "market", "50", "percent")
    assert sell["metrics"]["quantity"] == 10
    closed = arcade.advance_run(run, 1)
    assert closed["metrics"]["quantity"] == 5
    assert closed["metrics"]["realized_pnl"] < 0


def test_limit_order_and_cancel():
    run = start()["id"]
    game = arcade.submit_order(run, "buy", "limit", "10", "units", "90")
    assert game["orders"]
    advanced = arcade.advance_run(run, 6)
    assert advanced["metrics"]["quantity"] == 0
    assert len(advanced["orders"]) == 1
    cleared = arcade.cancel_order(run, advanced["orders"][0]["id"])
    assert cleared["orders"] == []
    with pytest.raises(HTTPException):
        arcade.submit_order(run, "sell", "market", "5", "units")


def test_signal_is_queued_after_close_and_executed_next_open():
    run = start()["id"]
    arcade.set_strategy(run, "WHEN PRICE CROSSES ABOVE SMA(5) BUY 50%")
    # Breakout occurs at bar 79, after first 79 bars close at 100.
    first = arcade.advance_run(run, 100, until_action=True)
    assert first["current_bar"] == 79
    assert first["metrics"]["quantity"] == 0
    assert first["orders"][0]["source"] == "bot"
    second = arcade.advance_run(run, 1)
    assert second["current_bar"] == 80
    assert second["metrics"]["quantity"] > 0
    assert second["fills"][0]["time"] == bars()[80]["time"]
    assert "Bot programmed" in second["metrics"]["badges"]
    assert second["metrics"]["xp"] > 0


def test_reject_impossible_inputs():
    run = start()["id"]
    with pytest.raises(HTTPException):
        arcade.submit_order(run, "buy", "market", "-1", "units")
    with pytest.raises(HTTPException):
        arcade.submit_order(run, "buy", "market", "150", "percent")
    with pytest.raises(HTTPException):
        arcade.submit_order(run, "buy", "limit", "1", "units", "0")
    with pytest.raises(HTTPException):
        arcade.advance_run(run, 101)
    with pytest.raises(HTTPException):
        arcade.start_run("es")
    with pytest.raises(HTTPException):
        arcade.start_run("vfv")


def test_api_endpoints_and_resume():
    response = client.post("/api/arcade/new", json={"asset_id":"spy"})
    assert response.status_code == 200
    run = response.json()["id"]
    assert client.get("/api/arcade/runs").json()[0]["id"] == run
    validated = client.post("/api/arcade/validate", json={"code":"WHEN PRICE ABOVE SMA(4) BUY 10%"})
    assert validated.json()["valid"]
    assert client.put(f"/api/arcade/{run}/strategy", json={"code":"WHEN PRICE ABOVE SMA(4) BUY 10%"}).status_code == 200
    trade = client.post(f"/api/arcade/{run}/orders", json={
        "side":"buy", "kind":"market", "size":"10", "size_type":"percent"})
    assert trade.status_code == 200
    stepped = client.post(f"/api/arcade/{run}/advance", json={"count":1})
    assert stepped.status_code == 200
    assert stepped.json()["metrics"]["quantity"] > 0
    assert client.get(f"/api/arcade/{run}").json()["metrics"]["quantity"] > 0
    assert client.post(f"/api/arcade/{run}/advance", json={"count":200}).status_code == 422


def test_long_history_and_catalog():
    from backend.assets import list_instruments
    instruments = list_instruments(limit=250)
    assert len(instruments) >= 130
    assert any(item["symbol"] == "AMZN" for item in instruments)
    assert any(item["symbol"] == "GC=F" and not item["tradable"] for item in instruments)
    assert any(item["symbol"] == "VFV.TO" and item["currency"] == "CAD" for item in instruments)
    assert any(item["symbol"] == "SOL-USD" for item in instruments)
    game = arcade.start_run("spy", period="10Y")
    assert game["period"] == "10Y"
    assert len(game["bars"]) < game["total_bars"]
    assert game["source"] == "fixture-real-provider"


def test_protective_stop_and_take_profit_priority(monkeypatch):
    source = bars()
    # Advance from index 50. After buying at 51, high and low of bar 52
    # touch both profit target and loss stop. The conservative stop wins.
    source[52] = {**source[52], "high": 120, "low": 80, "close": 100}
    monkeypatch.setattr(arcade, "history", lambda asset_id, period: {
        "bars": source, "source": "fixture", "asset_id": asset_id,
    })
    game = arcade.start_run("aapl", starting_point=0.3)
    assert game["current_bar"] == 50
    run = game["id"]
    arcade.set_risk(run, stop_loss_pct=3, take_profit_pct=5)
    arcade.submit_order(run, "buy", "market", "10", "units")
    acquired = arcade.advance_run(run, 1)
    assert acquired["metrics"]["quantity"] == 10
    assert acquired["risk"]["stop_loss_pct"] == 3
    assert acquired["fills"][0]["source"] == "manual"
    exited = arcade.advance_run(run, 1)
    assert exited["metrics"]["quantity"] == 0
    assert exited["fills"][0]["source"] == "risk"
    assert exited["fills"][0]["kind"] == "stop"
    assert exited["fills"][0]["price"] < 100
    assert len(exited["fills"]) == 2
    assert exited["metrics"]["realized_pnl"] < 0
    assert arcade.get_run(run)["risk"]["take_profit_pct"] == 5


def test_risk_disabled_and_bad_values():
    run = start()["id"]
    assert arcade.get_run(run)["risk"]["stop_loss_pct"] == 0
    with pytest.raises(HTTPException):
        arcade.set_risk(run, -1, 4)
    with pytest.raises(HTTPException):
        arcade.set_risk(run, 2, 76)
    result = client.put(f"/api/arcade/{run}/risk", json={"stop_loss_pct": 4, "take_profit_pct": 8})
    assert result.status_code == 200
    assert result.json()["risk"]["take_profit_pct"] == 8
