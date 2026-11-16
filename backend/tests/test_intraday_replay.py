"""Offline verification of minute-candle fetch, replay, analytics and calendars."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import arcade, intraday, portfolio_arcade as portfolio
from backend.main import app

UTC = timezone.utc
FIRST = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)


def minute_bars(asset_id, count=420):
    # Three trading sessions so USD crypto and US equities genuinely overlap.
    series=[]
    for index in range(count):
        day=index//140
        step=index%140
        t=FIRST+timedelta(days=day,minutes=step)
        if asset_id=="btcusd":
            t+=timedelta(seconds=30)
        price=110 + index*.02 + (7 if asset_id=="btcusd" else 0)
        series.append({"time":int(t.timestamp()), "open":price,
                       "high":price+1,"low":price-1,"close":price,
                       "volume":100})
    return series


def fake_source(asset_id, period, resolution):
    assert resolution in ("1m", "5m", "15m", "1h")
    return {"asset_id":asset_id, "range":f"{period}_{resolution}",
            "resolution":resolution,"source":"test intraday feed",
            "bars":minute_bars(asset_id)}


def test_replay_window_matrix():
    intraday.validate_replay_window("7D", "1m")
    intraday.validate_replay_window("60D", "5m")
    intraday.validate_replay_window("1Y", "1h")
    intraday.validate_replay_window("MAX", "1d")
    for period, interval in [("10Y","1m"),("1Y","5m"),("7D","1d"),("10Y","1h"),("7D","invalid")]:
        with pytest.raises(HTTPException) as ex:
            intraday.validate_replay_window(period,interval)
        assert ex.value.status_code==422


def test_yahoo_intraday_time_and_ohlc(monkeypatch):
    class MockTicker:
        def __init__(self,symbol):
            assert symbol=="AAPL"
        def history(self, **kwargs):
            assert kwargs["interval"]=="1m"
            assert kwargs["prepost"] is False
            timestamps=pd.date_range(FIRST,periods=3,freq="min",tz="UTC")
            return pd.DataFrame({"Open":[12.,12.5,13.],"High":[13.,13.5,14.],
                "Low":[11.,12.,12.5],"Close":[12.5,13.,13.2],"Volume":[100,150,80]},index=timestamps)
    monkeypatch.setattr(intraday.market.yf,"Ticker",MockTicker)
    from backend.assets import get_instrument
    rows=intraday.fetch_yahoo(get_instrument("aapl"),FIRST,FIRST+timedelta(hours=1),"1m")
    assert len(rows)==3
    assert rows[0]["time"]==int(FIRST.timestamp())
    assert rows[1]["open"]==12.5


def test_coinbase_granularity_is_exact_and_bounded(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):return [
            [int(FIRST.timestamp()),100,102,101,101.5,300],
            [int((FIRST+timedelta(minutes=1)).timestamp()),100,103,101.5,102,400],
        ]
    seen=[]
    class Client:
        def get(self,url,params):
            seen.append((url,params))
            return Response()
    monkeypatch.setattr(intraday.market,"_client",Client())
    from backend.assets import get_instrument
    rows=intraday.fetch_coinbase(get_instrument("btcusd"),FIRST,FIRST+timedelta(minutes=3),"1m")
    assert len(rows)==2
    assert seen[0][1]["granularity"]==60
    assert seen[0][0].endswith("/BTC-USD/candles")


def test_single_minute_replay_fill_and_distinct_analytics_rows(monkeypatch,tmp_path):
    monkeypatch.setattr(arcade,"GAME_DB",tmp_path/"minute.sqlite3")
    monkeypatch.setattr(arcade,"replay_history",fake_source)
    game=arcade.start_run("aapl",period="7D",resolution="1m")
    assert game["resolution"]=="1m"
    assert len(game["bars"])<game["total_bars"]
    initial=game["bars"][-1]["time"]
    arcade.submit_order(game["id"],"buy","market","10","units")
    advanced=arcade.advance_run(game["id"],1)
    assert advanced["fills"][0]["time"]>initial
    arcade.submit_order(game["id"],"buy","market","5","units")
    twice=arcade.advance_run(game["id"],1)
    assert twice["fills"][0]["time"]!=twice["fills"][1]["time"]
    report=arcade.get_analysis(game["id"])
    assert len(report["curve"])==3
    assert report["resolution"]=="1m"
    assert len({p["day"] for p in report["curve"]})==3
    assert report["summary"]["fill_count"]==2
    assert len(report["executions"])==2
    assert report["end_day"].startswith("2026-")


def test_portfolio_interleaved_intraday_clocks_and_stale_marks(monkeypatch,tmp_path):
    monkeypatch.setattr(portfolio,"DB_PATH",tmp_path/"portfolio.sqlite3")
    monkeypatch.setattr(portfolio,"replay_history",fake_source)
    run=portfolio.create_season(["spy","btcusd"],period="7D",resolution="1m")
    assert run["resolution"]=="1m"
    assert "T" in run["day"]
    assert run["bars"]["spy"][-1]["time"]<=int(datetime.fromisoformat(run["day"]).timestamp())
    portfolio.order(run["id"],"spy","buy","market","3","units")
    portfolio.order(run["id"],"btcusd","buy","market","2","units")
    after=portfolio.advance(run["id"],5)
    assert len(after["fills"])==2
    assert after["fills"][0]["time"]!=after["fills"][1]["time"]
    report=portfolio.get_analysis(run["id"])
    assert report["resolution"]=="1m"
    assert len(report["executions"])==2
    assert report["summary"]["current_invested"]>0
    assert report["end_day"]==after["day"]
    assert len(report["curve"])==6


def test_http_create_minute_portfolio_rejects_invalid_windows(monkeypatch,tmp_path):
    monkeypatch.setattr(portfolio,"DB_PATH",tmp_path/"api.sqlite3")
    monkeypatch.setattr(portfolio,"replay_history",fake_source)
    client=TestClient(app)
    resp=client.post("/api/portfolio-seasons",json={
        "asset_ids":["spy","qqq"],"period":"7D","resolution":"1m",
    })
    assert resp.status_code==200
    assert resp.json()["resolution"]=="1m"
    bad=client.post("/api/portfolio-seasons",json={
        "asset_ids":["spy","qqq"],"period":"10Y","resolution":"1m",
    })
    assert bad.status_code==422


def test_terminal_market_api_can_request_minute_candles(monkeypatch):
    from backend import intraday as module
    monkeypatch.setattr(module, "replay_history", fake_source)
    client=TestClient(app)
    result=client.get("/api/market/aapl?range=7D&resolution=1m")
    assert result.status_code==200
    assert result.json()["resolution"]=="1m"
    assert len(result.json()["bars"])==420


def test_intraday_and_daily_archives_use_distinct_files(tmp_path, monkeypatch):
    from backend import archive
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path))
    daily=archive.archive_path("spy","1Y")
    minute=archive.archive_path("spy","7D_1m")
    hourly=archive.archive_path("spy","1Y_1h")
    assert daily != minute != hourly
    assert minute.name == "7D_1m.parquet"
    with pytest.raises(HTTPException):
        archive.archive_path("spy","../7D_1m")
