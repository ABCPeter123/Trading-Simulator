"""Synthetic-only checks for research execution assumptions and score transparency.

Never serialize owner strategy parameters, real market observations or trades.
"""
from datetime import datetime, timedelta, timezone
from math import sin

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import performance_objectives as objectives
from backend import universe_research as universe
from backend import walkforward_optimizer as walkforward
from backend.main import app


def _curve(n=160):
    start=datetime(2022,1,3,tzinfo=timezone.utc)
    equity=100000.
    result=[]
    for i in range(n):
        equity*=1.0008+.001*sin(i/8)
        result.append({"time":int((start+timedelta(days=i)).timestamp()),
                       "value":equity})
    return result


def _synthetic_bars():
    start=datetime(2020,1,1,tzinfo=timezone.utc)
    bars=[]
    for i in range(1080):
        day=start+timedelta(days=i)
        if day.weekday()>=5:
            continue
        px=60*(1.00032**i)*(1+.006*sin(i/18))
        bars.append({"time":int(day.timestamp()),"open":px*1.0001,
                     "high":px*1.02,"low":px*.98,"close":px,"volume":90000})
    return bars


def test_transparent_score_matches_legacy_and_does_not_use_audit():
    validation={"return_pct":22.,"max_drawdown_pct":-12.,
                "turnover_pct":175.,"trades":6}
    details,metrics,stability=objectives.score_breakdown(
        validation,_curve(),risk_free_pct=3.,target_cagr_pct=42.,
        target_sharpe=1.4,drawdown_limit=25.)
    legacy,legacy_quality,legacy_stability=objectives.score(
        validation,_curve(),risk_free_pct=3.,target_cagr_pct=42.,
        target_sharpe=1.4,drawdown_limit=25.)
    assert details["total"]==legacy
    assert metrics==legacy_quality and stability==legacy_stability
    assert sum(details["components"].values())==pytest.approx(legacy,abs=.0001)
    assert details["components"]["drawdown_points"]<0
    assert details["components"]["turnover_points"]<0
    assert "held_out" not in details["inputs"]
    changed={**validation,"turnover_pct":350.}
    worse,_,_=objectives.score_breakdown(changed,_curve(),risk_free_pct=3.,
                                          target_cagr_pct=42.,target_sharpe=1.4,
                                          drawdown_limit=25.)
    assert worse["total"]<legacy


def test_usd_cost_defaults_and_input_validation(tmp_path,monkeypatch):
    monkeypatch.setattr(universe,"DB_PATH",tmp_path/"study.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    client=TestClient(app)
    posted=client.post("/api/live/research/universe/jobs",json={
        "scope":"etfs","base_currency":"USD","commission_usd":0,
        "fx_conversion_bps":150,"slippage_bps":8,"include_blends":True})
    assert posted.status_code==202,posted.text
    params=universe.get_job(posted.json()["id"])["params"]
    assert params["base_currency"]=="USD"
    assert params["fx_conversion_bps"]==150
    assert params["include_blends"] is True
    for patch in ({"base_currency":"EUR"},{"slippage_bps":101},
                  {"fx_conversion_bps":1000},{"commission_usd":-1}):
        response=client.post("/api/live/research/universe/jobs",json={**patch})
        assert response.status_code==422


def test_study_blends_and_cost_breakdown_are_read_only(monkeypatch):
    names=["spy","qqq","ief","gld","vti","tlt","shy","xlv"]
    monkeypatch.setattr(universe,"_universe",lambda scope:names)
    bars=_synthetic_bars()
    report=universe.run_study({
        "scope":"all","delay_sessions":1,
        "max_drawdown_pct":60.,"max_position_pct":40.,
        "research_objective":"high_performance",
        "base_currency":"USD","slippage_bps":7.,
        "commission_usd":0.,"fx_conversion_bps":150.,
        "include_blends":True,
    },loader=lambda symbol:{"source":"Independent synthetic fixture","bars":bars})
    assert report["execution_assumptions"]["base_currency"]=="USD"
    assert report["candidate_model_counts"]["blended_portfolio"]>0
    assert report["test_used_for_selection"] is False
    assert report["top10"]
    for choice in report["top10"]:
        assert choice["validation_score"]==choice["score_breakdown"]["total"]
        audit=choice["held_out_cost_audit"]
        assert audit["explicit_total_usd"]>=0
        assert audit["estimated_slippage_usd"]>=0
        assert audit["estimated_spread_usd"]>=0
        assert audit["implicit_costs_already_in_fill_prices"] is True
        if choice["model"]=="blended_portfolio":
            assert len(choice["sleeves"]) in (2,3)
            assert choice["research_only"] is True
    assert len(list(universe._model_configs(include_blends=False)))==len(universe.pr.MODELS)+len(universe.adv.MODELS)
    assert len(list(universe._model_configs(include_blends=True)))>11


def test_walkforward_comprehensive_grid_and_usd_controls():
    spec={"version":1,"model":"equal_weight",
          "symbols":["spy","qqq","ief"],"max_position_pct":40,
          "delay_sessions":1,"rebalance_sessions":21}
    request={"spec":spec,"search_width":"comprehensive",
             "base_currency":"USD","fx_conversion_bps":150.,
             "commission_usd":0.,"slippage_bps":9.}
    settings=walkforward.validate_request(request)
    choices=list(walkforward.candidates(settings["spec"],settings["search_width"]))
    assert len(choices)<=48
    assert len(choices)>24
    assert any(x["model"]=="blended_portfolio" for x in choices)
    assert settings["base_currency"]=="USD"
    for patch in ({"base_currency":"EUR"},{"fx_conversion_bps":500.},
                  {"commission_usd":31.}):
        with pytest.raises(HTTPException):
            walkforward.validate_request({**request,**patch})


def test_cost_audit_separates_implicit_and_explicit_costs():
    bar={"time":123,"open":100.,"close":100.}
    report=universe._execution_cost_audit(
        {"fees":12.,"margin_interest":4.,"short_borrow_cost":2.,
         "executions":[{"symbol":"spy","time":123,"quantity":10}]},
        {"spy":[bar]},{"spy":{"spread_bps":10}},slippage=8.)
    assert report["transaction_and_fx_usd"]==6.
    assert report["estimated_spread_usd"]==.5
    assert report["estimated_slippage_usd"]==.8
    assert report["implicit_costs_already_in_fill_prices"]
