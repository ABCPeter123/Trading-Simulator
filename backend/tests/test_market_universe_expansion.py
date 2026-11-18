"""Offline, synthetic regression tests for expanded market instrument coverage.

Never downloads market data, accesses owner watchlists, or sends strategy data.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import assets, archive, market, intraday, market_ingestion as ingest
from backend.main import app

UTC = timezone.utc


def test_catalog_includes_diversified_us_canadian_and_reference_instruments():
    catalog = assets.list_instruments(limit=1000)
    assert len(catalog) >= 320
    assert len(catalog) == len(set(i["id"] for i in catalog))
    assert len(set(i["symbol"] for i in catalog if i["symbol"])) == len(
        [i for i in catalog if i["symbol"]])
    for asset_id, category, currency, allowed in [
        ("xbal", "ETFs", "CAD", False),
        ("vdy", "ETFs", "CAD", False),
        ("hdiv", "ETFs", "CAD", False),
        ("vab", "ETFs", "CAD", False),
        ("vxus", "ETFs", "USD", True),
        ("sgov", "ETFs", "USD", True),
        ("spx", "Indices", "USD", False),
        ("tsx", "Indices", "CAD", False),
        ("hg", "Futures", "USD", False),
        ("usdcny", "Forex", "CNY", False),
        ("cm", "Stocks", "CAD", False),
        ("csu", "Stocks", "CAD", False),
        ("spym", "ETFs", "USD", True),
    ]:
        asset = assets.get_instrument(asset_id)
        assert (asset.kind, asset.currency, asset.tradable) == (
            category, currency, allowed)
    assert len(TestClient(app).get("/api/instruments?limit=2000").json()) >= 320
    assert TestClient(app).get("/api/instruments?limit=2001").status_code == 422


def test_15_and_20_year_daily_yahoo_use_explicit_valid_start_end(monkeypatch):
    seen = []
    class Provider:
        def history(self, **kwargs):
            seen.append(kwargs)
            return pd.DataFrame(
                {"Open":[100.,101.], "High":[101.,102.], "Low":[99.,100.],
                 "Close":[100.5,101.5], "Volume":[5000.,6000.]},
                index=pd.to_datetime(["2010-01-04T21:00:00Z",
                                      "2010-01-05T21:00:00Z"]))
    monkeypatch.setattr(market.yf, "Ticker", lambda _: Provider())
    for window, years in [("15Y",15),("20Y",20)]:
        bars = market.yahoo_candles(assets.get_instrument("spy"),window)
        assert len(bars) == 2
        params = seen[-1]
        assert params["interval"] == "1d"
        assert "period" not in params
        assert params["auto_adjust"] is False
        first = datetime.fromisoformat(params["start"])
        last = datetime.fromisoformat(params["end"])
        assert years*365 <= (last-first).days <= years*366
    assert market.RANGE_CONFIG["20Y"][2] >= 5000


def test_extended_windows_are_shared_between_replay_and_archive(monkeypatch,tmp_path):
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR",str(tmp_path))
    for window in ("15Y","20Y","MAX"):
        intraday.validate_replay_window(window,"1d")
        assert archive.archive_path("spy",window).name == window+".parquet"
    intraday.validate_replay_window("2Y","1h")
    assert archive.archive_path("spy","2Y_1h").name == "2Y_1h.parquet"
    assert intraday.MAX_INTRADAY_BARS >= 17520
    for window,resolution in [("15Y","1m"),("20Y","1h"),("2Y","5m")]:
        with pytest.raises(HTTPException):
            intraday.validate_replay_window(window,resolution)


def test_local_archive_returns_full_twenty_year_history_not_last_5000(monkeypatch,tmp_path):
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR",str(tmp_path))
    start=int(datetime(2004,1,1,tzinfo=UTC).timestamp())
    bars=[]
    for i in range(6200):
        close=50+i/50.
        bars.append({"time":start+i*86400,"open":close,
                     "high":close+1,"low":close-1,"close":close,
                     "volume":100+i})
    archive.record_history({"asset_id":"spy","range":"20Y","bars":bars})
    recovered=archive.load_archived_history("spy","20Y")
    assert len(recovered) == 6200
    assert recovered[0]["time"] == bars[0]["time"]
    assert recovered[-1]["time"] == bars[-1]["time"]
    assert recovered[0]["close"] == pytest.approx(50)
    assert archive.archive_stats("spy","20Y")["bars"] == 6200


def test_backfill_cli_preset_and_bounded_local_operation():
    script = Path(__file__).resolve().parents[2]/"scripts"/"backfill-market-history.py"
    helper = runpy.run_path(str(script))
    choose=helper["target_ids"]
    assert len(choose("diversified","spy,qqq",50)) >= 20
    assert choose(None,"spy,qqq,spy",50) == ["spy","qqq"]
    with pytest.raises(ValueError):
        choose(None,"",50)
    with pytest.raises(HTTPException):
        choose(None,"madeup_symbol",50)
    with pytest.raises(ValueError):
        choose("diversified","",3)
    seen=[]
    sleeps=[]
    base=int(datetime(2006,1,1,tzinfo=UTC).timestamp())
    def fake_fetch(asset_id,window):
        assert window=="20Y"
        seen.append(asset_id)
        return {"asset_id":asset_id,"bars":[
            {"time":base,"close":10}, {"time":base+86400,"close":11}],
            "offline_cache":False}
    events=[]
    result=helper["backfill"](["spy","qqq"],"20Y",0.25,
                             fetch=fake_fetch,pause=sleeps.append,emit=events.append)
    assert seen==["spy","qqq"]
    assert sleeps==[0.25]
    assert result["downloaded"]==2
    assert result["bars"]==4
    assert len(events)==2
    with pytest.raises(ValueError):
        helper["backfill"](["spy"],"1m",1,fetch=fake_fetch)


def test_wider_market_ingestion_schedules_fairly_and_rate_limits(tmp_path,monkeypatch):
    monkeypatch.setattr(ingest,"DB_PATH",tmp_path/"ingest.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    assert ingest.MAX_SUBSCRIPTIONS==100
    assert ingest.MAX_DUE_PER_CYCLE<=10
    instruments=[
        "spy","qqq","iwm","vti","xlf","xle","gld","slv",
        "tlt","ief","sgov","lqd","hyg","voo","vug",
    ]
    for asset_id in instruments:
        ingest.subscribe(asset_id,"5m")
    called=[]
    monkeypatch.setattr(ingest,"ingest_once",lambda asset_id,resolution,now:
                        (called.append(asset_id) or {"latest":int(now.timestamp()),
                                                     "added":1}))
    monkeypatch.setattr(ingest.market,"market_open",lambda *_: True)
    now=datetime(2026,11,17,15,0,tzinfo=UTC)
    first=ingest.run_due(now)
    assert len(first)==10
    second=ingest.run_due(now+timedelta(seconds=90))
    assert len(second)==5
    assert len(set(called))==15
    assert set(called)==set(instruments)



def test_bulk_all_catalog_plan_has_no_duplicate_tasks_or_undated_options():
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                "scripts" / "backfill-market-history.py"))
    all_ids = helper["target_ids"](None, "", 2000, all_catalog=True)
    assert len(all_ids) >= 320
    assert len(all_ids) == len(set(all_ids))
    assert "aapl-opt" not in all_ids
    assert "spy-opt" not in all_ids
    with pytest.raises(ValueError):
        helper["target_ids"]("canada", "spy", 2000, all_catalog=True)
    plan = helper["download_plan"](["spy", "spy", "qqq", "spy"], "MAX", True)
    assert len(plan) == 10  # one daily plus four distinct intraday intervals
    assert len(plan) == len(set(plan))
    assert plan[0] == ("spy", "1d", "MAX")
    assert ("spy", "1h", "2Y") in plan
    assert ("spy", "5m", "60D") in plan
    # NAV-only mutual funds never get fabricated intraday subscriptions.
    asset = assets.Instrument("synthetic-nav", "SYNTHETIC", "Funds")
    original = assets.INSTRUMENTS.get("synthetic-nav")
    try:
        assets.INSTRUMENTS["synthetic-nav"] = asset
        assert helper["download_plan"](["synthetic-nav"], "MAX", True) == [
            ("synthetic-nav", "1d", "MAX")]
    finally:
        if original is None:
            assets.INSTRUMENTS.pop("synthetic-nav", None)
        else:
            assets.INSTRUMENTS["synthetic-nav"] = original


def test_bulk_resume_skips_archive_even_without_checkpoint_and_preserves_unique_bars(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path / "market"))
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                "scripts" / "backfill-market-history.py"))
    checkpoint = tmp_path / "private-progress.json"
    start = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    fetches = []
    def fake_fetch(asset_id, window):
        fetches.append((asset_id, window))
        # Intentional duplicate stamp, repeated across consecutive downloads.
        candles = [
            {"time": start, "open": 10., "high": 11., "low": 9.,
             "close": 10., "volume": 20.},
            {"time": start, "open": 10., "high": 12., "low": 9.,
             "close": 11., "volume": 23.},
            {"time": start + 86400, "open": 12., "high": 13., "low": 11.,
             "close": 12., "volume": 25.},
        ]
        archive.record_history({"asset_id": asset_id, "range": window,
                                "bars": candles, "is_demo": False})
        return {"bars": candles, "is_demo": False}
    first = helper["backfill_catalog"](
        ["spy", "spy"], "MAX", 0, checkpoint=checkpoint, fetch_daily=fake_fetch)
    assert first["requested"] == 1
    assert first["downloaded"] == 1
    assert first["skipped_existing"] == 0
    assert fetches == [("spy", "MAX")]
    assert archive.archive_stats("spy", "MAX")["bars"] == 2
    recorded = archive.load_archived_history("spy", "MAX")
    assert len(recorded) == len({row["time"] for row in recorded})
    assert recorded[0]["close"] == 11.

    # Progress JSON can disappear after a crash, but valid Parquet survives.
    checkpoint.unlink()
    second = helper["backfill_catalog"](
        ["spy"], "MAX", 0, checkpoint=checkpoint, fetch_daily=fake_fetch)
    assert second["downloaded"] == 0
    assert second["skipped_existing"] == 1
    assert fetches == [("spy", "MAX")]
    assert checkpoint.is_file()

    # Explicit refresh may correct old prices, but never duplicates timestamps.
    third = helper["backfill_catalog"](
        ["spy"], "MAX", 0, checkpoint=checkpoint,
        fetch_daily=fake_fetch, refresh=True)
    assert third["downloaded"] == 1
    assert len(fetches) == 2
    assert archive.archive_stats("spy", "MAX")["bars"] == 2


def test_bulk_failed_task_retries_but_completed_work_is_never_fetched_twice(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path / "market"))
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                "scripts" / "backfill-market-history.py"))
    base = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    attempts = []
    def flaky(asset_id, window):
        attempts.append(asset_id)
        if asset_id == "qqq" and attempts.count("qqq") == 1:
            raise ValueError("Simulated transient provider failure.")
        candle = {"time": base, "open": 10., "high": 11.,
                  "low": 9., "close": 10., "volume": 20.}
        archive.record_history({"asset_id": asset_id, "range": window,
                                "bars": [candle]})
        return {"bars": [candle]}
    checkpoint = tmp_path / "checkpoint.json"
    first = helper["backfill_catalog"](
        ["spy", "qqq"], "MAX", 0, checkpoint=checkpoint, fetch_daily=flaky)
    assert (first["downloaded"], first["unavailable"]) == (1, 1)
    second = helper["backfill_catalog"](
        ["spy", "qqq"], "MAX", 0, checkpoint=checkpoint, fetch_daily=flaky)
    assert (second["skipped_existing"], second["downloaded"]) == (1, 1)
    assert attempts == ["spy", "qqq", "qqq"]
    assert archive.archive_stats("spy", "MAX")["bars"] == 1
    assert archive.archive_stats("qqq", "MAX")["bars"] == 1


def test_bulk_dry_run_never_fetches_history(monkeypatch, capsys, tmp_path):
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                "scripts" / "backfill-market-history.py"))
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path / "market"))
    monkeypatch.setattr(market, "history", lambda *_:
                        (_ for _ in ()).throw(AssertionError("Network forbidden")))
    assert helper["main"](["--all", "--include-intraday", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "distinct download tasks" in output
    assert "Existing complete Parquet windows will be skipped" in output
    assert not (tmp_path / "market").exists()
