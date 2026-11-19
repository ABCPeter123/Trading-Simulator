"""Offline portfolio research regression tests. All series independently synthetic.

Actual owner holdings, strategy parameters and real price histories are not
present in source code, GitHub Actions, or shared test fixtures.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import portfolio_research as p
from backend.main import app


START = datetime(2021, 1, 1, tzinfo=timezone.utc)
SYMBOLS = ("spy", "ief", "gld", "eem", "btcusd")
CLIENT = TestClient(app)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "DB_PATH", tmp_path / "private-portfolio.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO", raising=False)
    return tmp_path


def synthetic(n=660, shock=False):
    market = {}
    for j,symbol in enumerate(SYMBOLS):
        rows = []
        price = 80.0 + 20*j
        for i in range(n):
            day = START + timedelta(days=i)
            if symbol!="btcusd" and day.weekday()>=5:
                continue
            change = .0005 + .007*math.sin(i/(13+j*2)+j) + .002*math.sin(i/5+j)
            if symbol=="ief":
                change = .00005-.002*math.sin(i/17)
            if symbol=="gld":
                change = .0003+.003*math.sin(i/9+2)
            if shock and i>int(n*.8) and symbol in ("spy","eem"):
                change -= .025
            previous=price
            price = max(5.,price*(1+change))
            rows.append({"time":int(day.timestamp()),"open":previous,
                         "high":max(previous,price)*1.005,
                         "low":min(previous,price)*.995,
                         "close":price,"volume":50000})
        market[symbol]={"source":"synthetic fixture","bars":rows}
    return market


def test_multi_asset_portfolio_compares_five_models_and_persists(isolated):
    result=p.compare(list(SYMBOLS),max_drawdown_pct=50,data=synthetic())
    assert result["basket"]==list(SYMBOLS)
    assert len(result["groups"])>=3
    assert len(result["candidates"])==len(p.MODELS)
    assert {c["model"] for c in result["candidates"]}==set(p.MODELS)
    assert not result["test_used_for_selection"]
    assert result["sessions"]>=450
    assert result["selected"] is not None
    assert p.list_runs()[0]["basket"]==list(SYMBOLS)
    assert p.load_run(result["id"])["id"]==result["id"]
    assert result["selected"]["held_out_test"]["equity_curve"]
    assert result["selected"]["held_out_equal_weight_benchmark"]["equity_curve"]


def test_heldout_prices_can_change_only_heldout_metrics_not_selection(isolated):
    a=p.compare(list(SYMBOLS),max_drawdown_pct=50,data=synthetic())
    b=p.compare(list(SYMBOLS),max_drawdown_pct=50,data=synthetic(shock=True))
    assert [(x["model"],x["score"],x["qualified"]) for x in a["candidates"]]==[
        (x["model"],x["score"],x["qualified"]) for x in b["candidates"]]
    assert a["selected"]["model"]==b["selected"]["model"]
    assert a["selected"]["held_out_test"]["return_pct"]!=b["selected"]["held_out_test"]["return_pct"]


def test_no_future_close_signal_and_next_open_execution(isolated):
    symbols=["spy","ief","gld"]
    days,market,meta,_=p._prepare(symbols,{s:synthetic()[s] for s in symbols})
    closes={s:[x["close"] for x in market[s]] for s in symbols}
    i=210
    baseline=p._weights("trend_filter",symbols,closes,i,meta,.35)
    for sym in symbols:
        for j in range(i,len(market[sym])):
            market[sym][j]["close"]*=2.5
            # Alter current and subsequent bars; current open must remain unchanged
    updated={s:[x["close"] for x in market[s]] for s in symbols}
    assert p._weights("trend_filter",symbols,updated,i,meta,.35)==baseline


def test_shared_cash_asset_and_group_caps_no_leverage(isolated):
    symbols=list(SYMBOLS)
    days,market,meta,_=p._prepare(symbols,synthetic())
    metrics=p._segment("inverse_volatility",symbols,market,meta,180,260,.35)
    assert metrics["ending_equity"]>0
    assert metrics["trades"]>0
    assert metrics["fees"]>0
    assert metrics["turnover_pct"]>0
    for reb in metrics["rebalances"]:
        weights=reb["weights"]
        assert 0<=reb["cash_pct"]<=100
        assert sum(weights.values())<=.951
        assert all(-1e-8<=w<=.351 for w in weights.values())
        for group,cap in p.GROUP_CAPS.items():
            assert sum(w for symbol,w in weights.items() if meta[symbol]["group"]==group)<=cap+.002
    assert all(x["execution"]=="next_session_open" for x in metrics["executions"])


def test_not_same_calendar_session_never_filled_using_previous_candle(isolated):
    data=synthetic()
    # Remove stock candle for a weekday; no fabricated/backfilled bars.
    data["spy"]["bars"].pop(55)
    symbols=list(SYMBOLS)
    days,market,meta,_=p._prepare(symbols,data)
    assert len(days)==len(market["spy"])==len(market["btcusd"])
    for i,day in enumerate(days):
        assert datetime.fromtimestamp(market["spy"][i]["time"],timezone.utc).date().isoformat()==day
        assert datetime.fromtimestamp(market["btcusd"][i]["time"],timezone.utc).date().isoformat()==day


def test_reject_invalid_baskets_demo_and_short_data(isolated,monkeypatch):
    with pytest.raises(HTTPException):
        p.compare(["spy"],data=synthetic())
    with pytest.raises(HTTPException):
        p.compare(["spy","spy"],data=synthetic())
    with pytest.raises(HTTPException):
        p.compare(["spy","ief"],data={"spy":synthetic()["spy"]})
    with pytest.raises(HTTPException):
        p.compare(list(SYMBOLS),data={s:{"bars":synthetic()[s]["bars"][:100]}
                                         for s in SYMBOLS})
    data=synthetic()
    data["gld"]["is_demo"]=True
    with pytest.raises(HTTPException):
        p.compare(list(SYMBOLS),data=data)
    monkeypatch.setenv("TRADING_SIM_PUBLIC_DEMO","1")
    with pytest.raises(HTTPException) as exc:
        p.compare(list(SYMBOLS),data=synthetic())
    assert exc.value.status_code==403
    assert not p.DB_PATH.exists()


def test_bad_candles_are_not_silently_repaired(isolated):
    for field,invalid in [("open",float("nan")),("close",-2),("high",1)]:
        data=synthetic()
        data["gld"]["bars"][15][field]=invalid
        with pytest.raises(HTTPException):
            p.compare(list(SYMBOLS),data=data)
    data=synthetic()
    data["spy"]["bars"][8]["time"]=data["spy"]["bars"][7]["time"]
    with pytest.raises(HTTPException):
        p.compare(list(SYMBOLS),data=data)


def test_private_api_rejects_public_demo_without_accessing_database(isolated,monkeypatch):
    from backend import main
    monkeypatch.setattr(main,"PUBLIC_DEMO",True)
    response=CLIENT.get("/api/live/research/portfolio/runs")
    assert response.status_code==403
    response=CLIENT.post("/api/live/research/portfolio/compare",
                         json={"symbols":["spy","ief"]})
    assert response.status_code==403
    assert not p.DB_PATH.exists()


def test_read_and_list_api_return_private_runs(isolated):
    # Keep this path offline by filling via a synthetic-only direct service call.
    experiment=p.compare(list(SYMBOLS),max_drawdown_pct=50,data=synthetic())
    overview=CLIENT.get("/api/live/research/portfolio/runs")
    assert overview.status_code==200
    assert overview.json()[0]["id"]==experiment["id"]
    detail=CLIENT.get("/api/live/research/portfolio/runs/"+experiment["id"])
    assert detail.status_code==200
    assert detail.json()["selected"]["model"]==experiment["selected"]["model"]


def test_cli_offline_comparison_uses_private_data_path_not_public_demo(isolated,monkeypatch,capsys):
    from backend import portfolio_research_cli as cli
    data=synthetic()
    monkeypatch.setattr(p,"history",lambda symbol,window:data[symbol])
    assert cli.main(["--symbols",",".join(SYMBOLS),"--max-drawdown","50"])==0
    output=capsys.readouterr().out
    assert "validation net return" in output
    assert "HELD-OUT" in output
    assert "No broker orders" in output
    assert len(p.list_runs())==1
    assert p.DB_PATH.exists()


def test_reit_and_bitcoin_etf_use_exposure_group_caps(isolated):
    assert p._group("vnq","ETFs")=="real_estate"
    assert p._group("ibit","ETFs")=="crypto"
    assert p.GROUP_CAPS["real_estate"]<=.2
    assert p.GROUP_CAPS["crypto"]<=.1



def test_rebalance_cadence_changes_check_frequency_without_intraday_fills(isolated):
    symbols=["spy","ief","gld"]
    days, market, meta, _ = p._prepare(symbols, synthetic())
    reports={}
    for cadence in (1,5,21):
        run=p._segment("equal_weight",symbols,market,meta,180,222,.35,
                       broker={"rebalance_sessions":cadence,"slippage_bps":8.,
                               "commission_usd":0.,"base_currency":"USD"})
        reports[cadence]=run
        assert len(run["rebalances"])==(42+cadence-1)//cadence
        assert all(t["execution"]=="next_session_open" for t in run["executions"])
    assert len(reports[1]["rebalances"])>len(reports[5]["rebalances"])>len(reports[21]["rebalances"])
    # More decisions need not imply more trades; actual target changes determine orders.
    for invalid in (0,2,3,True,1.0):
        with pytest.raises(ValueError,match="rebalance cadence"):
            p._segment("equal_weight",symbols,market,meta,180,222,.35,
                       broker={"rebalance_sessions":invalid})
