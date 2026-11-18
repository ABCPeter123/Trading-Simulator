"""Synthetic only: training-screened cross-universe discovery and latency ranking."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from math import sin
import pytest
from fastapi.testclient import TestClient

from backend import basket_optimizer as basket
from backend import universe_research as research
from backend.main import app


def _universe_fixture():
    start=datetime(2018,1,1,tzinfo=timezone.utc)
    assets={}
    groups={}
    for idx in range(13):
        symbol=f"synthetic_{idx}"
        group=("equity","bond","commodity","real_estate")[idx%4]
        groups[symbol]=group
        rows=[]
        for i in range(1200):
            at=start+timedelta(days=i)
            if at.weekday()>4:continue
            price=(60+idx*2)*(1+.00011*(idx%6+1))**i*(1+.005*sin(i/(8+idx)))
            rows.append({"time":int(at.timestamp()),"open":price*1.0001,
                         "high":price*1.02,"low":price*.98,
                         "close":price,"volume":200000})
        assets[symbol]={"bars":rows}
    return assets,groups


def test_training_only_screen_unaffected_by_late_market_crash():
    original,groups=_universe_fixture()
    eligible=list(original)
    before=basket.discover(original,eligible,groups.__getitem__)
    damaged=deepcopy(original)
    # Shock only the last quarter, strictly after the conservative cutoff.
    for symbol in damaged:
        rows=damaged[symbol]["bars"]
        for row in rows[int(len(rows)*.75):]:
            for field in ("open","high","low","close"):
                row[field]*=.25
    after=basket.discover(damaged,eligible,groups.__getitem__)
    assert before==after
    assert before["cutoff_session"] is not None
    assert before["screened"]==13
    assert before["baskets"]
    assert len(before["baskets"])<=basket.MAX_EXTRA_BASKETS
    assert all(2<=len(symbols)<=16 and len(symbols)==len(set(symbols))
               for _,symbols in before["baskets"])
    assert len({tuple(sorted(symbols)) for _,symbols in before["baskets"]})==len(before["baskets"])
    assert "training" in before["method"] or "cutoff" in before["method"]


def test_bounded_screen_handles_no_history_and_rejects_invalid_budget():
    assert basket.discover({},[],lambda x:"equity")["baskets"]==[]
    histories,groups=_universe_fixture()
    with pytest.raises(ValueError):
        basket.discover(histories,list(histories),groups.__getitem__,max_extra=999)


def test_private_api_persists_exploration_and_rejects_invalid_modes(tmp_path,monkeypatch):
    monkeypatch.setattr(research,"DB_PATH",tmp_path/"studies.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    client=TestClient(app)
    result=client.post("/api/live/research/universe/jobs",json={
        "scope":"etfs","basket_search":"expanded",
        "selection_policy":"execution_robust","include_blends":True})
    assert result.status_code==202,result.text
    params=research.get_job(result.json()["id"])["params"]
    assert params["basket_search"]=="expanded"
    assert params["selection_policy"]=="execution_robust"
    for payload in ({"basket_search":"unbounded"},
                    {"selection_policy":"use_heldout"},
                    {"basket_search":None}):
        r=client.post("/api/live/research/universe/jobs",json=payload)
        assert r.status_code==422


def test_robust_validation_does_not_use_late_audit_to_select(monkeypatch):
    # Shared real-format OHLCV, but prices and symbols are synthetic-only.
    # The small known ETF list keeps the test deterministic and fast.
    ids=["spy","qqq","ief","gld","vti","tlt"]
    monkeypatch.setattr(research,"_universe",lambda scope:ids)
    start=datetime(2019,1,1,tzinfo=timezone.utc)
    bars=[]
    for i in range(1080):
        at=start+timedelta(days=i)
        if at.weekday()>4:continue
        px=75*(1.0004**i)*(1+.006*sin(i/17))
        bars.append({"time":int(at.timestamp()),"open":px*1.0001,
                     "high":px*1.015,"low":px*.985,
                     "close":px,"volume":50000})
    altered=deepcopy(bars)
    for row in altered[int(len(altered)*.82):]:
        for field in ("open","close","high","low"):
            row[field]*=.5
    settings={"scope":"all","delay_sessions":1,
              "max_drawdown_pct":60,"max_position_pct":45,
              "research_objective":"high_performance",
              "selection_policy":"execution_robust","basket_search":"focused",
              "include_blends":False}
    first=research.run_study(settings,loader=lambda symbol:{"bars":bars,"source":"Synthetic test"})
    changed=research.run_study(settings,loader=lambda symbol:{"bars":altered,"source":"Synthetic test"})
    assert first["test_used_for_selection"] is False
    assert first["selection_policy"]=="execution_robust"
    assert first["top10"]
    assert [(x["model"],x["symbols"],x["validation_score"])
            for x in first["top10"]]==[
            (x["model"],x["symbols"],x["validation_score"])
            for x in changed["top10"]]
    for row in first["top10"]:
        stress=row["validation_execution_stress"]
        assert stress is not None and stress["selection_only_validation_data"]
        assert stress["delay_sessions"]==2
        assert stress["slippage_bps"]>=20
        assert row["score_breakdown"]["components"]["execution_stress_points"]<=0
        assert row["score_breakdown"]["total"]==row["validation_score"]
