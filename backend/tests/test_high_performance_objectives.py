"""Synthetic regression tests for validation-only high-performance research.

These fixture curves and symbols are independently generated and do not
contain owner-specific strategy parameters, fills or optimized outputs.
"""
from datetime import datetime, timedelta, timezone
import math

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import performance_objectives as po
from backend import universe_research as ur
from backend.main import app


def _curve(n, daily=0.001):
    value=100_000.
    result=[]
    for i in range(n):
        value*=1+daily+0.003*math.sin(i/6)
        result.append({"time":int(datetime(2021,1,1,tzinfo=timezone.utc).timestamp())+86400*i,
                       "value":round(value,4)})
    return result


def _bars(days=1150, *,shock=False):
    start=datetime(2020,1,1,tzinfo=timezone.utc)
    bars=[]
    for i in range(days):
        day=start+timedelta(days=i)
        if day.weekday()>4:
            continue
        base=70*(1.0003**i)*(1+.007*math.sin(i/17))
        if shock and i>days*.81:
            base*=.50
        bars.append({"time":int(day.timestamp()),"open":base*1.0002,
                     "high":base*1.02,"low":base*.98,
                     "close":base,"volume":9000+i})
    return bars


def test_cash_rate_changes_excess_sharpe_not_growth():
    curve=_curve(252)
    zero=po.performance(curve,risk_free_pct=0)
    high=po.performance(curve,risk_free_pct=5)
    assert high["cagr_pct"]==zero["cagr_pct"]
    assert zero["excess_sharpe"]>high["excess_sharpe"]
    assert zero["annualized_volatility_pct"]==high["annualized_volatility_pct"]
    assert zero["sessions"]==252


def test_subperiod_validation_reconciles_and_is_diagnostic_only():
    curve=_curve(120)
    output=po.validation_windows(curve,risk_free_pct=3)
    assert output["sufficient_history"] is True
    assert output["window_count"]==3
    assert sum(x["sessions"] for x in output["windows"])==120
    combined=1.
    for item in output["windows"]:
        combined*=1+item["return_pct"]/100
    assert combined==pytest.approx(curve[-1]["value"]/100000,rel=1e-5)
    short=po.validation_windows(curve[:59])
    assert short["sufficient_history"] is False


def test_high_performance_score_excludes_insufficient_validation_history():
    valid={"return_pct":10,"max_drawdown_pct":-8,"turnover_pct":100,"trades":4}
    score,metrics,stability=po.score(valid,_curve(120),risk_free_pct=3)
    assert math.isfinite(score)
    assert metrics["cagr_pct"] is not None
    assert stability["sufficient_history"] is True
    not_enough,_,short=po.score(valid,_curve(65),risk_free_pct=3)
    assert not_enough==-1e6
    assert short["sufficient_history"] is False


def test_pareto_dominance_requires_both_objectives():
    one={"validation_objectives":{"cagr_pct":51,"excess_sharpe":2.1}}
    two={"validation_objectives":{"cagr_pct":48,"excess_sharpe":1.9}}
    mixed={"validation_objectives":{"cagr_pct":60,"excess_sharpe":1.5}}
    assert po.dominates(one,two)
    assert not po.dominates(one,mixed)
    assert not po.dominates(mixed,one)


@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(ur,"DB_PATH",tmp_path/"private_universe.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    return tmp_path


def test_queued_high_performance_goal_is_private_and_validated(database):
    client=TestClient(app)
    request={"scope":"etfs","research_objective":"high_performance",
             "target_cagr_pct":55,"target_sharpe":2,"risk_free_pct":3,
             "target_investment_pct":100,"equity_class_cap_pct":100,
             "redistribute_excess":True}
    response=client.post("/api/live/research/universe/jobs",json=request)
    assert response.status_code==202,response.text
    recorded=ur.get_job(response.json()["id"])
    assert recorded["params"]["target_cagr_pct"]==55
    assert recorded["params"]["research_objective"]=="high_performance"
    assert recorded["params"]["redistribute_excess"] is True
    assert recorded["result"] is None
    bad=client.post("/api/live/research/universe/jobs",json={**request,"target_sharpe":99})
    assert bad.status_code==422


def test_high_performance_ranking_never_reads_held_out_to_select(database,monkeypatch):
    instruments=["spy","qqq","ief","gld","eem","vnq","vti","xlv","tlt","shy"]
    monkeypatch.setattr(ur,"_universe",lambda scope:instruments)
    clean=_bars()
    changed=_bars(shock=True)
    assert ur._quality(clean) and ur._quality(changed)
    params={"scope":"all","delay_sessions":1,"max_drawdown_pct":60,
            "max_position_pct":40,"research_objective":"high_performance",
            "target_cagr_pct":55,"target_sharpe":2,
            "risk_free_pct":3,"target_investment_pct":100,
            "equity_class_cap_pct":100,"redistribute_excess":True}
    original=ur.run_study(params,loader=lambda s:{"source":"Synthetic fixture","bars":clean})
    shifted=ur.run_study(params,loader=lambda s:{"source":"Synthetic fixture","bars":changed})
    assert original["research_objective"]=="high_performance"
    assert original["test_used_for_selection"] is False
    assert original["qualified_candidates"]>=len(original["top10"])>=1
    assert [(x["model"],x["symbols"],x["validation_score"])
            for x in original["top10"]]==[
            (x["model"],x["symbols"],x["validation_score"])
            for x in shifted["top10"]]
    assert original["pareto_candidate_count"]>=1
    for x in original["top10"]:
        assert x["held_out_objectives"]["sessions"]>0
        assert x["validation_stability"]["sufficient_history"]
        assert x["validation_objectives"]["cagr_pct"] is not None
        assert "held_out_target_evaluable" in x
        assert x["no_real_order"] is True
