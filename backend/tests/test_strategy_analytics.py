"""No-lookahead strategy analytics tests with deterministic saved market data."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.strategy_analytics import build_report
from backend import arcade, portfolio_arcade as pa
from backend.main import app

client = TestClient(app)
START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def candle(day, price):
    return {"time": int((START + timedelta(days=day)).timestamp()),
            "open": price, "high": price + 2, "low": price - 2,
            "close": price, "volume": 100}


def test_empty_season_benchmark_and_rolling_returns():
    days = [(START + timedelta(days=i)).date().isoformat() for i in range(81)]
    bars = {"spy": {day: candle(i, 100+i) for i, day in enumerate(days)},
            "qqq": {day: candle(i, 200+2*i) for i, day in enumerate(days)}}
    report = build_report(days, bars, ["spy", "qqq"], 40, 60, [])
    assert len(report["curve"]) == 21
    assert report["summary"]["total_return_pct"] == 0
    assert report["summary"]["current_equity"] == 100000
    assert report["summary"]["current_cash"] == 100000
    assert report["summary"]["current_invested"] == 0
    assert report["curve"][0]["benchmark"] == 100000
    assert report["summary"]["benchmark_return_pct"] > 0
    assert report["rolling"]["5"]["return_pct"] == 0
    assert report["rolling"]["60"] is None
    assert report["summary"]["step_sharpe"] is None
    assert report["allocations"][0]["weight_pct"] == 0


def test_reconstructs_fills_fees_exposure_and_exit_win_rate():
    days = [(START + timedelta(days=i)).date().isoformat() for i in range(8)]
    daily = {"spy": {day:candle(i, 100+10*i) for i,day in enumerate(days)},
             "qqq": {day:candle(i, 100) for i,day in enumerate(days)}}
    fills = [
        {"time":candle(1,110)["time"], "asset_id":"spy", "side":"buy", "quantity":10, "price":110, "fee":1},
        {"time":candle(3,130)["time"], "asset_id":"spy", "side":"sell", "quantity":5, "price":130, "fee":2},
    ]
    report = build_report(days,daily,["spy","qqq"],0,5,fills)
    assert report["summary"]["fill_count"] == 2
    assert report["summary"]["total_fees"] == 3
    assert report["summary"]["current_cash"] == pytest.approx(99547)
    assert report["summary"]["current_invested"] == pytest.approx(750)
    assert report["summary"]["current_equity"] == pytest.approx(100297)
    assert report["summary"]["profitable_exit_rate_pct"] == 100
    pos = report["allocations"][0]
    assert pos["quantity"] == 5
    assert pos["realized_pnl"] == pytest.approx(97.5)
    assert pos["unrealized_pnl"] > 0
    assert report["curve"][2]["cash"] == pytest.approx(98899)
    assert all(item["day"] <= report["end_day"] for item in report["curve"])


def test_missing_candle_mark_is_stale_not_fabricated():
    days = [(START+timedelta(days=i)).date().isoformat() for i in range(7)]
    daily = {"spy":{days[i]:candle(i,100+i*10) for i in (0,1,4,6)},
             "qqq":{days[i]:candle(i,200) for i in range(7)}}
    fills = [{"time":candle(1,110)["time"],"asset_id":"spy","side":"buy",
              "quantity":10,"price":110,"fee":0}]
    report=build_report(days,daily,["spy","qqq"],0,5,fills)
    assert report["curve"][2]["invested"] == 1100
    assert report["curve"][3]["invested"] == 1100
    assert report["curve"][4]["invested"] == 1400
    assert report["allocations"][0]["last_observed_day"] == days[4]


def test_analytics_endpoints_expose_only_revealed_history(tmp_path, monkeypatch):
    monkeypatch.setattr(pa,"DB_PATH",tmp_path/"arcade.sqlite3")
    monkeypatch.setattr(arcade,"GAME_DB",tmp_path/"arcade.sqlite3")
    prices=[candle(i, 90+i*.4) for i in range(180)]
    monkeypatch.setattr(pa,"history",lambda aid,period:{"bars":prices,"source":"fixture"})
    monkeypatch.setattr(arcade,"history",lambda aid,period:{"bars":prices,"source":"fixture"})
    p=pa.create_season(["spy","qqq"],"5Y",.35)
    rep=client.get(f"/api/portfolio-seasons/{p['id']}/analytics")
    assert rep.status_code==200
    payload=rep.json()
    assert len(payload["curve"])==1
    assert payload["end_day"]==p["day"]
    assert payload["summary"]["fill_count"]==0
    more=pa.advance(p["id"],7)
    report=client.get(f"/api/portfolio-seasons/{p['id']}/analytics").json()
    assert len(report["curve"])==8
    assert report["end_day"]==more["day"]
    assert report["rolling"]["20"] is None

    a=arcade.start_run("spy",period="5Y",starting_point=.35)
    single=client.get(f"/api/arcade/{a['id']}/analytics")
    assert single.status_code==200
    assert single.json()["end_day"]==datetime.fromtimestamp(a["bars"][-1]["time"],timezone.utc).date().isoformat()
    assert len(single.json()["curve"])==1
