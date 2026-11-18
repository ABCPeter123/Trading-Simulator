"""Synthetic reproducibility and fail-closed promotion tests for model blends."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
from math import sin
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import tournament_strategies as saved
from backend import universe_research as universe
from backend import strategy_period_analysis as periods
from backend import strategy_source as source
from backend import walkforward_optimizer as walkforward
from backend.main import app


def version():
    return {
        "version":2,"model":"blended_portfolio",
        "symbols":["spy","qqq","ief"],
        "max_position_pct":40.,"delay_sessions":1,"rebalance_sessions":21,
        "sleeves":[{"model":"relative_momentum","weight_pct":60.},
                   {"model":"inverse_volatility","weight_pct":40.}],
        "research_only":True,
        "target_investment_pct":95.,"equity_class_cap_pct":70.,
        "redistribute_excess":False,
        "base_currency":"USD","slippage_bps":9.,
        "commission_usd":1.,"fx_conversion_bps":150.,
    }


def bars(scale=1.):
    start=datetime(2021,1,1,tzinfo=timezone.utc)
    result=[]
    for i in range(1060):
        day=start+timedelta(days=i)
        if day.weekday()>4:continue
        px=scale*75*(1.00035**i)*(1+.009*sin(i/13))
        result.append({"time":int(day.timestamp()),"open":px*1.0002,
                       "high":px*1.03,"low":px*.97,
                       "close":px,"volume":100000})
    return result


def test_blend_schema_strict_and_no_unexpected_live_source(monkeypatch):
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    spec=version()
    assert saved.validate_spec(spec)["sleeves"]==spec["sleeves"]
    for patch in (
        {"sleeves":[]},
        {"sleeves":[{"model":"leveraged_trend","weight_pct":50.},
                    {"model":"equal_weight","weight_pct":50.}]},
        {"research_only":False},{"version":1},
        {"base_currency":"EUR"},
        {"commission_usd":-1.},
    ):
        with pytest.raises(HTTPException) as error:
            saved.validate_spec({**spec,**patch})
        assert error.value.status_code==422
    report=source.source_for_model(spec,"research")
    assert report["entry_point"]=="backend.blended_portfolio_research.blend_weights"
    assert report["research_execution_entry_point"]=="backend.blended_portfolio_research.segment"
    assert any(f["path"]=="backend/blended_portfolio_research.py" for f in report["files"])
    for context in ("live","simulation"):
        with pytest.raises(HTTPException) as error:
            source.source_for_model(spec,context)
        assert error.value.status_code==422


def test_immutable_import_and_research_only_boundary(tmp_path,monkeypatch):
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    monkeypatch.setattr(universe,"DB_PATH",tmp_path/"universe.sqlite3")
    monkeypatch.setattr(saved,"DB_PATH",tmp_path/"versions.sqlite3")
    winner={"rank":1,"basket_type":"synthetic_test","model":"blended_portfolio",
            "symbols":["spy","qqq","ief"],"sleeves":version()["sleeves"],
            "research_only":True,"restricted_research":False,
            "short_proxy_research":False}
    params={"scope":"etfs","delay_sessions":1,"max_drawdown_pct":30.,
            "max_position_pct":40.,"base_currency":"USD","slippage_bps":9.,
            "commission_usd":1.,"fx_conversion_bps":150.}
    with closing(universe._connection()) as db:
        db.execute("INSERT INTO universe_jobs (id,status,created_at,updated_at,stage,params,result) "
                   "VALUES (?,?,?,?,?,?,?)",
                   ("synthetic-blend-study","completed","2026-01-01","2026-01-01",
                    "Study complete",json.dumps(params),
                    json.dumps({"top10":[winner]})))
    first=saved.import_rank("synthetic-blend-study",1)
    second=saved.import_rank("synthetic-blend-study",1)
    assert first["id"]==second["id"]
    assert first["research_only"] is True
    assert first["sleeves"]==version()["sleeves"]
    assert first["commission_usd"]==1.
    assert len(saved.list_saved())==1
    assert TestClient(app).post(
        "/api/live/research/universe/strategy-source",
        json={"spec":json.loads(first["code"]),"context":"live"}).status_code==422


def test_exact_sleeves_historical_reexecution_and_stress(monkeypatch):
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    original=version()
    original["target_investment_pct"]=100.
    original["equity_class_cap_pct"]=100.
    market={"spy":bars(1.),"qqq":bars(1.3),"ief":bars(.75)}
    loader=lambda symbol:{"source":"Independent synthetic fixture","bars":market[symbol]}
    output=periods.analyze({"spec":original},loader=loader)
    assert output["model"]=="blended_portfolio"
    assert output["sleeves"]==original["sleeves"]
    assert output["research_only"] is True
    assert output["assumptions"]["base_currency"]=="USD"
    assert output["assumptions"]["commission_usd"]==1.
    assert output["assumptions"]["target_investment_pct"]==100.
    assert output["metrics"]["trades"]>0
    assert output["metrics"]["average_invested_pct"]<=100.001
    assert output["metrics"]["fees"]>0
    assert output["fills_total"]==output["metrics"]["trades"]
    assert output["execution_stress"]["return_pct"]!=output["metrics"]["return_pct"]
    changed=periods.analyze({"spec":{**original,"sleeves":[
        {"model":"trend_filter","weight_pct":60.},
        {"model":"inverse_volatility","weight_pct":40.}]}},loader=loader)
    assert changed["sleeves"]!=output["sleeves"]


def test_walkforward_initial_candidate_preserves_selected_sleeves():
    spec=version()
    request={"spec":spec,"search_width":"focused",
             "base_currency":"USD","commission_usd":1.,
             "fx_conversion_bps":150.,"slippage_bps":9.}
    parsed=walkforward.validate_request(request)
    candidates=list(walkforward.candidates(parsed["spec"],parsed["search_width"]))
    assert candidates[0]["model"]=="blended_portfolio"
    assert candidates[0]["sleeves"]==spec["sleeves"]
    assert len(candidates)<=12
    assert all(c["delay_sessions"]==spec["delay_sessions"] for c in candidates)
