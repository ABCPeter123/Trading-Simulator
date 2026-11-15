"""Offline contract tests for the shared-cash, multi-symbol historical arcade."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import portfolio_arcade as pa
from backend.main import app
from backend.portfolio_dsl import compile_portfolio_rules

CLIENT = TestClient(app)
START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def fixture_bars(asset_id):
    result = []
    for idx in range(240):
        day = START + timedelta(days=idx)
        if asset_id != "btcusd" and day.weekday() >= 5:
            continue
        # An exchange outage / missing candle is left missing.
        if asset_id == "qqq" and idx in (129, 130, 131):
            continue
        price = (100 + idx * .05) if asset_id != "qqq" else (200 + idx * .12)
        if asset_id == "btcusd":
            price = 30000 + idx * 60
        # Create a cross for SPY at index 140 to trigger a bot.
        if asset_id == "spy":
            price = 100.0 if idx < 140 else (115.0 + (idx-140) * .05)
        result.append({
            "time": int(day.timestamp()), "open": price,
            "high": price + 2, "low": price - 2,
            "close": price, "volume": 10000,
        })
    return result


@pytest.fixture(autouse=True)
def fake_prices_and_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "DB_PATH", tmp_path / "arcade.sqlite3")
    monkeypatch.setattr(pa, "history", lambda asset_id, window: {
        "asset_id": asset_id, "range": window, "source": "test provider",
        "bars": fixture_bars(asset_id),
    })


def test_catalog_and_session_resumption_without_future_prices():
    game = pa.create_season(["spy", "qqq"], "5Y", .35)
    assert game["asset_ids"] == ["spy", "qqq"]
    assert len(game["bars"]["spy"]) < len(fixture_bars("spy"))
    assert len(game["bars"]["qqq"]) < len(fixture_bars("qqq"))
    for asset_id in game["asset_ids"]:
        assert all(datetime.fromtimestamp(b["time"], tz=timezone.utc).date().isoformat() <= game["day"]
                   for b in game["bars"][asset_id])
    assert pa.get_season(game["id"])["day"] == game["day"]
    assert pa.list_seasons()[0]["id"] == game["id"]
    assert game["metrics"]["cash"] == 100000
    assert game["metrics"]["equity"] == 100000


def test_shared_cash_and_independent_positions():
    game = pa.create_season(["spy", "qqq"], "1Y", .35)
    run = game["id"]
    pa.order(run, "spy", "buy", "market", "10", "units")
    pa.order(run, "qqq", "buy", "market", "15", "units")
    pending = pa.get_season(run)
    assert pending["metrics"]["cash"] == 100000
    assert len(pending["orders"]) == 2
    advanced = pa.advance(run, 5)
    holdings = {p["asset_id"]: p for p in advanced["positions"]}
    assert holdings["spy"]["quantity"] == 10
    assert holdings["qqq"]["quantity"] == 15
    assert advanced["metrics"]["cash"] < 100000
    assert abs(advanced["metrics"]["equity"]-(advanced["metrics"]["cash"]+advanced["metrics"]["exposure"])) < .001
    pa.order(run, "spy", "sell", "market", "5", "units")
    advanced = pa.advance(run, 5)
    holdings = {p["asset_id"]: p for p in advanced["positions"]}
    assert holdings["spy"]["quantity"] == 5
    assert holdings["qqq"]["quantity"] == 15
    assert len(advanced["fills"]) == 3


def test_market_holiday_does_not_fill_stock_order_with_crypto_only_day():
    game = pa.create_season(["spy", "btcusd"], "5Y", .35)
    run = game["id"]
    # Find Friday. Next global day is Saturday, when stock has no bar.
    while datetime.fromisoformat(game["day"]).weekday() != 4:
        game = pa.advance(run, 1)
    pa.order(run, "spy", "buy", "market", "10", "units")
    pa.order(run, "btcusd", "buy", "market", "1", "units")
    saturday = pa.advance(run, 1)
    assert datetime.fromisoformat(saturday["day"]).weekday() == 5
    assert next(p for p in saturday["positions"] if p["asset_id"]=="spy")["quantity"] == 0
    assert next(p for p in saturday["positions"] if p["asset_id"]=="btcusd")["quantity"] == 1
    assert len(saturday["orders"]) == 1
    monday = pa.advance(run, 2)
    assert next(p for p in monday["positions"] if p["asset_id"]=="spy")["quantity"] == 10
    assert not monday["orders"]


def test_cross_asset_bot_signal_on_close_and_next_symbol_open():
    game = pa.create_season(["spy", "qqq"], "5Y", .3)
    run = game["id"]
    code = "WHEN spy PRICE CROSSES ABOVE SMA(5) BUY 10% qqq"
    pa.strategy(run, code)
    activated = pa.advance(run, 100, until_action=True)
    assert activated["orders"]
    assert activated["orders"][0]["asset_id"] == "qqq"
    assert activated["orders"][0]["source"] == "bot"
    assert next(p for p in activated["positions"] if p["asset_id"]=="qqq")["quantity"] == 0
    after = pa.advance(run, 3)
    assert next(p for p in after["positions"] if p["asset_id"]=="qqq")["quantity"] > 0
    assert after["fills"][0]["asset_id"] == "qqq"
    assert after["fills"][0]["time"] > activated["bars"]["qqq"][-1]["time"]


def test_stop_exit_and_position_independence():
    game = pa.create_season(["spy", "qqq"], "5Y", .35)
    run = game["id"]
    pa.risk(run, 5, 0)
    pa.order(run, "spy", "buy", "market", "5", "units")
    pa.order(run, "qqq", "buy", "market", "7", "units")
    a = pa.advance(run, 3)
    assert all(p["quantity"]>0 for p in a["positions"])
    # Exercise risk path by changing frozen OHLC inside session (test fixture only).
    with pa.connection() as db:
        row, snap, state = pa._load(db, run)
        future = snap["days"][state["index"]+1]
        snap["daily"]["spy"][future]["low"] = 1
        import json, zlib
        db.execute("UPDATE portfolio_seasons SET snapshot=? WHERE id=?",
                   (zlib.compress(json.dumps(snap).encode()), run))
        db.commit()
    a = pa.advance(run, 1)
    assert next(p for p in a["positions"] if p["asset_id"]=="spy")["quantity"] == 0
    assert next(p for p in a["positions"] if p["asset_id"]=="qqq")["quantity"] == 7


def test_invalid_baskets_and_symbol_validation():
    with pytest.raises(HTTPException):
        pa.create_season(["spy"])
    with pytest.raises(HTTPException):
        pa.create_season(["spy", "spy"])
    with pytest.raises(HTTPException):
        pa.create_season(["spy", "vfv"])
    with pytest.raises(HTTPException):
        pa.create_season(["spy", "es"])
    with pytest.raises(HTTPException):
        compile_portfolio_rules("WHEN spy SMA(10) ABOVE SMA(30) BUY 25% tsla", {"spy", "qqq"})
    with pytest.raises(HTTPException):
        compile_portfolio_rules("import os", {"spy","qqq"})
    game = pa.create_season(["spy","qqq"])
    with pytest.raises(HTTPException):
        pa.order(game["id"], "tsla", "buy", "market", "3", "units")
    with pytest.raises(HTTPException):
        pa.order(game["id"], "spy", "sell", "market", "1", "units")


def test_http_endpoints():
    response = CLIENT.post("/api/portfolio-seasons", json={"asset_ids":["spy","qqq"],"period":"5Y"})
    assert response.status_code == 200
    game = response.json()
    assert CLIENT.get("/api/portfolio-seasons").status_code == 200
    assert CLIENT.get(f"/api/portfolio-seasons/{game['id']}").json()["id"] == game["id"]
    trade = CLIENT.post(f"/api/portfolio-seasons/{game['id']}/orders",json={
        "asset_id":"spy","side":"buy","size":"5","size_type":"units",
    })
    assert trade.status_code == 200
    step = CLIENT.post(f"/api/portfolio-seasons/{game['id']}/advance",json={"count":3})
    assert step.status_code == 200
    assert step.json()["metrics"]["cash"] < 100000
